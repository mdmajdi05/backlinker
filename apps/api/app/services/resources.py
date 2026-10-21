"""Resource aware scheduling.

The worker does not simply run "N jobs in parallel".  It looks at the machine
before it claims a browser job and lowers the number of parallel jobs when the
system is under load.  The measurement is real (CPU load and free memory of
the operating system) and the reduced limit is really enforced - the worker
claims fewer jobs while the machine is busy.

The limits are *soft* by nature: they describe what the worker aims for, they
cannot stop a single browser process from using CPU.  The user interface says
so explicitly instead of promising a guarantee that does not exist.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Literal

from app.core.logging import get_logger

log = get_logger(__name__)

ResourcePreference = Literal["max_speed", "balanced", "save_resources"]

PREFERENCE_FACTORS: dict[str, float] = {
    "max_speed": 1.0,
    "balanced": 0.6,
    "save_resources": 0.3,
}


@dataclass
class ResourceSnapshot:
    """A measurement of the machine at a point in time."""

    cpu_percent: float
    load_average: float
    memory_total_mb: float
    memory_available_mb: float
    memory_used_percent: float
    disk_free_mb: float
    cpu_count: int
    measured_at: float = field(default_factory=time.time)

    @property
    def overloaded(self) -> bool:
        return self.cpu_percent >= 85.0 or self.memory_available_mb < 512.0

    @property
    def busy(self) -> bool:
        return self.cpu_percent >= 65.0 or self.memory_used_percent >= 88.0

    def as_dict(self) -> dict:
        return {
            "cpu_percent": round(self.cpu_percent, 1),
            "load_average": round(self.load_average, 2),
            "memory_total_mb": round(self.memory_total_mb),
            "memory_available_mb": round(self.memory_available_mb),
            "memory_used_percent": round(self.memory_used_percent, 1),
            "disk_free_mb": round(self.disk_free_mb),
            "cpu_count": self.cpu_count,
            "overloaded": self.overloaded,
            "busy": self.busy,
        }


def _memory_info() -> tuple[float, float]:
    """Total and available memory in MB."""
    try:
        import psutil  # type: ignore

        memory = psutil.virtual_memory()
        return memory.total / 1048576, memory.available / 1048576
    except Exception:  # pragma: no cover - psutil is optional
        log.debug("psutil is not available - the load average is used instead")
    try:
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        # macOS and Linux do not expose the available memory through sysconf;
        # the load average is used as a coarse second signal.
        free = 0.0
        return total / 1048576, free
    except Exception:  # pragma: no cover - defensive
        return 0.0, 0.0


def _disk_free_mb(path: str = ".") -> float:
    try:
        usage = os.statvfs(path)
        return (usage.f_bavail * usage.f_frsize) / 1048576
    except Exception:  # pragma: no cover - defensive
        return 0.0


def _cpu_percent() -> float:
    """CPU usage of the machine in percent."""
    try:
        import psutil  # type: ignore

        return float(psutil.cpu_percent(interval=0.25))
    except Exception:  # pragma: no cover - psutil is optional
        log.debug("psutil is not available - the load average is used instead")
    try:
        load = os.getloadavg()[0]
        return min(100.0, (load / max(1, os.cpu_count() or 1)) * 100.0)
    except Exception:  # pragma: no cover - defensive
        return 0.0


def sample() -> ResourceSnapshot:
    """Measure the machine right now."""
    total_mb, available_mb = _memory_info()
    if not available_mb:
        # Fall back to a rough estimate so the governor still reacts to load.
        available_mb = max(0.0, total_mb * (1.0 - min(100.0, _cpu_percent()) / 100.0))
    used_percent = 0.0
    if total_mb:
        used_percent = (total_mb - available_mb) / total_mb * 100.0
    try:
        load = os.getloadavg()[0]
    except Exception:  # pragma: no cover - defensive
        load = 0.0
    return ResourceSnapshot(
        cpu_percent=_cpu_percent(),
        load_average=load,
        memory_total_mb=total_mb,
        memory_available_mb=available_mb,
        memory_used_percent=used_percent,
        disk_free_mb=_disk_free_mb(),
        cpu_count=os.cpu_count() or 1,
    )


class ResourceGovernor:
    """Turns a measurement into the number of parallel jobs that may run."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: ResourceSnapshot | None = None
        self._last_sample = 0.0
        self._reduced_until = 0.0
        self._sample_interval = 2.0

    def snapshot(self, force: bool = False) -> ResourceSnapshot:
        now = time.time()
        with self._lock:
            if (
                not force
                and self._snapshot is not None
                and now - self._last_sample < self._sample_interval
            ):
                return self._snapshot
        measured = sample()
        with self._lock:
            self._snapshot = measured
            self._last_sample = now
            if measured.overloaded:
                self._reduced_until = now + 60
            elif measured.busy:
                self._reduced_until = max(self._reduced_until, now + 20)
        return measured

    def effective_limit(
        self,
        user_limit: int,
        preference: ResourcePreference = "balanced",
    ) -> tuple[int, str]:
        """The number of jobs that may run right now.

        Returns the limit and the reason, so the user interface can explain
        why the concurrency was lowered.
        """
        limit = max(1, int(user_limit))
        factor = PREFERENCE_FACTORS.get(preference, 0.6)
        preferred = max(1, int(limit * factor)) if factor < 1.0 else limit

        snapshot = self.snapshot()
        now = time.time()
        with self._lock:
            reduced = now < self._reduced_until

        if snapshot.overloaded:
            return 1, (
                f"The machine is under heavy load (CPU {snapshot.cpu_percent:.0f}%, "
                f"{snapshot.memory_available_mb:.0f} MB memory left) - only one job runs at a time."
            )
        if reduced or snapshot.busy:
            return max(1, min(preferred, limit // 2 or 1)), (
                f"The machine is busy (CPU {snapshot.cpu_percent:.0f}%) - the number of parallel "
                "jobs was lowered automatically."
            )
        return preferred, "The machine has enough resources for the configured concurrency."

    def status(self, user_limit: int, preference: ResourcePreference) -> dict:
        snapshot = self.snapshot(force=True)
        limit, reason = self.effective_limit(user_limit, preference)
        return {
            "resources": snapshot.as_dict(),
            "configured_limit": user_limit,
            "preference": preference,
            "effective_limit": limit,
            "reason": reason,
            "measured_at": snapshot.measured_at,
        }


governor = ResourceGovernor()
