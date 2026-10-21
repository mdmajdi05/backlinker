"""Contract tests between the backend, the shared client and the two apps.

The browser app (``apps/web``) and the desktop app (``apps/desktop``) talk to
the very same FastAPI backend through the very same typed client
(``packages/api-client``).  This module guards that invariant:

* every path the shared client uses exists in the OpenAPI schema,
* every operation of the OpenAPI schema is reachable through the client,
* every helper both apps use is part of the shared client,
* every DTO the client imports exists in ``packages/shared-types``.

The tests are deliberately static: they read the TypeScript sources and the
OpenAPI schema, therefore they fail fast when a client and the backend drift
apart - which is exactly what used to happen silently.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.main import app

ROOT = Path(__file__).resolve().parents[3]
API_CLIENT_PATH = ROOT / "packages" / "api-client" / "src" / "index.ts"
SHARED_TYPES_PATH = ROOT / "packages" / "shared-types" / "src" / "index.ts"
WEB_ROOT = ROOT / "apps" / "web"
DESKTOP_ROOT = ROOT / "apps" / "desktop"

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "upload", "download", "subscribe")

#: Transport helper -> HTTP verb of the backend.
TRANSPORT_METHOD = {
    "get": "get",
    "post": "post",
    "put": "put",
    "patch": "patch",
    "delete": "delete",
    "upload": "post",
    "download": "get",
    "subscribe": "get",
}


# --------------------------------------------------------------------------
# Tiny TypeScript scanner
# --------------------------------------------------------------------------


def _skip_string(src: str, i: int) -> int:
    quote = src[i]
    i += 1
    while i < len(src):
        if src[i] == "\\":
            i += 2
            continue
        if src[i] == quote:
            return i + 1
        i += 1
    return i


def _skip_template(src: str, i: int) -> int:
    """Skip a template literal, honouring nested ``${ ... }`` expressions."""
    i += 1
    while i < len(src):
        ch = src[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "`":
            return i + 1
        if ch == "$" and i + 1 < len(src) and src[i + 1] == "{":
            depth = 0
            j = i + 1
            while j < len(src):
                c = src[j]
                if c in "\"'":
                    j = _skip_string(src, j)
                    continue
                if c == "`":
                    j = _skip_template(src, j)
                    continue
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            i = j + 1
            continue
        i += 1
    return i


def _code_positions(src: str) -> list[int]:
    """Indices of the characters that are real code (not string or comment)."""
    positions: list[int] = []
    i = 0
    size = len(src)
    while i < size:
        ch = src[i]
        if ch == "/" and i + 1 < size and src[i + 1] == "/":
            while i < size and src[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < size and src[i + 1] == "*":
            end = src.find("*/", i + 2)
            i = size if end < 0 else end + 2
            continue
        if ch in "\"'":
            i = _skip_string(src, i)
            continue
        if ch == "`":
            i = _skip_template(src, i)
            continue
        positions.append(i)
        i += 1
    return positions


def _match_brace(src: str, start: int) -> int:
    """Index of the ``}`` that closes the ``{`` at ``start`` (``-1`` if none)."""
    depth = 0
    for index in _code_positions(src[start:]):
        char = src[start + index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return start + index
    return -1


def _expand_template(path: str) -> str:
    """Normalise a TypeScript template literal into an OpenAPI path template.

    ``${id}`` becomes ``{}`` (the OpenAPI parameter placeholder).  A
    substitution that only contributes a query string (``?project_id=...``) is
    dropped completely - the path itself stays the same.
    """
    out: list[str] = []
    i = 0
    while i < len(path):
        if path[i] == "$" and i + 1 < len(path) and path[i + 1] == "{":
            depth = 0
            j = i + 1
            while j < len(path):
                if path[j] == "{":
                    depth += 1
                elif path[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            expression = path[i + 2 : j]
            if "?" in expression:
                # a conditional query string - it does not change the path
                break
            out.append("{}")
            i = j + 1
            continue
        out.append(path[i])
        i += 1
    return "".join(out)


def _literal_at(src: str, i: int) -> tuple[str, int] | None:
    """Read the string / template literal that starts at ``i``."""
    if i >= len(src):
        return None
    if src[i] == "`":
        start = i + 1
        j = start
        while j < len(src):
            if src[j] == "\\":
                j += 2
                continue
            if src[j] == "`":
                return src[start:j], j + 1
            if src[j] == "$" and j + 1 < len(src) and src[j + 1] == "{":
                depth = 0
                k = j + 1
                while k < len(src):
                    c = src[k]
                    if c in "\"'":
                        k = _skip_string(src, k)
                        continue
                    if c == "`":
                        k = _skip_template(src, k)
                        continue
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    k += 1
                j = k + 1
                continue
            j += 1
        return None
    if src[i] in "\"'":
        start = i + 1
        j = start
        buf: list[str] = []
        while j < len(src):
            if src[j] == "\\":
                buf.append(src[j : j + 2])
                j += 2
                continue
            if src[j] == src[i]:
                return "".join(buf), j + 1
            buf.append(src[j])
            j += 1
    return None


def _transport_calls(src: str) -> list[tuple[str, str]]:
    """All ``(http_method, path)`` pairs used by the transport layer."""
    calls: list[tuple[str, str]] = []
    pattern = re.compile(
        r"(?<![\w.$])([A-Za-z_$][\w$]*)\.(" + "|".join(HTTP_METHODS) + r")\b"
    )
    for match in pattern.finditer(src):
        verb = TRANSPORT_METHOD[match.group(2)]
        index = match.end()
        # optional generic type argument: <Paginated<Project>>
        while index < len(src) and src[index] in " \t\r\n":
            index += 1
        if index < len(src) and src[index] == "<":
            depth = 0
            while index < len(src):
                if src[index] == "<":
                    depth += 1
                elif src[index] == ">":
                    depth -= 1
                    if depth == 0:
                        index += 1
                        break
                index += 1
        while index < len(src) and src[index] in " \t\r\n":
            index += 1
        if index >= len(src) or src[index] != "(":
            continue
        index += 1
        while index < len(src) and src[index] in " \t\r\n":
            index += 1
        literal = _literal_at(src, index)
        if literal is None:
            continue
        raw, _end = literal
        path = _expand_template(raw)
        path = path.split("?")[0]
        if not path.startswith("/"):
            continue
        calls.append((verb, path))
    return calls


def _is_member_separator(src: str, positions: list[int], index: int) -> bool:
    """Does the comma at ``index`` end an object member?

    A comma inside a generic type argument (``Record<string, unknown>``) does
    not - only a comma followed by ``key:`` or by the end of the object does.
    """
    for position in positions[index + 1 :]:
        if src[position] in " \t\r\n":
            continue
        if src[position] == "}":
            return True
        match = re.match(r"[A-Za-z_$][\w$]*", src[position:])
        if not match:
            return False
        after = position + match.end()
        while after < len(src) and src[after] in " \t\r\n":
            after += 1
        return after < len(src) and src[after] == ":"
    return False


def _object_members(src: str, content_start: int, content_end: int) -> list[tuple[str, int, int]]:
    """Members of the object literal whose *content* lies between the indices.

    Returns ``(key, value_start, value_end)`` triples.  Brackets of every
    kind are tracked, therefore a comma inside an argument list does not end
    a member.
    """
    members: list[tuple[str, int, int]] = []
    positions = _code_positions(src)
    depth = 0
    key: str | None = None
    value_start = 0
    for index, position in enumerate(positions):
        if position < content_start:
            continue
        if position >= content_end:
            break
        char = src[position]
        if char in "{([":
            depth += 1
            continue
        if char in "})]":
            depth -= 1
            continue
        if depth != 0:
            continue
        if char == ",":
            if key is not None and _is_member_separator(src, positions, index):
                members.append((key, value_start, position))
                key = None
            continue
        if key is None:
            match = re.match(r"[A-Za-z_$][\w$]*", src[position:])
            if match:
                key = match.group(0)
                value_start = position + match.end()
    if key is not None:
        members.append((key, value_start, content_end))
    return members


def _first_brace(src: str, start: int, end: int) -> int:
    """Index of the first ``{`` of the value, ``-1`` when there is none."""
    for position in _code_positions(src):
        if start <= position < end and src[position] == "{":
            return position
    return -1


def _api_helpers(src: str) -> dict[str, tuple[str, str]]:
    """Map ``area.action`` to ``(http_method, path)`` for the shared client.

    The helper is looked up in the ``export const api = { ... }`` object; the
    ``auth`` area is a factory and therefore handled separately.
    """
    helpers: dict[str, tuple[str, str]] = {}
    marker = "export const api = {"
    index = src.find(marker)
    if index < 0:
        return helpers
    body_start = index + len(marker) - 1
    body_end = _match_brace(src, body_start)
    if body_end < 0:
        return helpers

    for area, area_start, area_end in _object_members(src, body_start + 1, body_end):
        if area == "auth":
            continue
        area_brace = _first_brace(src, area_start, area_end)
        if area_brace < 0:
            continue
        area_content_end = _match_brace(src, area_brace)
        if area_content_end < 0:
            continue
        for action, value_start, value_end in _object_members(
            src, area_brace + 1, area_content_end
        ):
            chunk = src[value_start:value_end]
            call = _transport_calls(chunk)
            if not call:
                continue
            verb, path = call[0]
            helpers[f"{area}.{action}"] = (verb, path)

    # The auth area is created by a factory function.
    factory = src.find("export const createAuthApi")
    if factory >= 0:
        chunk = src[factory : factory + 2000]
        for action, verb, path in re.findall(
            r"(\w+):\s*\([^)]*\)\s*=>\s*client\.(\w+)<[^>]*>\(\s*[`\"]([^`\"]+)[`\"]", chunk
        ):
            helpers[f"auth.{action}"] = (TRANSPORT_METHOD[verb], path)
    return helpers


def _used_api_helpers(src: str) -> set[str]:
    """The ``api.<area>.<action>`` helpers an app actually uses."""
    used = {
        f"{match.group(1)}.{match.group(2)}"
        for match in re.finditer(r"(?<![\w.$])api\.([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*)", src)
    }
    # The auth helpers are used through the factory: ``api.auth(client)`` and
    # the ``authApi`` alias the apps keep around.
    used |= {
        f"auth.{match.group(1)}"
        for match in re.finditer(r"(?<![\w.$])api\.auth\([^)]*\)\.([A-Za-z_$][\w$]*)", src)
    }
    used |= {
        f"auth.{match.group(1)}"
        for match in re.finditer(r"(?<![\w.$])authApi\.([A-Za-z_$][\w$]*)", src)
    }
    return used


def _typescript_sources(root: Path, skip_dirs: tuple[str, ...] = ()) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        relative = path.relative_to(root)
        parts = set(relative.parts)
        if parts & {"node_modules", ".next", "dist", ".sidecar-venv", "target"}:
            continue
        if parts & set(skip_dirs):
            continue
        try:
            files[str(relative)] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover - defensive
            continue
    return files


def _exported_names(src: str) -> set[str]:
    return set(
        re.findall(
            r"^export\s+(?:declare\s+)?(?:interface|type|const|enum|class|function|abstract\s+class)\s+"
            r"([A-Za-z_$][\w$]*)",
            src,
            re.MULTILINE,
        )
    )


def _imported_shared_types(src: str) -> set[str]:
    """The DTOs the client imports from ``@autobacklinker/shared-types``."""
    names: set[str] = set()
    for block in re.findall(
        r"import\s+type\s*\{([^}]*)\}\s*from\s*[\"']@autobacklinker/shared-types[\"']",
        src,
    ):
        for entry in block.split(","):
            entry = entry.strip()
            if not entry:
                continue
            names.add(entry.split(" as ")[0].strip())
    return names


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def openapi_operations() -> set[tuple[str, str]]:
    """Every ``(method, path)`` of the OpenAPI schema, parameters normalised."""
    spec = app.openapi()
    operations: set[tuple[str, str]] = set()
    for path, item in spec["paths"].items():
        normalised = re.sub(r"\{[^}]+\}", "{}", path)
        for method in item:
            if method in {"get", "post", "put", "patch", "delete"}:
                operations.add((method.upper(), normalised))
    return operations


@pytest.fixture(scope="session")
def api_client_source() -> str:
    return API_CLIENT_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def client_helpers(api_client_source: str) -> dict[str, tuple[str, str]]:
    return _api_helpers(api_client_source)


@pytest.fixture(scope="session")
def web_helpers() -> set[str]:
    used: set[str] = set()
    for source in _typescript_sources(WEB_ROOT).values():
        used |= _used_api_helpers(source)
    return used


@pytest.fixture(scope="session")
def desktop_helpers() -> set[str]:
    used: set[str] = set()
    for source in _typescript_sources(DESKTOP_ROOT, skip_dirs=("src-tauri",)).values():
        used |= _used_api_helpers(source)
    return used


# --------------------------------------------------------------------------
# The contract
# --------------------------------------------------------------------------


def test_openapi_schema_is_not_empty(openapi_operations: set[tuple[str, str]]) -> None:
    assert len(openapi_operations) > 50, "the OpenAPI schema looks suspiciously small"


def test_every_client_path_exists_in_the_backend(
    api_client_source: str,
    openapi_operations: set[tuple[str, str]],
) -> None:
    """Every path the shared client calls exists in the OpenAPI schema."""
    missing = []
    for verb, path in _transport_calls(api_client_source):
        if (verb.upper(), path) not in openapi_operations:
            missing.append(f"{verb.upper():6} {path}")
    assert not missing, (
        "The API client calls endpoints the backend does not serve:\n"
        + "\n".join(f"  - {item}" for item in sorted(set(missing)))
    )


def test_every_backend_operation_is_reachable_from_the_client(
    client_helpers: dict[str, tuple[str, str]],
    openapi_operations: set[tuple[str, str]],
) -> None:
    """No backend endpoint may be unreachable for the clients."""
    reachable = {(verb.upper(), path) for verb, path in client_helpers.values()}
    unreachable = sorted(
        f"{method:6} {path}"
        for method, path in openapi_operations
        if (method, path) not in reachable
    )
    assert not unreachable, (
        "The backend offers endpoints no client helper can reach:\n"
        + "\n".join(f"  - {item}" for item in unreachable)
        + "\nAdd a helper to packages/api-client/src/index.ts "
        "(naming convention: api.<area>.<action>(client, ...))."
    )


def test_client_helpers_resolve_to_the_backend(
    client_helpers: dict[str, tuple[str, str]],
    openapi_operations: set[tuple[str, str]],
) -> None:
    """Every helper of the shared client points at a real backend operation."""
    broken = [
        f"api.{name} -> {verb.upper()} {path}"
        for name, (verb, path) in sorted(client_helpers.items())
        if (verb.upper(), path) not in openapi_operations
    ]
    assert not broken, "These client helpers do not match any backend endpoint:\n" + "\n".join(
        f"  - {item}" for item in broken
    )


@pytest.mark.parametrize("app", ["web", "desktop"])
def test_every_app_helper_exists_in_the_shared_client(
    app: str,
    client_helpers: dict[str, tuple[str, str]],
    web_helpers: set[str],
    desktop_helpers: set[str],
) -> None:
    """Both apps may only use helpers that the shared client provides."""
    used = web_helpers if app == "web" else desktop_helpers
    missing = sorted(used - set(client_helpers))
    web_only = sorted(web_helpers - desktop_helpers)
    desktop_only = sorted(desktop_helpers - web_helpers)
    assert not missing, (
        f"The {app} app uses helpers that packages/api-client does not provide:\n"
        + "\n".join(f"  - {item}" for item in missing)
        + "\n\nFeature difference between the two clients:\n"
        + f"  web only    : {web_only}\n"
        + f"  desktop only: {desktop_only}"
    )


@pytest.mark.parametrize("app", ["web", "desktop"])
def test_every_app_path_is_served_by_the_backend(
    app: str,
    client_helpers: dict[str, tuple[str, str]],
    web_helpers: set[str],
    desktop_helpers: set[str],
    openapi_operations: set[tuple[str, str]],
) -> None:
    """Every endpoint both apps use is really served by the backend."""
    used = web_helpers if app == "web" else desktop_helpers
    missing = []
    for name in sorted(used):
        helper = client_helpers.get(name)
        if helper is None:
            missing.append(f"api.{name} (no helper in the shared client)")
            continue
        verb, path = helper
        if (verb.upper(), path) not in openapi_operations:
            missing.append(f"api.{name} -> {verb.upper()} {path}")
    assert not missing, (
        f"The {app} app relies on endpoints the backend does not serve:\n"
        + "\n".join(f"  - {item}" for item in missing)
    )


def test_desktop_can_reach_every_web_capability(
    client_helpers: dict[str, tuple[str, str]],
    web_helpers: set[str],
    desktop_helpers: set[str],
    openapi_operations: set[tuple[str, str]],
) -> None:
    """The desktop client must be able to do everything the web client can.

    Both apps consume the very same ``@autobacklinker/api-client`` package, so
    the desktop can reach a web capability as soon as the shared client
    offers it.  This test therefore checks that the *contract* is complete -
    the UI of the desktop app may still be catching up.
    """
    contract = set(client_helpers)
    missing_for_desktop = sorted(web_helpers - contract)
    missing_for_web = sorted(desktop_helpers - contract)

    assert not missing_for_desktop, (
        "The desktop client cannot reach these web capabilities - the shared "
        "client is missing them:\n"
        + "\n".join(f"  - api.{item}" for item in missing_for_desktop)
    )
    assert not missing_for_web, (
        "The web client cannot reach these desktop capabilities - the shared "
        "client is missing them:\n"
        + "\n".join(f"  - api.{item}" for item in missing_for_web)
    )

    # Every capability of the shared contract is served by the backend.
    unserved = sorted(
        f"api.{name} -> {verb.upper()} {path}"
        for name, (verb, path) in client_helpers.items()
        if (verb.upper(), path) not in openapi_operations
    )
    assert not unserved, "These shared capabilities are not served by the backend:\n" + "\n".join(
        f"  - {item}" for item in unserved
    )


def test_both_apps_use_the_same_shared_client() -> None:
    """The web and the desktop app must not drift apart transport wise."""
    web_imports = "\n".join(_typescript_sources(WEB_ROOT).values())
    desktop_imports = "\n".join(
        _typescript_sources(DESKTOP_ROOT, skip_dirs=("src-tauri",)).values()
    )
    assert "@autobacklinker/api-client" in web_imports, (
        "the web app must talk to the backend through @autobacklinker/api-client"
    )
    assert "@autobacklinker/api-client" in desktop_imports, (
        "the desktop app must talk to the backend through @autobacklinker/api-client"
    )


def test_shared_dtos_referenced_by_the_client_exist(api_client_source: str) -> None:
    """Every DTO the client imports exists in ``packages/shared-types``."""
    shared = _exported_names(SHARED_TYPES_PATH.read_text(encoding="utf-8"))
    imported = _imported_shared_types(api_client_source)
    missing = sorted(imported - shared)
    assert not missing, (
        "packages/api-client imports DTOs that packages/shared-types does not "
        "export:\n" + "\n".join(f"  - {item}" for item in missing)
    )
    assert imported, "no shared DTOs found - the import block moved?"


def test_client_helpers_cover_the_shared_dtos(api_client_source: str) -> None:
    """The client uses the shared DTOs instead of inventing inline shapes."""
    shared = _exported_names(SHARED_TYPES_PATH.read_text(encoding="utf-8"))
    imported = _imported_shared_types(api_client_source)
    # A couple of DTOs are only used as building blocks of other DTOs.
    assert len(imported & shared) == len(imported)


# --------------------------------------------------------------------------
# The endpoints that were added to close the contract gaps
# --------------------------------------------------------------------------


def test_adapter_detail_endpoint(authenticated_client) -> None:
    """``GET /api/v1/adapters/{id}`` serves a single adapter."""
    adapters = authenticated_client.get("/api/v1/adapters")
    assert adapters.status_code == 200, adapters.text
    items = adapters.json()
    assert items, "the registry seeds at least one adapter"

    detail = authenticated_client.get(f"/api/v1/adapters/{items[0]['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == items[0]["id"]
    assert detail.json()["key"] == items[0]["key"]


def test_adapter_detail_uses_the_error_envelope(authenticated_client) -> None:
    """A missing adapter answers with ``{"error": {...}}``."""
    response = authenticated_client.get("/api/v1/adapters/does-not-exist")
    assert response.status_code == 404, response.text
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"]


def test_project_websites_endpoint(authenticated_client) -> None:
    """``GET /api/v1/projects/{id}/websites`` lists the landing pages."""
    project = authenticated_client.post(
        "/api/v1/projects",
        json={
            "name": "Landing Pages",
            "target_website": "https://landing.example",
            "landing_pages": [
                {"name": "Main", "url": "https://landing.example/", "kind": "MAIN"},
                {"name": "Blog", "url": "https://landing.example/blog", "kind": "BLOG"},
            ],
        },
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]

    response = authenticated_client.get(f"/api/v1/projects/{project_id}/websites")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert {item["kind"] for item in body["items"]} == {"MAIN", "BLOG"}
    assert all(item["project_id"] == project_id for item in body["items"])

    filtered = authenticated_client.get(f"/api/v1/projects/{project_id}/websites?kind=BLOG")
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 1


def test_project_websites_uses_the_error_envelope(authenticated_client) -> None:
    response = authenticated_client.get("/api/v1/projects/does-not-exist/websites")
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"


def test_imports_and_reports_accept_filters(authenticated_client, project_id: str) -> None:
    """The list endpoints of the data flow support filtering."""
    imports = authenticated_client.get(f"/api/v1/imports?project_id={project_id}")
    assert imports.status_code == 200, imports.text
    assert imports.json()["total"] == 0

    reports = authenticated_client.get(f"/api/v1/reports?project_id={project_id}&status=COMPLETED")
    assert reports.status_code == 200, reports.text
    assert reports.json()["total"] == 0


def test_discovery_runs_accept_filters(authenticated_client, project_id: str) -> None:
    runs = authenticated_client.get(f"/api/v1/discovery/runs?project_id={project_id}&status=PENDING")
    assert runs.status_code == 200, runs.text
    assert runs.json()["total"] == 0

    providers = authenticated_client.get("/api/v1/discovery/providers")
    assert providers.status_code == 200, providers.text
    assert all("requires_credentials" in item for item in providers.json())


def test_new_endpoints_require_authentication(client) -> None:
    """Every new endpoint is protected by the regular authentication."""
    for method, path in (
        ("GET", "/api/v1/adapters/some-id"),
        ("GET", "/api/v1/projects/some-id/websites"),
        ("GET", "/api/v1/adapters/some-id/configuration"),
    ):
        response = client.request(method, path)
        assert response.status_code == 401, f"{method} {path} -> {response.text}"
        assert response.json()["error"]["code"] == "not_authenticated"


def test_system_endpoints_stay_public(client) -> None:
    """``/health`` and ``/api/v1/system/info`` are deliberately public.

    The desktop app asks the backend for its version before it has a session.
    """
    health = client.get("/health")
    assert health.status_code == 200, health.text
    assert health.json()["status"] == "ok"

    info = client.get("/api/v1/system/info")
    assert info.status_code == 200, info.text
    assert info.json()["version"]
    assert info.json()["database_type"] in {"sqlite", "postgresql"}
