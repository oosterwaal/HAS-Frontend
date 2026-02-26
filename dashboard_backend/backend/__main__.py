"""
Entry point for the Home Assistant Dashboard backend.

Usage:
    python -m backend
    python -m backend --host 0.0.0.0 --port 8080
"""
import argparse
import sys

import uvicorn

from .settings import settings


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Home Assistant Dashboard Backend"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=settings.HOST,
        help=f"Host to bind to (default: {settings.HOST})"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=settings.PORT,
        help=f"Port to bind to (default: {settings.PORT})"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Log level (default: info)"
    )
    
    args = parser.parse_args()
    
    # Validate settings before starting
    valid, error = settings.validate()
    if not valid:
        print(f"⚠️  Warning: {error}")
        print("   The server will start but won't connect to Home Assistant.")
        print("   Create a .env file with HA_URL and HA_TOKEN to enable connection.")
        print()
    
    print(f"🏠 Starting Home Assistant Dashboard")
    print(f"   URL: http://{args.host}:{args.port}")
    print(f"   API Docs: http://{args.host}:{args.port}/docs")
    print()
    
    uvicorn.run(
        "backend.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level
    )


if __name__ == "__main__":
    main()
