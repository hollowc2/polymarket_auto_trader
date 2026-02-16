# Architecture Decision Records

## ADR-001: Trigger Length = 4
**Context:** Need to pick how many consecutive same outcomes before betting reversal.
**Decision:** Trigger=4. Balances trade frequency (~51 signals in sample) with win rate (~67%).
**Alternatives:** Trigger=5 has higher win rate (82%) but very few signals (17 in sample).

## ADR-002: Quarter-Kelly Sizing
**Context:** Kelly criterion suggests optimal bet size but is aggressive.
**Decision:** Use quarter-Kelly for conservative bankroll management. Reduces variance at cost of slower growth.

## ADR-003: FOK Orders for Copytrade
**Context:** Copytrade needs guaranteed fills — partial fills create position management complexity.
**Decision:** Fill-or-Kill (FOK) orders. Either fully filled or not at all.

## ADR-004: Hybrid WS + REST for Copytrade Detection
**Context:** Pure WebSocket for trade detection was unreliable. Pure REST has 5s+ latency.
**Decision:** Hybrid approach — WebSocket for orderbook data, fast REST polling (1.5s) for wallet activity. Achieves ~1.5-2s total detection latency.

## ADR-005: src/ Package Structure
**Context:** Flat file layout became unwieldy as strategies and infra grew.
**Decision:** Moved to `src/` with `strategies/`, `core/`, `infra/` sub-packages. Entrypoints remain at root for easy `uv run python bot.py`.

## ADR-006: Nix Flake Devshell
**Context:** Need reproducible dev environment with Python 3.13, uv, ruff, ty, prek.
**Decision:** Nix flake with devShell. Auto-creates venv and installs prek hooks on `nix develop`.
