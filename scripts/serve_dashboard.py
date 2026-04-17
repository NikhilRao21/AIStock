from __future__ import annotations

import argparse
import http.server
import json
import socketserver
from pathlib import Path

from aistock.integrations.market.yfinance_provider import YFinanceProvider


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, dashboard_dir: Path, **kwargs):
        self._dashboard_dir = dashboard_dir
        super().__init__(*args, directory=str(dashboard_dir), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        """Override parent GET handling to serve API routes before static files."""
        if self.path.rstrip("/") == "/api/live-prices":
            self._serve_live_prices()
            return
        super().do_GET()

    def _serve_live_prices(self) -> None:
        latest_path = self._dashboard_dir / "latest_cycle.json"
        payload: dict = {}
        if latest_path.exists():
            try:
                payload = json.loads(latest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError, TypeError):
                payload = {}

        symbols = [str(p.get("symbol", "")).upper() for p in payload.get("positions", []) if p.get("symbol")]
        prices: dict[str, float] = {}
        market = YFinanceProvider()
        for symbol in symbols:
            try:
                prices[symbol] = round(float(market.latest_price(symbol)), 4)
            except Exception:
                continue

        response = {
            "prices": prices,
            "cash": float(payload.get("cash", 0.0) or 0.0),
            "timestamp": payload.get("timestamp"),
        }
        body = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve AIStock dashboard HTML")
    parser.add_argument("--dir", default="data", help="Directory containing dashboard.html")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    dashboard_dir = Path(args.dir).resolve()
    dashboard_dir.mkdir(parents=True, exist_ok=True)

    with socketserver.TCPServer(
        ("0.0.0.0", args.port),
        lambda *handler_args, **handler_kwargs: DashboardHandler(
            *handler_args,
            dashboard_dir=dashboard_dir,
            **handler_kwargs,
        ),
    ) as httpd:
        print(f"Serving dashboard from {dashboard_dir} on http://0.0.0.0:{args.port}")
        print("Press Ctrl+C to stop")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
