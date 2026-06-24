# Strategy 7 — FX Macro Swing

## Thesis

Trade liquid FX majors on a **days-to-weeks swing horizon**, driven by central-bank policy
divergence and macro news — *not* intraday, and *not* carry. The dominant driver of FX is the
interest-rate differential and the divergence in central-bank policy paths; any edge that ignores
that is fighting the actual engine.

The edge for a solo operator isn't latency, balance sheet, or data — funds beat us on all three.
It's **cheap, fast, decent qualitative macro reading via a frontier LLM, at a swing horizon** — a
gap that systematic funds skip (no qualitative read) and macro desks fill only with expensive
analysts at high frequency. Lean into the proven news+Claude muscle (us_news_stock_bot / Strategy 6),
not into quant carry/trend where we have no advantage.

## Composition — two complementary layers

Built as **"#2 + #3"** from the original brainstorm; carry (**#1**) was tested and rejected.

### 1. Trend skeleton (the backtestable baseline)
Time-series momentum on a majors basket, inverse-vol sized. Generates the candidate direction.
Fully testable on historical FX candles.
- Default universe: **EUR/USD, USD/JPY, GBP/USD** (most liquid, most policy-driven).
- Lookback: backtest **1mo / 3mo / 6mo** and let the data pick — do not assume.

### 2. Claude central-bank / macro overlay (the actual edge)
Each morning (plus event-driven on major releases), Claude reads overnight macro + central-bank
communication and outputs a directional bias + conviction per pair. Same pattern as
us_news_stock_bot — systematic trigger + Claude gate — inverted for FX.

## Combining Rule — "trend proposes, Claude disposes" (asymmetric)

- Claude needs **trend agreement to get IN** (no acting on news noise).
- Claude can get **OUT unilaterally** (early exit at a regime shift, even before price breaks).
- Conservative on entry, aggressive on risk reduction — mirrors the multi-gate entry of the equity bots.

**Why the two layers are complementary, not redundant:** trend-following is structurally *late at
turns* (gives back the tail); news/Claude is *noisy* (a single headline looks like a regime shift).
Together each fixes the other — trend confirms a news shift is real (filters noise); Claude catches
the inflection before the trend rolls over (fixes lateness). News leads price; trend confirms price.

## Why Carry Was Rejected (Strategy #1)

A crowded trade where **the crowding *is* the crash**: every fund holds the same positive-carry
positions and exits through the same door on risk-off (Aug-2024 Yen unwind, 2008, LTCM 1998). You
earn a thin, competed-away premium while standing closest to the steamroller — and on a small
account you have no edge vs funds on latency, balance sheet, or financing. The 2024 Yen unwind
already hurt the SOXL book via the same mechanism. Settled — do not reopen.

## Worked Example (EUR/USD)

- **Alignment:** 3-mo momentum positive + Claude reads ECB hawkish / Fed dovish → divergence
  favors EUR → long, full size.
- **The money case (early exit):** long on trend, price unbroken; overnight ECB turns dovish +
  Fed minutes hawkish → Claude flags the narrative flip → exit *days* before the momentum signal
  would roll. Skips the give-back that pure trend-following always eats at turns.
- **Noise filter:** a headline spikes GBP but the 3-mo trend is flat → no entry.

## Vehicle & Platform — OANDA (not IBKR)

User has an OANDA account and prior v20 API experience; clean REST + streaming API, well-suited to
FX-only with flexible unit sizing. It's a **new connector** separate from the IBKR-based bots —
fine, since Strategy 7 is FX-only. Bonuses:
- OANDA provides **additional news on top of Benzinga** (richer signal for the Claude overlay).
- OANDA's API gives convenient **historical candles** (may not even need Polygon for the backtest)
  and **order-book / positioning sentiment** data.

## Validation Plan (resolves the "discretionary = unbacktestable" problem)

1. Backtest the **trend-only** skeleton → hard baseline (Sharpe, drawdown), watching 2024/risk-off.
2. Forward paper-trade **trend + Claude overlay** and **A/B** against that baseline — measure
   whether the overlay earns its keep (fewer whipsaws, earlier exits at turns).

Hybrid is the lean: a backtestable systematic skeleton + Claude as the live discretionary overlay,
so you're never flying fully blind on a discretionary strategy.

## Open Decisions (to resolve before building)

- Universe width (3 majors vs add AUD/USD, USD/CAD).
- Final trend lookback (data-driven — 1/3/6mo).
- Claude cadence (morning + event-driven on releases).
- Leverage / risk caps; correlation handling (EUR/USD & GBP/USD co-move → cap aggregate USD exposure).
- Backtest data source (OANDA candles vs Polygon FX).
- Avoid: scalping the NFP/CPI release (millisecond game), naive mean-reversion without regime awareness.

## Why This Works (Structural Edge)

You're not competing where you're weak (carry crowding, latency, balance sheet, data). You're
exploiting a genuinely under-occupied gap: **a frontier LLM reading central-bank communication
cheaply and forming a days-to-weeks directional view on liquid majors** — with a trend skeleton to
filter the LLM's noise and an asymmetric exit to catch regime turns early.

## Next Steps

First concrete move: draft the **trend-skeleton backtest** against the `research/` harness pattern,
establish the baseline, *then* design the Claude overlay spec. Carry is settled — don't reopen it.

## Portfolio Context

Adds an **uncorrelated FX sleeve** using the operator's strongest muscle (news + Claude) rather than
competing where there's no edge. Cousin of Strategy 6 (news+Claude swing) and Strategy 8
(catalyst-driven), but on currencies and central-bank macro. In planning — build after the current
us_news bot is validated; forward-paper-trade like Strategy 6/8.
