"""Tests for the isolated browser automation and the resource aware scheduling.

The tests must not open a browser - they check the decisions, the isolation
guarantees and the control flow.
"""

from __future__ import annotations

API = "/api/v1"


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------

def test_the_browser_never_uses_the_personal_profile() -> None:
    from app.services import browser

    isolation = browser.isolation_summary()
    assert isolation["personal_profile_used"] is False
    assert isolation["own_profile_directory"] is True
    assert isolation["headless_by_default"] is True
    assert isolation["extensions_disabled"] is True

    # The profile lives in the application data directory, never in the
    # profile of the personal browser.
    profile = str(browser.profile_dir())
    assert profile.endswith("browser-profile")
    assert str(browser.browsers_dir()).endswith("browsers")
    assert "Chrome" not in profile
    assert "Google" not in profile
    assert "Firefox" not in profile


def test_the_isolation_arguments_disable_extensions_and_sync() -> None:
    from app.services.browser import ISOLATION_ARGS

    assert "--disable-extensions" in ISOLATION_ARGS
    assert "--disable-sync" in ISOLATION_ARGS
    assert "--no-first-run" in ISOLATION_ARGS
    assert "--password-store=basic" in ISOLATION_ARGS
    assert "--use-mock-keychain" in ISOLATION_ARGS
    # Nothing may point at a user profile directory.
    assert not any("profile-directory" in argument for argument in ISOLATION_ARGS)
    assert not any("user-data-dir" in argument for argument in ISOLATION_ARGS)


def test_the_launch_options_are_explicit() -> None:
    from app.services import browser

    options = browser.launch_options(headless=True)
    assert options["headless"] is True
    assert options["isolated"] is True
    assert options["user_data_dir"] == str(browser.profile_dir())
    assert "--disable-extensions" in options["args"]


def test_the_environment_drops_browser_pointing_variables(monkeypatch) -> None:
    from app.services import browser

    monkeypatch.setenv("CHROME_PROFILE", "/Users/somebody/Library/Application Support/Google/Chrome")
    monkeypatch.setenv("BROWSER_POINT", "/Applications/Google Chrome.app")
    env = browser.isolated_environment()
    assert "CHROME_PROFILE" not in env
    assert "BROWSER_POINT" not in env
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(browser.browsers_dir())


def test_the_on_demand_playwright_runtime_is_made_importable(tmp_path, monkeypatch) -> None:
    """The desktop bundle installs Playwright into the data directory."""
    import os
    import sys

    from app.core.config import settings
    from app.services import browser

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    packages = tmp_path / "py"
    packages.mkdir()
    (tmp_path / "browsers" / "chromium-1248").mkdir(parents=True)

    try:
        browser.ensure_playwright_path()

        assert str(packages) in sys.path
        # The driver process must look in the data directory, or it would not
        # find the browser that `install_runtime` downloaded there.
        assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(tmp_path / "browsers")
    finally:
        if str(packages) in sys.path:
            sys.path.remove(str(packages))
        os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)


def test_an_empty_browser_directory_does_not_hide_the_default_cache(tmp_path, monkeypatch) -> None:
    import os

    from app.core.config import settings
    from app.services import browser

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    (tmp_path / "browsers").mkdir()

    browser.ensure_playwright_path()

    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ


def test_the_playwright_adapter_uses_the_isolation_arguments() -> None:
    import inspect

    from app.services.adapters.impl.playwright_form import PlaywrightFormAdapter

    source = inspect.getsource(PlaywrightFormAdapter.submit)
    assert "ISOLATION_ARGS" in source
    assert "headless=headless" in source
    # The headless flag comes from the context (execution settings).
    assert "settings.playwright_headless" not in source


# ---------------------------------------------------------------------------
# Resource aware scheduling
# ---------------------------------------------------------------------------

def test_the_governor_lowers_the_limit_when_the_machine_is_busy() -> None:
    from app.services.resources import ResourceGovernor, ResourceSnapshot

    governor = ResourceGovernor()
    busy = ResourceSnapshot(
        cpu_percent=92.0,
        load_average=6.0,
        memory_total_mb=16000,
        memory_available_mb=300,
        memory_used_percent=98.0,
        disk_free_mb=50000,
        cpu_count=8,
    )
    governor._snapshot = busy
    governor._last_sample = 9_999_999_999

    limit, reason = governor.effective_limit(4, "max_speed")
    assert limit == 1
    assert "heavy load" in reason


