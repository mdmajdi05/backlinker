"""Command line interface of the local agent.

    python -m agent --register --server-url http://127.0.0.1:8000
    python -m agent --once
    python -m agent --daemon
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import __version__
from .browser import browser_runtime_status
from .client import BackendClient, BackendError
from .config import (
    AgentConfig,
    default_capabilities,
    delete_config,
    load_config,
    save_config,
)
from .executor import TaskExecutor
from .logging_setup import setup_logging
from .runner import AgentRunner
from .transport import TransportError, UrllibTransport

LOG = logging.getLogger("agent.cli")

DEFAULT_SERVER_URL = os.environ.get("AUTOBL_SERVER_URL", "http://127.0.0.1:8000")


def default_api_dir() -> Path | None:
    """Locate ``apps/api`` relative to this file (monorepo checkout)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "api"
        if (candidate / "app" / "services" / "adapters").is_dir():
            return candidate
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent",
        description="Auto Backlinker local automation agent",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="register this device at the backend and store the api key",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="claim and execute a single task, then exit",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="run continuously (the default)",
    )
    parser.add_argument(
        "--server-url",
        default=None,
        help=f"base url of the backend (default: {DEFAULT_SERVER_URL})",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="device name that is shown in the backend",
    )
    parser.add_argument(
        "--api-dir",
        default=None,
        help="path to the apps/api directory (adapter framework)",
    )
    parser.add_argument(
        "--capabilities",
        default="",
        help="comma separated list of capabilities (default: submit,verify,http)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not advertise the browser capability",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("AUTOBL_AGENT_LOG_LEVEL", "INFO"),
        help="log level (DEBUG, INFO, WARNING, ERROR)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete the stored device registration and exit",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="print the registration status and exit",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def _capabilities(raw: str, include_browser: bool) -> list[str]:
    if raw.strip():
        return [item.strip() for item in raw.split(",") if item.strip()]
    return default_capabilities(include_browser)


def _register(args: argparse.Namespace, logger: logging.Logger) -> AgentConfig:
    server_url = (args.server_url or DEFAULT_SERVER_URL).rstrip("/")
    transport = UrllibTransport(server_url)
    client = BackendClient(transport)
    capabilities = _capabilities(args.capabilities, not args.no_browser)

    try:
        registration = client.register(
            name=args.name or AgentConfig(device_id="", api_key="").name,
            platform=__import__("platform").system(),
            version=__version__,
            capabilities=capabilities,
        )
    except (TransportError, BackendError) as error:
        logger.error("Registration failed: %s", error)
        raise SystemExit(2)

    config = AgentConfig(
        device_id=registration.device_id,
        api_key=registration.api_key,
        server_url=server_url,
        name=args.name or registration.device_id,
        capabilities=capabilities,
        poll_interval_seconds=registration.poll_interval_seconds,
    )
    path = save_config(config)
    logger.info("Registered as device %s (configuration: %s)", config.device_id, path)
    print(f"Registered device {config.device_id}")
    print(f"Configuration written to {path}")
    return config


def _load_or_register(
    args: argparse.Namespace, logger: logging.Logger
) -> AgentConfig:
    config = load_config()
    if config is not None:
        return config
    if args.server_url:
        logger.info("No registration found - registering now")
        return _register(args, logger)
    logger.error(
        "The agent is not registered. Run `python -m agent --register "
        "--server-url <backend-url>` first."
    )
    raise SystemExit(2)


def _status(logger: logging.Logger) -> int:
    config = load_config()
    available, message = browser_runtime_status()
    if config is None:
        print("The agent is not registered.")
    else:
        print(
            json.dumps(
                {
                    "device_id": config.device_id,
                    "server_url": config.server_url,
                    "name": config.name,
                    "capabilities": config.capabilities,
                    "poll_interval_seconds": config.poll_interval_seconds,
                    "last_seen": config.last_seen,
                },
                indent=2,
            )
        )
    print(f"browser runtime: {'available' if available else message}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logger = setup_logging(args.log_level)

    if args.reset:
        delete_config()
        print("The local registration was removed.")
        return 0

    if args.status:
        return _status(logger)

    if args.register:
        _register(args, logger)
        return 0

    config = _load_or_register(args, logger)
    api_dir = Path(args.api_dir) if args.api_dir else default_api_dir()
    if api_dir is None:
        logger.warning(
            "The apps/api directory was not found - browser submissions will not "
            "be possible. Use --api-dir to point at a checkout of apps/api."
        )

    transport = UrllibTransport(config.server_url, token=config.api_key)
    client = BackendClient(
        transport, device_id=config.device_id, api_key=config.api_key
    )
    executor = TaskExecutor(api_dir=api_dir)
    runner = AgentRunner(config, client, executor=executor)

    if args.once:
        outcome = runner.run_once()
        if outcome is None:
            print("No task was available.")
            return 0
        print(f"Task finished with status {outcome.status}")
        if outcome.error:
            print(f"error: {outcome.error}")
        return 0 if outcome.status not in ("FAILED",) else 1

    return runner.run_forever()


if __name__ == "__main__":
    sys.exit(main())
