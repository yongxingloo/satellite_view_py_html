"""CLI launcher for the satellite_view package."""

from __future__ import annotations

import argparse
import threading
import webbrowser

from .webapp import create_app


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(description="Run the satellite view Flask application.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind (default: 5000).")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open a browser tab.")
    return parser


def main() -> None:
    """Start the web application server."""
    args = build_parser().parse_args()
    app = create_app()
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{args.host}:{args.port}")).start()
    app.run(host=args.host, port=args.port, debug=False)