def test_the_governor_respects_the_resource_preference() -> None:
    from app.services.resources import ResourceGovernor, ResourceSnapshot

    governor = ResourceGovernor()
    idle = ResourceSnapshot(
        cpu_percent=5.0,
        load_average=0.5,
        memory_total_mb=16000,
        memory_available_mb=9000,
        memory_used_percent=30.0,
        disk_free_mb=50000,
        cpu_count=8,
    )
    governor._snapshot = idle
    governor._last_sample = 9_999_999_999

    fast, _ = governor.effective_limit(4, "max_speed")
    balanced, _ = governor.effective_limit(4, "balanced")
    careful, _ = governor.effective_limit(4, "save_resources")

    assert fast >= balanced >= careful
    assert careful >= 1


def test_the_preference_never_produces_zero() -> None:
    from app.services.resources import ResourceGovernor, ResourceSnapshot

    governor = ResourceGovernor()
    idle = ResourceSnapshot(1.0, 0.1, 16000, 9000, 10.0, 50000, 8)
    governor._snapshot = idle
    governor._last_sample = 9_999_999_999
    limit, _ = governor.effective_limit(1, "save_resources")
    assert limit >= 1


# ---------------------------------------------------------------------------
# Execution control
# ---------------------------------------------------------------------------

def test_the_execution_can_be_paused_and_resumed(authenticated_client) -> None:
    paused = authenticated_client.post(f"{API}/worker/pause")
    assert paused.status_code == 200
    assert paused.json()["execution"]["state"] == "PAUSED"

    resumed = authenticated_client.post(f"{API}/worker/resume")
    assert resumed.status_code == 200
    assert resumed.json()["execution"]["state"] == "RUNNING"


def test_stopping_marks_the_running_tasks_for_cancellation(
    authenticated_client, db_session
) -> None:
    from app.db.models import Task

    task = Task(
        type="SUBMIT",
        status="RUNNING",
        idempotency_key="stop-me",
    )
    db_session.add(task)
    db_session.commit()

    stopped = authenticated_client.post(f"{API}/worker/stop")
    assert stopped.status_code == 200
    assert stopped.json()["execution"]["state"] == "STOPPED"

    db_session.expire_all()
    stored = db_session.get(Task, task.id)
    assert stored.cancel_requested is True

    # back to running for the other tests
    authenticated_client.post(f"{API}/worker/resume")


def test_the_worker_settings_are_validated(authenticated_client) -> None:
    invalid = authenticated_client.put(
        f"{API}/worker/settings", json={"resource_preference": "turbo"}
    )
    assert invalid.status_code == 400

    valid = authenticated_client.put(
        f"{API}/worker/settings",
        json={"max_browser_jobs": 3, "resource_preference": "save_resources", "headless": False},
    )
    assert valid.status_code == 200
    execution = valid.json()["execution"]
    assert execution["max_browser_jobs"] == 3
    assert execution["resource_preference"] == "save_resources"
    assert execution["headless"] is False

    authenticated_client.put(f"{API}/worker/settings", json={"headless": True})


def test_the_worker_status_reports_the_resources_and_the_location(authenticated_client) -> None:
    response = authenticated_client.get(f"{API}/worker/status")
    assert response.status_code == 200
    body = response.json()
    assert "resources" in body
    assert "effective_limit" in body["resources"]
    assert body["browser"]["isolation"]["personal_profile_used"] is False
    assert body["execution"]["state"] in ("RUNNING", "PAUSED", "STOPPED")


def test_the_browser_status_is_reported(authenticated_client) -> None:
    response = authenticated_client.get(f"{API}/browser/status")
    assert response.status_code == 200
    body = response.json()
    assert body["headless"] is True
    assert body["isolation"]["own_profile_directory"] is True
    assert body["browsers_dir"]


def test_cancelling_a_running_task_asks_it_to_stop(authenticated_client, db_session) -> None:
    from app.db.models import Task

    task = Task(type="SUBMIT", status="RUNNING", idempotency_key="cancel-me")
    db_session.add(task)
    db_session.commit()

    response = authenticated_client.post(f"{API}/tasks/{task.id}/cancel")
    assert response.status_code == 200

    db_session.expire_all()
    stored = db_session.get(Task, task.id)
    assert stored.cancel_requested is True
    assert stored.status == "CANCELLED"


def test_the_worker_does_not_claim_jobs_while_paused(authenticated_client, db_session) -> None:
    from app.services import queue as queue_service
    from app.services.execution import pause, resume
    from app.workers.runner import Worker

    _task, created = queue_service.enqueue(
        db_session, task_type="SUBMIT", idempotency_key="paused-job"
    )
    assert created

    pause(db_session)
    try:
        worker = Worker(worker_id="test-worker")
        assert worker.tick() == 0
    finally:
        resume(db_session)

    worker = Worker(worker_id="test-worker")
    assert worker.tick() >= 1
    db_session.rollback()
