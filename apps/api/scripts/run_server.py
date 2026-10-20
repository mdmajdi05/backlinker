"""Start the Auto Backlinker API server.

This is the entry point used by the desktop sidecar and by the standalone
installations:

    python scripts/run_server.py --host 127.0.0.1 --port 8765

The host defaults to the loopback interface on purpose - the desktop build
must never expose an unauthenticated API to the network.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Auto Backlinker API server")
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind (default: loopback)")
    parser.add_argument("--port", type=int, default=8000, help="TCP port to bind")
    parser.add_argument("--reload", action="store_true", help="enable auto reload (development only)")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    import uvicorn

    from app.core.config import settings

    settings.ensure_directories()
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
