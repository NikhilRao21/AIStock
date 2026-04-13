from __future__ import annotations

from aistock.runtime.pipeline import run_one_cycle


def main() -> None:
    result = run_one_cycle()
    portfolio = result["portfolio"]
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


if __name__ == "__main__":
    main()
