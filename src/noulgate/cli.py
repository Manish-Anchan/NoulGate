"""
NoulGate CLI
============
Launches the NoulGate proxy server.

Usage::

    noulgate                         # default: host=0.0.0.0 port=8080
    noulgate --port 3000
    noulgate --host 127.0.0.1 --port 9000 --reload
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="noulgate",
        description="NoulGate — High-speed System 1 MCP tool gateway.",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("HOST", "0.0.0.0"),
        help="Host to bind to (default: 0.0.0.0 or $HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", "8080")),
        help="Port to listen on (default: 8080 or $PORT)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload on code changes (development only)",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Uvicorn log level (default: info)",
    )
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn is not installed. Run: uv sync", file=sys.stderr)
        sys.exit(1)

    print(f"🚀 NoulGate starting on http://{args.host}:{args.port}")
    print(f"   Docs:   http://{args.host}:{args.port}/docs")
    print(f"   Health: http://{args.host}:{args.port}/health")
    print()

    uvicorn.run(
        "noulgate.proxy:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
