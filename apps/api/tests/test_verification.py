"""Verification tests (skipped until the verification engine exists).

The verification engine fetches the published page and looks for the expected
link.  The tests use a local HTTP server on 127.0.0.1 - the SSRF guard is
relaxed for the test process (``AUTOBL_ALLOW_PRIVATE_NETWORK``) so the local
fixture can be reached.  No third party host is ever contacted.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.core.config import settings
from app.db.models import BacklinkRecord, VerificationRun
from app.services import queue as queue_service
from tests.conftest import API

verification = pytest.importorskip(
    "app.services.verification",
    reason="the verification engine (app.services.verification) is not available yet",
    exc_type=ImportError,
)

TARGET_URL = "https://target.example/product"
ANCHOR_TEXT = "Acme Analytics"

PAGE_WITH_LINK = f"""<html><body>
<h1>Business directory</h1>
<p>Our partner <a href="{TARGET_URL}">{ANCHOR_TEXT}</a> is listed here.</p>
</body></html>"""

PAGE_WITHOUT_LINK = """<html><body>
<h1>Business directory</h1>
<p>No backlink on this page.</p>
</body></html>"""


class _FixtureHandler(BaseHTTPRequestHandler):
    """Serves two pages: one with the expected link, one without."""

    def do_GET(self) -> None:  # the name is imposed by http.server
        body = PAGE_WITH_LINK if self.path.startswith("/with-link") else PAGE_WITHOUT_LINK
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:  # pragma: no cover - keep the output clean
        return


@pytest.fixture
def local_server(monkeypatch: pytest.MonkeyPatch):
    """A local HTTP server plus the relaxed SSRF guard it needs."""
    monkeypatch.setattr(settings, "allow_private_network", True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _create_record(db_session, project_id: str, published_page_url: str) -> BacklinkRecord:
    record = BacklinkRecord(
        project_id=project_id,
        target_website=published_page_url,
        expected_link_url=published_page_url,
        published_page_url=published_page_url,
        expected_destination_url=TARGET_URL,
        verification_status="PUBLISHED_UNVERIFIED",
        evidence={},
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    return record


def _verify(db_session, record: BacklinkRecord):
    task, _created = queue_service.enqueue(
        db_session,
        task_type="VERIFY",
        project_id=record.project_id,
        payload={"backlink_id": record.id, "force": True},
        idempotency_key=f"VERIFY:{record.id}:test",
    )
    return verification.verify_task(db_session, task)


def test_a_live_link_is_verified(local_server, db_session, project_id) -> None:
    published = f"{local_server}/with-link"
    record = _create_record(db_session, project_id, published)

    _verify(db_session, record)

    db_session.rollback()
    refreshed = db_session.get(BacklinkRecord, record.id)
    assert refreshed.verification_status == "VERIFIED_LIVE"
    assert refreshed.link_present is True
    assert refreshed.destination_matched is True
    assert refreshed.is_live is True
    assert refreshed.observed_destination_url is not None
    assert ANCHOR_TEXT in (refreshed.observed_anchor_text or "")
    assert refreshed.verified_at is not None
    assert db_session.query(VerificationRun).filter_by(backlink_id=record.id).count() >= 1


def test_a_missing_link_fails_the_verification(local_server, db_session, project_id) -> None:
    published = f"{local_server}/without-link"
    record = _create_record(db_session, project_id, published)

    _verify(db_session, record)

    db_session.rollback()
    refreshed = db_session.get(BacklinkRecord, record.id)
    assert refreshed.verification_status == "VERIFICATION_FAILED"
    assert refreshed.link_present is False
    assert refreshed.is_live is not True


def test_the_verification_records_are_listed_by_the_api(
    local_server, authenticated_client, db_session, project_id
) -> None:
    published = f"{local_server}/with-link"
    record = _create_record(db_session, project_id, published)
    _verify(db_session, record)

    listing = authenticated_client.get(
        f"{API}/verification/records", params={"project_id": project_id}
    )
    assert listing.status_code == 200, listing.text
    assert record.id in [item["id"] for item in listing.json()["items"]]

    history = authenticated_client.get(f"{API}/verification/records/{record.id}/history")
    assert history.status_code == 200, history.text
    assert len(history.json()) >= 1
