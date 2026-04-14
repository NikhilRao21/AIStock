from __future__ import annotations

import argparse

from aistock.runtime.pipeline import run_one_cycle


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one AIStock cycle")
    parser.add_argument(
        "--fresh-start",
        action="store_true",
        help="Reset local portfolio/history artifacts before running the cycle",
    )
    args = parser.parse_args()

    if args.fresh_start:
        from pathlib import Path

        data_dir = Path("data")
        for p in ("broker_state.json", "latest_cycle.json", "cycle_reports.jsonl", "dashboard.html"):
            target = data_dir / p
            if target.exists():
                target.unlink()

    result = run_one_cycle()
    portfolio = result["portfolio"]
    report = result.get("cycle_report", {})

    print(f"Scanned symbols: {len(result.get('symbols', []))}")
    if result.get("symbols"):
        print("Universe sample:", ", ".join(result["symbols"][:10]))

    print("Decisions:")
    for d in result["decisions"]:
        print(f"- {d.symbol}: {d.action} qty={d.quantity} conf={d.confidence:.2f} reason={d.reason}")

    print("\nFills:")
    if not result["fills"]:
        print("- none")
    else:
        for f in result["fills"]:
            print(f"- {f.timestamp.isoformat()} {f.action} {f.symbol} qty={f.quantity} px={f.fill_price:.2f} fee={f.fee:.2f}")

    print("\nPortfolio:")
    print(f"- cash={portfolio.cash:.2f}")
    print(f"- equity={portfolio.equity:.2f}")
    print(f"- positions={[(p.symbol, p.quantity, round(p.avg_cost, 2)) for p in portfolio.positions]}")
    print(f"- equity_delta={report.get('equity_delta')}")

    print("\nDebug:")
    issues = report.get("debug_issues", [])
    if issues:
        for issue in issues:
            print(f"- issue: {issue}")
    else:
        print("- issue: none")
    print(f"- ai_output_count={report.get('ai_output_count', 0)}")
    print(f"- ai_raw_output_count={report.get('ai_raw_output_count', 0)}")
    print(f"- news_raw_output_count={report.get('news_raw_output_count', 0)}")
    news_raw_output = report.get("news_status", {}).get("raw_output", [])
    if news_raw_output:
        print("- news_raw_output_sample:")
        for item in news_raw_output[:3]:
            print(
                f"  - {item.get('symbol', '')}: status={item.get('status', '')} "
                f"http={item.get('http_status', '')} error={item.get('error', '')}"
            )

    print("\nDashboard files:")
    print("- data/latest_cycle.json")
    print("- data/cycle_reports.jsonl")
    print("- data/dashboard.html")


if __name__ == "__main__":
    main()
