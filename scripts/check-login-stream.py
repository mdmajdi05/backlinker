"""End to end check of the remote login stream (run manually)."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
PYTHON = ROOT / ".venv" / "bin" / "python"
PORT = 8123
BASE = f"http://127.0.0.1:{PORT}"


def wait_for_health(client: httpx.Client) -> None:
    for _ in range(120):
        try:
            if client.get(f"{BASE}/health").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise SystemExit("backend did not start")


def main() -> None:
    data_dir = tempfile.mkdtemp(prefix="abk-stream-e2e-")
    env = {
        **os.environ,
        "AUTOBL_DATA_DIR": data_dir,
        "AUTOBL_ENVIRONMENT": "desktop",
        "AUTOBL_WORKER_ENABLED": "false",
        "AUTOBL_SECRET_KEY": "e2e-secret-key-000000000000000000000000",
    }
    process = subprocess.Popen(  # noqa: S603
        [str(PYTHON), "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"],
        cwd=API_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        with httpx.Client(timeout=30) as client:
            wait_for_health(client)
            registered = client.post(
                f"{BASE}/api/v1/auth/register",
                json={"email": "stream@example.com", "password": "stream-password-123", "name": "Stream"},
            )
            registered.raise_for_status()
            token = registered.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            project = client.post(
                f"{BASE}/api/v1/projects",
                json={"name": "Stream check", "target_website": "https://stream.example"},
                headers=headers,
            )
            project.raise_for_status()
            project_id = project.json()["id"]

            opened = client.post(
                f"{BASE}/api/v1/projects/{project_id}/login/google",
                json={"view": "remote"},
                headers=headers,
            )
            opened.raise_for_status()
            print("open:", opened.json())

            ticket: dict = {}
            for _ in range(60):
                response = client.post(
                    f"{BASE}/api/v1/projects/{project_id}/login/stream-ticket",
                    headers=headers,
                )
                if response.status_code == 200:
                    ticket = response.json()
                    break
                time.sleep(0.5)
            if not ticket:
                raise SystemExit(f"no ticket: {response.status_code} {response.text}")
            print("ticket:", {k: v for k, v in ticket.items() if k != "ticket"})

            async def consume() -> None:
                import websockets

                url = f"ws://127.0.0.1:{PORT}{ticket['ws_path']}?ticket={ticket['ticket']}"
                async with websockets.connect(url, max_size=8 * 1024 * 1024) as socket:
                    ready = json.loads(await socket.recv())
                    print("ready:", ready)
                    frames = 0
                    total = 0
                    deadline = time.time() + 25
                    while frames < 3 and time.time() < deadline:
                        message = await asyncio.wait_for(socket.recv(), timeout=20)
                        if isinstance(message, bytes):
                            frames += 1
                            total += len(message)
                            if frames == 1:
                                Path("/tmp/abk-login-frame.jpg").write_bytes(message)
                        else:
                            payload = json.loads(message)
                            if payload.get("type") == "error":
                                raise SystemExit(f"stream error: {payload}")
                            if payload.get("type") == "closed":
                                raise SystemExit("stream closed early")
                    print(f"frames: {frames}, bytes: {total}")
                    if frames == 0:
                        raise SystemExit("no frame received")

            asyncio.run(consume())
            first = Path("/tmp/abk-login-frame.jpg")
            print("jpeg:", first.stat().st_size, base64.b64encode(first.read_bytes()[:3]).decode())

            closed = client.post(
                f"{BASE}/api/v1/projects/{project_id}/login/cancel", headers=headers
            )
            print("cancel:", closed.json())
    finally:
        process.terminate()
        try:
            output, _ = process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()
        if process.returncode not in (0, -15):
            print(output[-4000:])
            sys.exit(1)


if __name__ == "__main__":
    main()
