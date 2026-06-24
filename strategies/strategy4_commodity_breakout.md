# Strategy 4 — Commodity Breakout

**Status:** LIVE (metals dormancy only) · `commodity_breakout_bot`

## Thesis

Futures breakouts on a small commodity universe. The honest lane for a retail systematic trader in
commodities is **quant pattern**, not information (physical merchants and macro desks own the
information edge) — so this trades coiled-spring volatility breakouts and seasonal momentum, nothing
fundamental.

## What is actually LIVE: Metals "dormancy" (coiled spring)

Per `config.toml` `[category_strategy]`, only the **metals dormancy** path is live (GC/SI/PL):

- **Daily 09:35 ET scan** (restart-idempotent — runs once/day, catches up if the bot was down,
  never re-fires off-schedule).
- **Setup:** a metal whose volatility has compressed into the **bottom 20th percentile** of its own
  252-day history (coiled), persisting ~20 days → then **breaks the 20-day Donchian high**.
- **News confirmation:** Claude classifies recent headlines as fundamental vs noise; only
  fundamental-backed breakouts proceed.
- **Exit:** native IBKR stop below the dormant range + trailing stop that ratchets up. Roll
  detection near expiry. Risk ≤ 1% of reserved capital and ≤ notional/10 (10:1 leverage cap).
- Rare by design — fires only when a metal is genuinely coiled.

## What is configured but NOT live (TBD)

- **Energy & grains seasonal** (`seasonal` category) = calendar-gated momentum, "skipped for now."
- **Grains (ZC/ZW/ZS) shelved (2026-06-22):** seasonal backtest fired **zero** trades — long-only
  momentum can't fire when grains aren't trending up (2024–2026 were range-bound/bearish). The
  apparent backtest "+580%" was energy outliers entered ~16× on overlapping days (the backtest lacks
  no-overlap / max_active_trades modeling — numbers untrustworthy until added). **Intraday grains
  rejected** (can't backtest on IBKR's ~4yr daily cap / weeks of intraday; latency game; limit-lock +
  USDA-report millisecond trap). Revisit only with a deeper futures data source + no-overlap modeling.

## Why it's quiet by design

Most days nothing fires — the only live path needs a metal in a rare coiled-then-breakout state.
Silence is the strategy being selective, not broken.
