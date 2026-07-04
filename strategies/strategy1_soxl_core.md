---
name: strategy1-soxl-core
description: "Strategy 1 — SOXL Core: hold 3x SOXL while SOXX > 200d MA, exit first day below. Crash-avoidance edge (2022: -7.7% vs -86.5% B&H). +999%/5yr. LIVE (soxl_index_bot)."
metadata:
  type: project
---

# Strategy 1 — SOXL Core (200-day MA Regime)

**Status:** LIVE · `soxl_index_bot` · capital pool: own

## Thesis

Hold SOXL (3× leveraged semiconductor ETF) only while the semiconductor sector is in a confirmed
uptrend, and step fully aside the moment it isn't. The entire edge is **2022-style crash
avoidance**: a 3× ETF that drops 86% in a bear market needs a 7× gain just to recover, so
*preserving capital through the crash* is what lets the position compound through the recovery. We
give up some upside in exchange for not getting destroyed.

## Mechanics

- **Signal:** is SOXX (the unleveraged semi index) above its **200-day moving average**?
- **Evening check ~16:15 ET** (~6 regime changes/year):
  - SOXX prev close **> 200d MA** → hold/buy SOXL (market-on-open).
  - SOXX prev close **< 200d MA** → exit SOXL entirely (market-on-open), first day below.
- Long-term position. **No stop-loss** — the regime filter *is* the exit.

## Backtest (5yr, 2021–2026)

| | Core 200d MA | SOXL Buy & Hold |
|---|---|---|
| Total return | **+999%** | +483% |
| Max drawdown | −79% | −91% |
| **2022** | **−7.7%** | **−86.5%** |

**MA-period sweep:** 50d → +712% (−74% in 2022); 100d → +320%; **200d → +999% (−7.7% in 2022)**;
B&H → +483%. 200d wins decisively, and the 2022 protection is the reason.

## Risk

3× leverage; large absolute drawdowns even with the filter (−79%); whipsaw risk near the MA in
choppy regimes (a few false exits/entries per year — accepted as the cost of crash protection).

## Key decision

200d (not 50/100d) — confirmed by the sweep. Any change that worsens 2022 protection is suspect
even if it lifts the headline number; the 2022 −7.7% vs −86.5% is the defining edge.
