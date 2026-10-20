#!/usr/bin/env python3
"""Entry point of the bundled backend sidecar.

The desktop application starts this executable with:

    autobacklinker-api --host 127.0.0.1 --port 8765

and the following environment variables:

    AUTOBL_DATA_DIR        the OS application data directory (SQLite lives here)
    AUTOBL_ENVIRONMENT     "desktop"
    AUTOBL_STORAGE_MODE    "local"
    AUTOBL_WORKER_ENABLED  "true"
    AUTOBL_LOCAL_TOKEN     the random token of this installation

The launcher only wires uvicorn up - it never listens on a public interface.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _extend_sys_path() -> None:
    """Make the ``app`` package importable (zipapp / development fallback)."""
    here = Path(__file__).resolve().parent
    candidates = [
        here,  # zipapp: the API sources sit next to the archive
        here / "api",
        here.parent / "api",
        here.parent.parent / "api",
    ]
    for candidate in candidates:
        if (candidate / "app" / "main.py").is_file():
            sys.path.insert(0, str(candidate))
            return


def _parse_args(argv: list[str]) -> tuple[str, int]:
    host = os.environ.get("AUTOBL_HOST", "127.0.0.1")
    port = int(os.environ.get("AUTOBL_PORT", "8765"))
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--host" and index + 1 < len(argv):
            host = argv[index + 1]
            index += 2
            continue
        if argument.startswith("--host="):
            host = argument.split("=", 1)[1]
            index += 1
            continue
        if argument == "--port" and index + 1 < len(argv):
            port = int(argv[index + 1])
            index += 2
            continue
        if argument.startswith("--port="):
            port = int(argument.split("=", 1)[1])
            index += 1
            continue
        index += 1
    return host, port


def main() -> int:
    _extend_sys_path()

    host, port = _parse_args(sys.argv[1:])
    # The backend is a local component - never expose it on the network.
    if host not in ("127.0.0.1", "localhost"):
        print(
            f"[autobacklinker-api] refusing to bind to {host!r}; "
            "the desktop backend only listens on 127.0.0.1",
            file=sys.stderr,
        )
        return 2

    try:
        import uvicorn
    except ImportError as error:  # pragma: no cover - packaging problem
        print(f"[autobacklinker-api] uvicorn is missing: {error}", file=sys.stderr)
        return 3

    try:
        from app.main import app
    except Exception as error:  # pragma: no cover - broken bundle
        print(f"[autobacklinker-api] cannot import the backend: {error}", file=sys.stderr)
        return 4

    print(f"[autobacklinker-api] starting on http://{host}:{port}", flush=True)
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=os.environ.get("AUTOBL_LOG_LEVEL", "info"),
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
