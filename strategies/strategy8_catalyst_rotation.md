# Strategy 8 — Catalyst-Momentum Rotation

## Thesis

The **multi-day swing evolution** of us_news_stock_bot. Instead of enter-on-catalyst /
exit-same-day, hold a **ranked portfolio** of catalyst-driven single stocks, re-scored daily,
rotating capital out of decaying names and into fresh high-score ones.

It exists to capture the **2–5 day post-news drift** that same-day exit leaves on the table — with
a mechanical, score-driven *"let winners run, cut losers"* that sidesteps the beta-noise problem
(a position down on a red day isn't a loser if it beat the market). Cousin of Strategy 6 (rotation +
scoring) but single-stock and catalyst-driven, not ETF/social.

## The Decaying Conviction Score (core idea)

Think of the score as components with different lifespans:

```
score = catalyst_component (decays over the news drift window)
      + momentum/alpha_component (is it following through vs the market?)
      + trend/regime_component
```

- **Fresh catalyst → full weight**, then **decays over ~2–5 days** — the exit-timing study gives the
  decay *rate* (and it differs by strategy: upgrades fade fast, AINews slower). Closed loop.
- **A new catalyst resets the clock → "catalyst stacking."** A second initiation from another broker
  re-freshens the score and compounds conviction → keep the name.
- **No fresh catalyst + decayed + price stalling/falling → score drops below threshold → sell.**
- **The score is the *rotation* sell rule** — a name leaves the book when its score falls below the
  cut or below a fresher candidate. Layered on top are **fast risk exits** (bad news, MA break, hard
  stop — see *Exit Stack*) for sharp failures the once-daily rescore is too slow to catch.

## The Conviction Score — Final Factor Set

Guiding principle: **never score on what an upstream filter — or the catalyst universe itself —
already compresses** (no variance = no predictive power). A tight orthogonal set beats a kitchen
sink (less overfitting, robust out-of-sample, interpretable).

| Factor | Measures (level) | When usable | Source | Status |
|---|---|---|---|---|
| **ma_trend** | stock vs itself — price > 20 > 50 SMA ("not a falling knife") | **entry** | yfinance + pandas-ta | prior |
| **alpha** | stock vs market (idiosyncratic) | **hold** (needs ≥1 day) | yfinance vs SPY/sector | ✅ validated |
| **sector_trend** | sector ETF vs market (1-mo return / above-EMA) | both | sector ETFs via yfinance | prior |
| **market_regime** | the market itself (SPY vs 50-SMA, VIX) | both | yfinance | prior |
| **freshness** | catalyst decay over time (temporal axis) | both | days since catalyst | prior (rate from exit study) |

Layout = **stock + sector + market** (space) + **freshness** (time), with momentum covered at *both*
ends (`ma_trend` at entry, `alpha` on the hold). One-line story: *"Is this stock in a healthy
uptrend, outperforming the market, in a strong sector, in a friendly regime — and is the catalyst
still fresh?"* All factors are reconstructable from price history + the trade journal, so the scorer
is a pure research build with nothing to change live.

