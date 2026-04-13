# AIStock

AI-driven US equities paper trader with synthetic-money execution.

This repository now includes a runnable MVP foundation that:

- reads news via provider adapters (Hack Club Search or mock)
- scores symbols with AI (Hack Club AI or mock)
- computes conventional momentum signals from market data (yfinance)
- fuses AI + conventional signals into trade decisions
- executes paper trades in a synthetic broker and tracks equity

## Current MVP Scope

- Asset class: US equities only
- Execution: synthetic money only
- Risk baseline: 3% max allocation per trade, 8% stop-loss configured
- Fidelity: deferred for now; architecture is adapter-ready for future broker integration

## Project Layout

```
src/aistock/
	core/                 # config + shared domain models
	integrations/
		ai/                 # AI provider adapters
		news/               # news/search adapters
		market/             # market data adapters
	signals/              # conventional indicators + ensemble fusion
	risk/                 # position sizing/risk policies
	broker/               # broker interface + paper broker
	runtime/              # cycle orchestration
scripts/
	run_cycle.py          # execute one trading cycle
```

## Quick Start

1. Create virtual environment and install dependencies.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Configure environment.

```bash
cp .env.example .env
```

3. Ensure local import path is available.

```bash
export PYTHONPATH=src
```

4. Run one paper trading cycle.

```bash
python scripts/run_cycle.py
```

## Provider Modes

Use these in `.env`:

- `AI_PROVIDER=mock` and `NEWS_PROVIDER=mock` for deterministic local testing
- `AI_PROVIDER=hackclub` and `NEWS_PROVIDER=hackclub` to use Hack Club endpoints

Set API keys when required:

- `AI_HACKCLUB_API_KEY` for Hack Club AI
- `SEARCH_HACKCLUB_API_KEY` for Hack Club Search

## Auto Deploy On Server

This repo now includes a GitHub Actions workflow at `.github/workflows/deploy.yml`.
On every push to `main`, GitHub will SSH into your server and run:

1. pull latest code
2. install dependencies in venv
3. restart systemd service `aistock-paper.service`

### Server prerequisites

1. Clone repo to `/opt/AIStock` on the server.
2. Create and activate virtual environment once.
3. Create a systemd service named `aistock-paper.service`.
4. Ensure the deploy SSH user can run `sudo systemctl restart aistock-paper.service`.

### GitHub repo secrets to add

1. `SERVER_HOST`
2. `SERVER_USER`
3. `SERVER_SSH_KEY`
4. `SERVER_PORT` (optional, defaults to 22)

After this is configured, updating `main` in GitHub will automatically update the server.

## Notes

- The Hack Club API response parser is defensive because payload structure can vary.
- yfinance is used for low-cost daily close and latest price retrieval.
- This is the first implementation slice; backtesting module, scheduler loop, richer risk rules, and KPI dashboard are next.