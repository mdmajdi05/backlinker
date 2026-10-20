"""Offline tests of the local agent.

The tests never touch the network - every HTTP call is served by a mock
transport that records the exact request.

    cd apps/local-agent
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import config as agent_config  # noqa: E402
from agent.allowlist import TaskRejected, validate_task  # noqa: E402
from agent.client import BackendClient  # noqa: E402
from agent.executor import TaskExecutor  # noqa: E402
from agent.logging_setup import redact  # noqa: E402
from agent.transport import MockTransport, Response  # noqa: E402


class AgentConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._previous = os.environ.get("AUTOBL_AGENT_HOME")
        os.environ["AUTOBL_AGENT_HOME"] = self._tmp.name

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop("AUTOBL_AGENT_HOME", None)
        else:
            os.environ["AUTOBL_AGENT_HOME"] = self._previous
        self._tmp.cleanup()

    def test_config_is_stored_with_0600_permissions(self) -> None:
        config = agent_config.AgentConfig(
            device_id="device-1",
            api_key="abk_supersecretvalue",
            server_url="http://127.0.0.1:8000",
        )
        path = agent_config.save_config(config)

        self.assertTrue(path.is_file())
        mode = stat.S_IMODE(path.stat().st_mode)
        self.assertEqual(mode, 0o600, f"expected 0600, got {oct(mode)}")

        stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(stored["device_id"], "device-1")
        self.assertEqual(stored["api_key"], "abk_supersecretvalue")

        loaded = agent_config.load_config()
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.device_id, "device-1")
        self.assertNotIn("api_key", loaded.public_dict())

    def test_missing_config_returns_none(self) -> None:
        self.assertIsNone(agent_config.load_config())


class BackendClientTests(unittest.TestCase):
    def test_register_posts_the_documented_payload(self) -> None:
        transport = MockTransport(
            [
                Response(
                    200,
                    json.dumps(
                        {
                            "device_id": "dev-42",
                            "api_key": "abk_key",
                            "poll_interval_seconds": 20,
                        }
                    ).encode(),
                )
            ]
        )
        client = BackendClient(transport)

        registration = client.register(
            name="studio-mac",
            platform="Darwin",
            version="1.0.0",
            capabilities=["submit", "verify"],
        )

        self.assertEqual(registration.device_id, "dev-42")
        self.assertEqual(registration.api_key, "abk_key")
        self.assertEqual(registration.poll_interval_seconds, 20)

        call = transport.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["path"], "/api/v1/devices/register")
        self.assertEqual(
            call["body"],
            {
                "name": "studio-mac",
                "platform": "Darwin",
                "version": "1.0.0",
                "capabilities": ["submit", "verify"],
            },
        )
        # The registration call must not carry a stale token.
        self.assertNotIn("Authorization", call["headers"])

    def test_heartbeat_uses_the_bearer_token(self) -> None:
        transport = MockTransport([Response(200, b"{}")])
        client = BackendClient(transport, device_id="dev-42", api_key="abk_key")

        self.assertTrue(client.heartbeat(status="ONLINE", capabilities=["verify"]))

        call = transport.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["path"], "/api/v1/devices/dev-42/heartbeat")
        self.assertEqual(call["body"], {"status": "ONLINE", "capabilities": ["verify"]})
        self.assertEqual(call["headers"]["Authorization"], "Bearer abk_key")

    def test_claim_returns_none_when_the_queue_is_idle(self) -> None:
        transport = MockTransport([Response(204, b"")])
        client = BackendClient(transport, device_id="dev-42", api_key="abk_key")

        self.assertIsNone(client.claim_task())
        self.assertEqual(transport.calls[0]["path"], "/api/v1/devices/tasks/claim")
        self.assertEqual(transport.calls[0]["method"], "GET")

    def test_claim_returns_the_task(self) -> None:
        task = {"id": "task-1", "type": "VERIFY", "payload": {}}
        transport = MockTransport([Response(200, json.dumps(task).encode())])
        client = BackendClient(transport, device_id="dev-42", api_key="abk_key")

        self.assertEqual(client.claim_task(), task)

    def test_report_sends_status_result_and_error(self) -> None:
        transport = MockTransport([Response(200, b"{}")])
        client = BackendClient(transport, device_id="dev-42", api_key="abk_key")

        client.report_task(
            "task-1",
            status="FAILED",
            result={"requires_human": True},
            error="browser runtime not installed",
        )

        call = transport.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["path"], "/api/v1/devices/tasks/task-1/report")
        self.assertEqual(call["body"]["status"], "FAILED")
        self.assertEqual(call["body"]["error"], "browser runtime not installed")
        self.assertEqual(call["body"]["result"], {"requires_human": True})


class AllowlistTests(unittest.TestCase):
    def test_allowed_task_types_pass(self) -> None:
        self.assertEqual(validate_task({"id": "1", "type": "SUBMIT", "payload": {}}), "SUBMIT")
        self.assertEqual(validate_task({"id": "1", "type": "VERIFY", "payload": {}}), "VERIFY")

    def test_unknown_task_type_is_rejected(self) -> None:
        with self.assertRaises(TaskRejected):
            validate_task({"id": "1", "type": "IMPORT", "payload": {}})

    def test_payload_with_command_field_is_rejected(self) -> None:
        task = {
            "id": "1",
            "type": "SUBMIT",
            "payload": {"url": "https://example.com", "command": "rm -rf /"},
        }
        with self.assertRaises(TaskRejected):
            validate_task(task)

    def test_nested_command_field_is_rejected(self) -> None:
        task = {
            "id": "1",
            "type": "VERIFY",
            "payload": {"context": {"options": {"script": "rm -rf /"}}},
        }
        with self.assertRaises(TaskRejected):
            validate_task(task)


class ExecutorTests(unittest.TestCase):
    def test_rejected_task_is_never_executed(self) -> None:
        executor = TaskExecutor(api_dir=None)
        outcome = executor.execute(
            {
                "id": "task-1",
                "type": "SUBMIT",
                "payload": {"command": "curl evil.example"},
            }
        )
        self.assertEqual(outcome.status, "FAILED")
        self.assertTrue(outcome.requires_human)
        self.assertIn("rejected", outcome.result)
        self.assertIn("command", (outcome.error or "").lower())

    def test_missing_adapter_framework_reports_a_clear_error(self) -> None:
        # An api dir without the backend package must not silently succeed.
        with tempfile.TemporaryDirectory() as tmp:
            executor = TaskExecutor(api_dir=Path(tmp))
            outcome = executor.execute(
                {"id": "task-2", "type": "VERIFY", "payload": {"url": "https://example.com"}}
            )
        self.assertEqual(outcome.status, "WAITING_FOR_USER")
        self.assertTrue(outcome.requires_human)
        self.assertIn("adapter framework", (outcome.error or "").lower())


class RedactionTests(unittest.TestCase):
    def test_secrets_are_removed_from_log_messages(self) -> None:
        message = (
            'Authorization: Bearer abk_abcdefghijklmnop '
            '{"api_key": "abk_abcdefghijklmnop"} '
            'password=hunter2'
        )
        redacted = redact(message)
        self.assertNotIn("abk_abcdefghijklmnop", redacted)
        self.assertNotIn("hunter2", redacted)
        self.assertIn("***", redacted)


if __name__ == "__main__":
    unittest.main()
