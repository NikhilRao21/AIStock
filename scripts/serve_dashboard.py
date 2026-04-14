from __future__ import annotations

import argparse
import http.server
import socketserver
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve AIStock dashboard HTML")
    parser.add_argument("--dir", default="data", help="Directory containing dashboard.html")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    dashboard_dir = Path(args.dir).resolve()
    dashboard_dir.mkdir(parents=True, exist_ok=True)

    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("0.0.0.0", args.port), handler) as httpd:
        print(f"Serving dashboard from {dashboard_dir} on http://0.0.0.0:{args.port}")
        print("Press Ctrl+C to stop")
        import os

        os.chdir(dashboard_dir)
        httpd.serve_forever()


if __name__ == "__main__":
    main()
