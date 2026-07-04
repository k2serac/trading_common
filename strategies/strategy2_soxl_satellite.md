---
name: strategy2-soxl-satellite
description: "Strategy 2 — SOXL Satellite: intraday momentum add when semis lead (QQQ>VWAP + SOXX outperforms QQQ >=0.75% + SOXX>5d MA). +257%/5yr. LIVE (soxl_index_bot)."
metadata:
  type: project
---

# Strategy 2 — SOXL Satellite (Intraday Momentum / Relative Strength)

**Status:** LIVE · `soxl_index_bot` · capital pool: own

## Thesis

A tactical satellite around the Core position: on mornings when semiconductors are clearly *leading*
the market with confirmed intraday momentum, add a leveraged SOXL position and ride the
multi-day continuation. Captures the strong-trend days the regime-only Core doesn't time precisely.

## Signal (10:05 ET — all three must fire)

1. **QQQ price > intraday VWAP** (broad tech bid).
2. **SOXX outperforming QQQ from the open by ≥ 0.75%** (semis *leading*, not just rising).
3. **SOXX previous close > its 5-day MA** (short-term trend intact).

Entry: first bar after 10:05 AM ET, bracket order on SOXL.

## Exit

ATR **2.5×** trailing stop (14-day ATR) · **8%** hard floor stop · **7-trading-day** hold cap.

## Backtest (5yr, ~39 trades)

| Metric | Value |
|---|---|
| Compounded return | **+257%** |
| Sharpe | 0.26 |
| Win rate | 44% |
| Avg P/L per trade | +4.5% |
| Avg winner / loser | +19.4% / −7.0% |
| Avg hold | 4.6 days |
| Trades/year | ~8 |

Asymmetric payoff (big winners, capped losers) carries a sub-50% win rate.

## Important history

This strategy was **silently dead in live trading** until 2026-06-22: a timezone bug in
`get5MinBars` (IBKR returned non-ET bar timestamps; the VWAP filter assumed ET → empty scan → no
signal ever) meant it never placed a trade. Fixed at the data layer (normalize bars to ET). Also
added an **entry-window guard** (skip if the 10:05–10:15 evaluation completes late, e.g. after an
IBKR disconnect — no entering on a stale signal hours later). First real live trade: 2026-06-23.

## Risk

3× ETF on an intraday-momentum entry; ATR-based trail can be very wide in high-vol regimes (the 8%
floor is the real protection). Relative-strength entries on crash-bounce days are higher-risk.