**Pruned out (and why):** `catalyst_strength` (Claude's gate already selects strong catalysts →
compressed); `PT-upside %` (the upgrade prompt already requires a large price target → compressed,
and analyst-only); `entry_gap` (MaxVarFromNews already filters it); `rvol` (overlaps with alpha,
and every catalyst spikes volume by nature → compressed); `market_cap` (predicts move *magnitude /
volatility*, not direction — it's a position-sizing input, not a conviction signal).

**Corollary:** the current bot's filters (Claude + MaxVar + liquidity) already nail *entry*
selection, so a conviction score adds little at entry — its value is the multi-day **hold/rotation**
decision (where `alpha` + `freshness` carry the variance). That's why the score belongs to
Strategy 8, not the current same-day bot.

### Candidate factors (to validate — not yet in the set)

- **`peer_earnings_reaction`** — a same-day strong earnings reaction from an **industry peer** (same
  GICS sub-industry) as an industry-level read-through tailwind (*"NVDA blows out → the whole semi
  complex bids → SNPS rides it"*; **intra-industry earnings information transfer**, a documented
  effect). It's an *event* signal (sharp, dated) — distinct from the slow `sector_trend` — and decays
  like `freshness` but at the **industry** level. Proxy = the peer's **earnings-day price reaction**
  (the market reaction already encodes materiality), not the raw beat/miss.
  - **The sign risk is handled for free by the MinVar=0 entry floor.** The competitive case (a peer
    beats by *taking* our company's share → our stock trades red) self-filters — we only enter when
    our stock is *also* flat-or-up, i.e. the rising-tide case. So the floor fixes the **sign**; the
    regression only needs to calibrate the **magnitude** (strong booster vs. noise). Multi-day
    competitive risk (rising tide day 1, fades day 3) is caught by the *Exit Stack*, not the floor.
  - **Peer pool = Finnhub `/stock/peers`** (per-symbol, free, covers small caps), then
    **correlation-weighted**. LIVE-VERIFIED 2026-06-24 (real API key): Finnhub peers is
    **sector/size-coherent but NOT EDA-tight** — CDNS/SNPS both return a broad large-cap-software basket
    (`PLTR, APP, CRM, CDNS, SNPS, DDOG, ADBE, INTU, ADSK, ROP, MSTR`), *not* a clean EDA list. So the
    pool is broad; the **real discriminator is market-residual return correlation WITHIN the pool**:
    SNPS↔CDNS = **+0.67** (the lone true co-mover) vs **+0.15–0.32** for every loose sector name — a
    clean gap. **Best form: weight each peer's earnings read-through by its correlation to the held
    name** (CDNS earnings → strong read-through to SNPS; CRM → negligible) — one continuous weight that
    fuses "is a peer" + "actually co-moves." Filter to **live tickers** (acquisitions delist peers —
    ANSS→Synopsys, MENT→Siemens). Cache the map; no network in the hot path.
  - **Rejected after LIVE testing — note all three pasted "API samples" turned out fabricated, caught
    only by querying the real endpoints:** OpenFIGI (symbology only — `marketSector:"Equity"`, no
    industry); Finnhub `profile2` `gsubind`/`naics` (don't exist — real `profile2` returns just
    `finnhubIndustry:"Technology"`); the clean `["CDNS","SNPS","ANSS","MENT"]` peer list (real one is
    the broad software basket above); Wikipedia GICS (S&P-500 only → misses small caps); FinanceDatabase
    (free/broad but coarsest level is "Software"). **Validate the factor via `factor_report` before
    adding it** — log it as a feature and let the coefficient decide.

## Score Methodology & Weighting (let the data assign the weights)

Normalize each factor to 0–100 (percentile / z-score), direction-align, weighted sum → 1–100. Use
the score primarily for **position sizing** (small on a 40, full on an 85), not just filtering.

Weights are the hard part — you can't know them a priori, and you shouldn't guess. Three stages,
gated by sample size:
1. **Now (~40 noisy trades): equal weight.** Famously robust when data is thin; a baseline to beat.
2. **~50–150 trades: Information Coefficient.** Test each factor's correlation with forward outcome
   (the exit-study alpha label); drop near-zero-IC factors; *gently* tilt toward the high-IC ones.
3. **200+ trades: regularized regression.** Ridge/Lasso (regularization is non-negotiable — it stops
   overfitting; Lasso auto-drops dead features), cross-validated. Trees only once you're in the
   hundreds and want interactions.

**Label = forward 3-day *alpha*** (market-relative — strips the beta noise).

## Daily Ranked Rebalance

Hold top-N by score; each day sell decayed names, buy fresh high-score ones. Non-negotiable
add-ons so it isn't naive:
- **Hysteresis / a swap margin** — only replace a held name if a new candidate beats it by a
  *meaningful* margin (else you churn daily on tiny score differences).
- **Caps** — max ~10 names, 1–2 swaps/day.

**Turnover is *lower* than the current intraday bot, not higher.** Today's model round-trips *every*
position *every* day to capture one day's move (zero amortization); Strategy 8 holds names multi-day
and rotates only 1–2/day, so each round-trip captures the full 3–5 day drift. The right metric is
**cost per unit of move captured**, where multi-day holds win — and spread/slippage (bigger than
commission on a small account) favors it for the same reason. Hysteresis is for avoiding churn, not
because turnover is inherently high.

## Exit Stack (protecting the hold)

The MinVar=0 floor only protects the *entry*; a multi-day hold needs exits that protect the *hold*.
The score handles **slow** decay (the rotation rule above); layered on top are **fast** risk exits
for sharp failures the once-daily rescore can't react to in time. OR-logic — any trigger sells:

| Trigger | Catches | Type | Note |
|---|---|---|---|
| **Material negative news** | catalyst thesis reversed | fundamental | reuse `_handle_sentiment_reversal`; **gate on high `confidence`** so a held name's constant news flow doesn't whipsaw it out on a minor negative |
| **Daily *close* below the MA** | trend/momentum broke | technical | 10/20-day MA — **not** intraday VWAP (VWAP resets daily → that's the intraday bot's tool). Symmetric with `ma_trend` entry (enter above → exit below). Close-based to avoid intraday-wick whipsaw |
| **Score decay below cut** | catalyst went stale | time | the rotation rule (above) |
| **Hard ATR / % stop** | gap / crash | tail | catastrophe floor |

Continuous news monitoring covers **every** held name — cross-reference incoming news against the
`OpenTradeRegistry` holdings and run it through the existing us_news sentiment pipeline. Not a new
build; the entry machinery already watches and reverses on negative sentiment.

## The Pipeline This Completes

- **Conviction score** = the **features** (the 5-factor table above)
- **Exit-timing study** (`us_news_stock_bot/research/exit_timing_study.py`) = the **labels** (forward alpha / MFE)
- **Rotation framework** = the **deployment** (a live, self-managing swing portfolio)

## Validation Plan

Backtesting a rotation cleanly is hard (needs historical catalysts + scores + prices), so it's a
**forward paper-trade** validation, like Strategy 6/7 — and *gated* on first proving the score works:

1. Build a v1 scorer (`research/conviction_score.py`) from the 5 factors.
2. Run it **retrospectively** vs the exit-study P&L and **prove score → forward alpha correlates**
   (the IC step). If `alpha`/`freshness` don't predict, stop here.
3. Only then design the rotation portfolio — as its own strategy (a portfolio manager, not a
   retrofit of the intraday bot).

## Open Decisions (to resolve before building)

- N (portfolio size), swap margin / hysteresis threshold, max turnover.
- Decay function shape (linear vs exponential) and rate per catalyst type (from the exit study).
- Score → position-size mapping (tiers).
- Whether to reuse the us_news news+Claude pipeline or fork it.

## Why This Works (Structural Edge)

Captures multi-day drift that the same-day exit discards, with a mechanical *let-winners-run /
cut-losers* rule driven by **alpha** (validated) instead of raw P&L — so beta noise never mislabels
a working catalyst on a red day. The score's job is *tradeability and context* (the dimensions
Claude doesn't see), layered on top of Claude's already-tuned catalyst gate.

## Next Steps

Do **not** build the rotation engine first. Run the current bot well → accumulate clean, labeled
trades → re-run the exit study as the sample grows → build & validate the v1 scorer → then design
the rotation. Virtuous loop: the better the current bot runs, the better the data, the stronger
this strategy will be when we reach it.

## Portfolio Context

In planning. The swing evolution of us_news_stock_bot; sibling to Strategy 6 (social rotation) and
Strategy 7 (FX macro) in the news+Claude swing family. Gated on multi-day trade data to validate the
`alpha`/`freshness` factors. Cost is *not* a concern (see turnover note); the only real gate is
proving the score predicts outcomes.
