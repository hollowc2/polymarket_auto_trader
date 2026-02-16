# AGENTS.md — Polymarket Streak Bot

## Project
Python bot for trading BTC 5-min up/down prediction markets on Polymarket. Three strategies: streak reversal (mean reversion), copytrade (wallet copying), and selective copytrade (filtered).

## Stack
- Python 3.13, uv (package manager)
- Nix flake devshell (`nix develop`)
- py-clob-client, web3, websockets, requests
- Ruff (linter), ty (type checker), prek (pre-commit hooks)

## Structure
```
bot.py / copybot_v2.py          # Entrypoints (streak / copytrade)
src/config.py                   # Settings from .env
src/strategies/                 # Strategy logic (streak, copytrade, filters)
src/core/                       # API clients (REST, WebSocket, blockchain, trader)
src/infra/                      # Cross-cutting (resilience, logging)
scripts/                        # Backtest, history analysis
docs/                           # Detailed docs (architecture, decisions, conventions)
```

## Development
```bash
nix develop                              # Enter devshell
uv sync                                  # Install deps
uv run python bot.py --paper             # Streak strategy (paper)
uv run python copybot_v2.py --paper      # Copytrade (paper)
uv run python scripts/backtest.py        # Backtest
```

## Docs
- `docs/ARCHITECTURE.md` — system design, data flow, API surface
- `docs/CONVENTIONS.md` — code patterns, naming, module boundaries
- `docs/DECISIONS.md` — architecture decision records

## Verification
```bash
ruff check .                    # Lint
ruff format --check .           # Format check
ty check                        # Type check
```

## Rules
- Paper trade first (`--paper`). Never default to live.
- All config via `.env` — no hardcoded keys or amounts.
- Entrypoints (`bot.py`, `copybot_v2.py`) stay thin — logic lives in `src/`.
- REST fallback for every WebSocket path (graceful degradation).
