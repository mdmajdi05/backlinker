"""Auto Backlinker local automation agent.

The agent registers itself at a backend, claims tasks that must run on this
machine and executes them with the adapter framework of the backend
(``apps/api/app/services/adapters``).

Security rules that are enforced by this package:

* only a fixed allowlist of task types is executed,
* a task whose payload contains an executable/command field is rejected,
* the agent never evaluates code that it received from the server.
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["__version__"]
