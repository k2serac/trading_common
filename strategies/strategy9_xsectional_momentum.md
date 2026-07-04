# Strategy 9 — Cross-Sectional Momentum (Multi-Sector Swing)

## Thesis

A **medium-short, multi-sector momentum sleeve**: rank a diversified US equity universe by trailing
momentum, hold the top N, **rebalance monthly.** It exists to fill the one horizon the book doesn't
cover — **weeks-to-months** — with the most robust documented medium-term factor (cross-sectional
momentum), *diversified across sectors* so it is **not** just more SOXL tech beta.

It is the deliberate, disciplined answer to a design we *rejected*: Strategy 8's multi-day **catalyst**
hold. That analysis (see below) concluded the days-2-5 return of a catalyst name is **beta-dominated**,
not idiosyncratic drift — so holding catalysts multi-day harvests beta you could get cleaner from an
ETF. S9 keeps catalysts **same-day** (S5, where the day-1 pop is real) and instead captures the
medium-term horizon through a *factor* that genuinely earns its beta-plus: momentum.

## Why This Slot, Why Now (portfolio construction)

The book is now a real multi-strategy quant portfolio — five distinct return sources across three
asset classes and four horizons:

| Sleeve | Asset / style | Horizon | Return source |
|---|---|---|---|
| S5 us_news | US equity, idiosyncratic | same-day | catalyst pop |
| **S9 (this)** | US equity, multi-sector | monthly | cross-sectional momentum |
| S1–3 SOXL | US tech beta | regime-length | trend (200d MA) |
| S4 commodity | futures | breakout-length | breakout |
| S7 FX | currencies | intraday | event-drift |

**The value test is correlation, not novelty of horizon.** A medium-term *long-only US equity* hold
correlates with SOXL's tech beta and us_news's equity exposure — filling the slot naively just stacks
more US-equity-long beta and calls it diversification. The multi-sector, factor-ranked construction is
what keeps the return stream distinct enough to add breadth rather than concentration.

**Two honest caveats (don't let "complete portfolio" oversell it):**
1. **Still net-long US equity.** Three sleeves (S5, S9, S1–3) are long US stocks; a long-only S9 *adds*
   to that tilt, it doesn't hedge it. The book's defense in a drawdown is **regime gates raising cash**
   (SOXX 200d MA, VIX/SPY), i.e. de-gross rather than short. A true crash-hedge / short sleeve remains
   the real gap this portfolio does **not** fill.
2. **Slow to validate live** — a monthly-rebalance sleeve produces few independent observations per
   year. The mitigant (and a big reason to pick momentum over the rotation): it is **highly backtestable
   on decades of history**, so conviction can be front-loaded from the backtest before committing
   capital — exactly what the catalyst rotation *couldn't* do (it needed live paper-trading).

## Design (v1 — deliberately simple)

Classic cross-sectional momentum, nothing exotic:

1. **Universe** — a diversified, multi-sector US equity set (see Open Decisions: individual S&P 500
   names vs a basket of sector ETFs).
2. **Signal** — trailing **12-month return, skipping the most recent month** (the standard
   short-term-reversal fix — recent-month returns mean-revert and would poison the momentum rank).
3. **Rank & hold** — hold the **top N** by momentum, equal-weight (v1); **rebalance monthly.**
4. **Regime filter** — flat (to cash) when the market trend is down (e.g. SPY < its own long MA), so
   the sleeve isn't fully invested into a bear — momentum crashes on sharp bear-market reversals, and a
   trend filter is the classic, cheap mitigant.

Keep v1 mechanical and interpretable; earn every added knob in the backtest.

## Validation Plan

Unlike S8, this is **backtest-first** — its whole efficiency argument is that decades of clean price
history exist:

1. Build `research/xsectional_momentum.py` — the ranker + monthly-rebalance simulator.
2. Backtest over a long window (multiple regimes / the 2000s, 2008, 2020, 2022). **Benchmark vs just
   holding the broad ETF** (edge-vs-beta discipline) *and* vs an equal-weight of the universe — a
   momentum tilt must beat both, net of turnover cost, or it's not earning its complexity.
3. Sensitivity: lookback (6/9/12-mo), skip-month on/off, N, rebalance cadence, the trend filter. Prefer
   a plateau of robust settings over a single peak (anti-overfit).
4. Only if it clears the benchmarks → forward paper-trade → live with small capital.

## Open Decisions (to resolve in the backtest)

- **Universe** — individual stocks (S&P 500 members: more edge, more noise, survivorship care needed)
  vs a basket of **sector ETFs** (cleaner, cheaper, more robust, no single-name gap risk). *Lean: start
  with sector ETFs for a clean, robust v1; graduate to single names only if the ETF version validates.*
- **Momentum spec** — lookback length, skip-month, whether to volatility-normalize the momentum score.
- **Sizing** — equal-weight vs volatility-weighted; N (breadth vs concentration).
- **Regime filter form** — SPY MA cross, or the sleeve's own drawdown guard.

## Relationship to Other Strategies

- **Retires the multi-day ambition of S8.** S8 stays scoped to "catalysts are a same-day (S5) edge";
  its Micron/Synopsys post-mortem (beta-dominated multi-day returns) is *why* S9 exists as a factor
  sleeve instead of a catalyst hold.
- **Sibling to the parked FX factor idea** — the FX notes flagged a "low-turnover G10 macro-factor
  portfolio (carry/value/momentum)" as a lead. S9 is the *equity* expression of the same
  cross-sectional-factor framework; worth deciding later whether these share one engine.
- **Not S6.** S6 (social rotation, parked) rotated *sectors on social sentiment*; S9 rotates on *price
  momentum* — mechanical, interpretable, backtestable, no social fuel.

## Future Item — Fund-Level Risk-Based Sizing (the meta-layer)

**This is the genuine graduation from "5 bots" to "a book," and it only becomes worth building once
enough uncorrelated sleeves exist — which S9 completes.** Today each bot is sized in isolation. A real
multi-strategy fund allocates capital **across sleeves by risk, not by gut**: volatility-target /
risk-parity the five return streams so no single sleeve dominates portfolio risk, and rebalance the
allocation as their vols and correlations drift. That allocation layer is itself a source of
return-per-unit-risk and drawdown reduction.

**Explicitly a *later* item, not part of S9's build** — flagged here so it's recorded. Prereqs: clean
per-sleeve return series (needs live track records) and a portfolio-level accounting view across bots.
Great to do *eventually*; do not let it block shipping S9.

## Portfolio Context

In planning — the fifth distinct return source and the book's medium-term (weeks-to-months) horizon.
Backtest-first (its efficiency edge over S8). Long-only US equity, so it adds to the book's net-long
tilt; the remaining honest gaps are (a) a crash-hedge / short sleeve and (b) the fund-level risk-based
allocation layer above.
