# Strategy 3 — SOXL PM-Gap (Pre-Market Gap Momentum)

**Status:** LIVE · `soxl_index_bot` · capital pool: own

## Thesis

When SOXL gaps up hard overnight in a bullish regime, the move tends to continue into and through
the open. Buy the open and ride the multi-day follow-through. (This also *is* the tradeable slice of
overnight Asia-semis spillover — the gap already prices it; only the rare big dislocation continues.)

## Signal (07:00 ET pre-market scan)

1. **SOXL pre-market price ≥ 5% above prior RTH close** (at 07:00 ET).
2. **SOXX previous close > 200d MA** (bullish regime filter).
3. **Not already in a position** (no-overlap — mandatory).

Entry: RTH open (09:35 ET) bracket. Exit: ATR **2.5×** trail · **8%** floor · **7-day** cap.

## Backtest (5yr, 43 trades)

| Metric | Value |
|---|---|
| Compounded return | **+243%** |
| Sharpe | 0.23 |
| Win rate | 42% |
| Avg P/L | +4.3% |
| Avg winner / loser | +21.1% / −7.8% |
| Avg hold | 4.0 days |
| Trades/year | ~9 |

## Threshold sweep — 5% is the global optimum (2026-06-22)

| Gap | Trades | Sharpe | $10k→ | Max DD | 2022 |
|---|---|---|---|---|---|
| 3% | 75 | 0.08 | +24% | **−80.7%** | −40.1% |
| 4% | 54 | 0.14 | +86% | −60.2% | −23.0% |
| **5%** | 43 | **0.24** | **+260%** | **−40.6%** | −16.3% |
| 6% | 33 | 0.21 | +120% | −47.1% | −9.0% |

5% wins on return, Sharpe, win rate AND drawdown simultaneously. Lower = noise/fade on a 3× ETF
(3% is catastrophic). Do not lower it.

## Key locked-in decisions

Scan at **07:00** (later scans underperform with no-overlap) · **5%** threshold · SOXX **200d** MA
filter (not 5d) · **no** QQQ filter (redundant at 5% gaps) · **no-overlap** mandatory.

## Rejected sibling

**Strategy A — VIX Spike Recovery: REJECTED.** Bigger VIX spikes → *worse* outcomes (≥40% spike →
0% win rate). VIX spikes signal a market still falling, not a fear peak.
