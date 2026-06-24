# Trading Strategies

Canonical, version-controlled docs for every strategy across the bots — live, planned, and
rejected. (The day-to-day working notes live in Claude memory; these are the durable source of truth.)

## Live (implemented)

| # | Strategy | Bot | One-line |
|---|---|---|---|
| 1 | [SOXL Core](strategy1_soxl_core.md) | `soxl_index_bot` | Hold 3× SOXL while SOXX > 200d MA; exit on first day below. Crash avoidance. +999%/5yr. |
| 2 | [SOXL Satellite](strategy2_soxl_satellite.md) | `soxl_index_bot` | Intraday: QQQ>VWAP + SOXX outperforms QQQ ≥0.75% + SOXX>5d MA → ride. +257%/5yr. |
| 3 | [SOXL PM-Gap](strategy3_soxl_pmgap.md) | `soxl_index_bot` | Buy SOXL at open on ≥5% pre-market gap + bullish regime. +243%/5yr (5% is optimal). |
| 4 | [Commodity Breakout](strategy4_commodity_breakout.md) | `commodity_breakout_bot` | Metals coiled-spring dormancy breakout (live); energy/grains seasonal TBD. |
| 5 | [US News Catalyst](strategy5_us_news_catalyst.md) | `us_news_stock_bot` | News → Claude sentiment → confirmed-reaction entry → same-day exit. |

## Planned (in research/design)

| # | Strategy | One-line |
|---|---|---|
| 6 | [Social Rotation](strategy6_social_rotation.md) | Reddit + Benzinga + Opus → sector-rotation ETF swing. |
| 7 | [FX Macro Swing](strategy7_fx_macro.md) | Majors trend skeleton + Claude central-bank overlay (OANDA). Carry rejected. |
| 8 | [Catalyst Rotation](strategy8_catalyst_rotation.md) | Multi-day catalyst-momentum portfolio w/ a freshness-decaying conviction score. The swing evolution of #5. |

## Retired / rejected

- **SP500 Periscope bot** (`sp500_index_bot`) — intraday SPX mean-reversion reading Unusual Whales
  Periscope GEX screenshots. **Retired 2026-06-24:** can't beat buy-and-hold (intraday-only misses the
  overnight drift); long 1DTE calls lose to the IV crush on the bounce; put credit spreads are
  ~breakeven; signal too small to clear option frictions. GEX is a free computation on the IBKR/yfinance
  options chain — no paid Periscope needed; its only salvageable use is a gamma-**regime** input to #8.
- **Carry (FX)** — crowding *is* the crash; no edge vs funds. (See #7.)
- **VIX Spike Recovery (SOXL)** — bigger spikes → worse outcomes. (See #3.)
- **Intraday grains** — no backtestable data; latency/limit-lock/USDA traps. (See #4.)
- **Cross-market spillover** — priced instantly via 24h futures; PM-Gap already captures the ≥5% slice.

## Cross-cutting infrastructure

Shared `trading_common` lib (IBKR/data, Claude sentiment, Telegram, journaling) · Bot Launcher GUI ·
Telegram TRADE-OPENED/CLOSED/ALERT on every bot. The recurring lesson across rejections: compete only
where the lane is open (systematic / news+Claude), never where it's closed (latency, physical info,
crowded premia).
