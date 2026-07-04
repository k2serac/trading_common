---
name: strategy5-us-news-catalyst
description: "Strategy 5 — US News Catalyst: Benzinga news -> Claude sentiment -> confirmed reaction-band entry -> same-day exit. 5 catalyst types. LIVE (us_news_stock_bot)."
metadata:
  type: project
---

# Strategy 5 — US News Catalyst (Intraday News Momentum)

**Status:** LIVE · `us_news_stock_bot`

## Thesis

Catch genuine, *fresh* bullish catalysts on liquid US stocks before/at the open, enter on a
confirmed reaction, and ride the institutional-pre-market → retail-RTH follow-through. Currently
**same-day** (flat by the close); the multi-day evolution is [[strategy8_catalyst_rotation]].

## Pipeline

```
News (Benzinga via Massive) → regex pattern match → Claude sentiment gate
  → web-search "already priced in" freshness check
  → reaction-band monitor → bracket entry → exit near the close
```

- **Strategies (regex + per-strategy Claude prompt + context):** PharmaDrugApproval, CompanyUpgrade,
  AINews, AcquisitionNews, ShareBuyback.
- **Reaction band:** after positive sentiment, queue the symbol and enter only when price is within
  `[MinVarFromNews, MaxVarFromNews]` of the **pre-catalyst close** (the after-hours anchor uses the
  *previous* session close so the band measures the move from before the catalyst).
  - **MinVar = 0** across all strategies (enter on any flat-or-up reaction — don't wait for a
    confirming move, but still skip a stock trading *red*).
  - **MaxVar** = the no-chase ceiling (halved after micro-caps were filtered out): Pharma 7.5,
    Acq 5, AINews/Buyback 3, Upgrade 2.5.
- **Entry limit** = `min(current + reaction_limit_var_pct%, close × (1+MaxVar%))`; capped, not market.
- **Exit:** ATR/VWAP exits + pre-close sweep (~same-day). Multi-day positions survive restarts via
  the OpenTradeRegistry.

## Risk filters

Max orders/day & /strategy · max $/trade · earnings-day skip · min avg $-volume (liquidity) ·
restart counter sync · non-US symbol filter · credit-exhaustion shutdown.

## Key fixes / decisions (2026-06)

- **4-hour news-delay bug fixed** — the news-window query sent ET wall-clock labelled `Z` to a
  UTC API → every fetch was ~4h stale, missing fresh pre-market catalysts. (Massive/Benzinga
  timestamps are TRUE UTC despite the `Z`.)
- **Stale-catalyst guard** — skip news published at/before the most recent close (its reaction is
  already in that close).
- **Reaction window now extends through the first `reaction_post_open_minutes` (15) of RTH** — a
  catalyst that's flat/red pre-market but gaps up within band AT the open is now caught (the move is
  often the opening print), keeping MinVar=0 / MaxVar discipline.
- **Mega-cap materiality** — reject immaterial mega-cap showcase AI news.
- **Pre-market-only reaction is intentional** (ride smart-money accumulation → retail follow-through).

## Open research

`research/exit_timing_study.py` — does multi-day hold beat same-day? Early read: **classify by
ALPHA (market-relative), not raw return**; day-1 alpha predicts the multi-day outcome; the MFE gap
favors a trailing stop. Feeds the score/labels pipeline for [[strategy8_catalyst_rotation]].
