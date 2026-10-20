"""The daemon loop of the agent.

Responsibilities:

* send a heartbeat in a fixed interval,
* claim a task, execute it and report the result,
* survive a backend outage (exponential backoff, offline mode),
* shut down gracefully on SIGINT / SIGTERM.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from typing import Any

from .client import BackendClient, BackendError
from .config import AgentConfig, utc_now
from .executor import TaskExecutor, TaskOutcome
from .transport import TransportError

LOG = logging.getLogger("agent.runner")

MAX_BACKOFF_SECONDS = 60.0
BASE_BACKOFF_SECONDS = 1.0


class AgentRunner:
    def __init__(
        self,
        config: AgentConfig,
        client: BackendClient,
        executor: TaskExecutor | None = None,
        poll_interval: float | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.executor = executor or TaskExecutor()
        self.poll_interval = float(
            poll_interval if poll_interval is not None else config.poll_interval_seconds
        )
        self.stop_event = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_stop = threading.Event()

    # -- lifecycle -----------------------------------------------------
    def request_stop(self, *_args: Any) -> None:
        LOG.info("Shutdown requested - finishing the current task")
        self.stop_event.set()
        self._heartbeat_stop.set()

    def install_signal_handlers(self) -> None:
        for signal_name in ("SIGINT", "SIGTERM"):
            handler = getattr(signal, signal_name, None)
            if handler is not None:
                try:
                    signal.signal(handler, self.request_stop)
                except (ValueError, OSError):  # pragma: no cover - non main thread
                    LOG.debug("Cannot install the %s handler", signal_name)

    # -- heartbeat -----------------------------------------------------
    def start_heartbeat(self, interval: float = 30.0) -> None:
        def loop() -> None:
            while not self._heartbeat_stop.is_set():
                try:
                    self.client.heartbeat(
                        status="ONLINE", capabilities=self.config.capabilities
                    )
                    self.config.last_seen = utc_now()
                except (TransportError, BackendError) as error:
                    LOG.warning("Heartbeat failed: %s", error)
                except Exception as error:  # pragma: no cover - defensive
                    LOG.warning("Heartbeat failed: %s", error)
                self._heartbeat_stop.wait(interval)

        self._heartbeat_thread = threading.Thread(
            target=loop, name="agent-heartbeat", daemon=True
        )
        self._heartbeat_thread.start()

    def stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=5)

    def send_offline_heartbeat(self) -> None:
        try:
            self.client.heartbeat(status="OFFLINE", capabilities=self.config.capabilities)
        except (TransportError, BackendError) as error:
            LOG.warning("Could not send the offline heartbeat: %s", error)

    # -- task processing -----------------------------------------------
    def run_once(self) -> TaskOutcome | None:
        """Claims and executes a single task. ``None`` means "nothing to do"."""
        try:
            task = self.client.claim_task()
        except (TransportError, BackendError) as error:
            LOG.warning("Could not claim a task: %s", error)
            return None

        if not task:
            LOG.debug("No task available")
            return None

        task_id = str(task.get("id", "unknown"))
        task_type = str(task.get("type", "unknown"))
        LOG.info("Claimed task %s (%s)", task_id, task_type)

        try:
            outcome = self.executor.execute(task)
        except Exception as error:  # pragma: no cover - defensive
            LOG.exception("Task %s crashed", task_id)
            outcome = TaskOutcome(
                status="FAILED",
                result={},
                error=f"{type(error).__name__}: {error}",
            )

        try:
            self.client.report_task(
                task_id,
                status=outcome.status,
                result=outcome.to_payload(),
                error=outcome.error,
            )
            LOG.info("Reported task %s as %s", task_id, outcome.status)
        except (TransportError, BackendError) as error:
            LOG.error("Could not report task %s: %s", task_id, error)
        return outcome

    def run_forever(self) -> int:
        """The daemon loop - returns the process exit code."""
        self.install_signal_handlers()
        self.start_heartbeat()

        backoff = BASE_BACKOFF_SECONDS
        LOG.info(
            "Agent %s started (device %s, poll interval %.0fs)",
            self.config.name,
            self.config.device_id,
            self.poll_interval,
        )

        try:
            while not self.stop_event.is_set():
                try:
                    outcome = self.run_once()
                    backoff = BASE_BACKOFF_SECONDS
                except Exception as error:  # pragma: no cover - defensive
                    LOG.exception("Unexpected error in the agent loop: %s", error)
                    outcome = None

                if outcome is None:
                    # Nothing to do (or the backend is unreachable) -> back off.
                    delay = min(backoff, MAX_BACKOFF_SECONDS)
                    backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                    if self.stop_event.wait(delay):
                        break
                    continue

                if self.stop_event.wait(self.poll_interval):
                    break
        finally:
            self.stop_heartbeat()
            self.send_offline_heartbeat()
            LOG.info("Agent stopped")
        return 0


def wait_for_stop(seconds: float, stop_event: threading.Event) -> bool:
    """Sleeps but reacts to the stop event. Returns True when stopped."""
    return stop_event.wait(seconds)


__all__ = ["AgentRunner", "wait_for_stop"]
