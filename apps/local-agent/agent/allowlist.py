"""Allowlist for the tasks the agent is allowed to execute.

The agent runs code that a remote server asks it to run - therefore the
contract has to be narrow:

* only the task types listed in :data:`ALLOWED_TASK_TYPES` are executed,
* a task whose payload contains an executable/command field is rejected,
* everything else is reported as "manual intervention required".
"""

from __future__ import annotations

from typing import Any, Iterable

#: The only task types this agent executes.
ALLOWED_TASK_TYPES = frozenset({"SUBMIT", "VERIFY"})

#: Task types the backend knows but this agent never executes.
KNOWN_TASK_TYPES = frozenset(
    {"DISCOVER", "SUBMIT", "VERIFY", "IMPORT", "EXPORT", "MANUAL"}
)

#: Payload keys that would turn the task into arbitrary code execution.
FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "argv",
        "bash",
        "cmd",
        "code",
        "command",
        "commands",
        "entrypoint",
        "eval",
        "exec",
        "executable",
        "javascript",
        "powershell",
        "python",
        "script",
        "shell",
        "spawn",
        "subprocess",
    }
)

#: Keys that are allowed to carry a nested payload with the same rules.
_NESTED_KEYS = ("payload", "context", "data", "options", "config")


class TaskRejected(Exception):
    """The task must not be executed."""


def _iter_keys(value: Any, depth: int = 0) -> Iterable[str]:
    if depth > 6:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            if str(key).lower() in _NESTED_KEYS:
                yield from _iter_keys(item, depth + 1)
            elif isinstance(item, (dict, list)):
                yield from _iter_keys(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_keys(item, depth + 1)


def find_forbidden_keys(payload: Any) -> list[str]:
    """Returns every forbidden key that is present in the payload."""
    found: list[str] = []
    for key in _iter_keys(payload):
        lowered = key.lower()
        if lowered in FORBIDDEN_PAYLOAD_KEYS and lowered not in found:
            found.append(lowered)
    return found


def task_type_of(task: dict[str, Any]) -> str:
    return str(task.get("type") or task.get("task_type") or "").upper()


def validate_task(task: dict[str, Any]) -> str:
    """Validates a claimed task and returns its type.

    Raises :class:`TaskRejected` when the task must not be executed.
    """
    if not isinstance(task, dict):
        raise TaskRejected("The claimed task is not an object")

    task_type = task_type_of(task)
    if not task_type:
        raise TaskRejected("The claimed task has no type")
    if task_type not in ALLOWED_TASK_TYPES:
        raise TaskRejected(
            f"Task type {task_type} is not allowed on this agent "
            f"(allowed: {', '.join(sorted(ALLOWED_TASK_TYPES))})"
        )

    payload = task.get("payload") or {}
    if not isinstance(payload, dict):
        raise TaskRejected("The task payload is not an object")

    forbidden = find_forbidden_keys(payload)
    if forbidden:
        raise TaskRejected(
            "The task payload contains executable fields and was rejected: "
            + ", ".join(sorted(forbidden))
        )

    return task_type


__all__ = [
    "ALLOWED_TASK_TYPES",
    "FORBIDDEN_PAYLOAD_KEYS",
    "KNOWN_TASK_TYPES",
    "TaskRejected",
    "find_forbidden_keys",
    "task_type_of",
    "validate_task",
]
