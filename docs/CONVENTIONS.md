# Conventions

## Code Style
- Ruff for linting and formatting (default config)
- Type hints on all function signatures
- ty for type checking

## Module Boundaries
- **Entrypoints** (`bot.py`, `copybot_v2.py`): CLI parsing + orchestration only. No business logic.
- **Strategies**: Pure signal generation. No direct API calls — receive data, return decisions.
- **Core**: API clients and execution. No strategy logic.
- **Infra**: Generic utilities. No domain knowledge.

## Naming
- Market-related: `condition_id`, `token_id`, `slug`
- Strategy signals: use explicit types/dataclasses, not raw dicts
- Config: ALL_CAPS env vars → snake_case Python attributes in `config.py`

## Error Handling
- Graceful degradation: if a market fetch fails, skip and continue
- WebSocket always has REST fallback
- Circuit breaker wraps external API calls
- Never crash on a single failed trade

## Git
- Conventional commits preferred
- Pre-commit hooks via prek (runs ruff)
