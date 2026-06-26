# Strategy 6 — Social Sentiment + Sector Rotation

> **STATUS: PARKED as a standalone strategy (2026-06-25).** Deprioritized behind #8 (cooking on a
> proven base) and #7 (FX macro). Reasons: (1) it runs the proven Claude-synthesis engine on its
> **weakest fuel** — social sentiment is noisy, crowded/arbitraged, and faded post-2021; (2) an
> **internal mismatch** — the social/retail signal is *fast & single-stock*, but the vehicle
> (sector-ETF rotation) is *slow & macro*, so they don't fit; (3) lowest-confidence of the three theses.
> **Salvage (do NOT delete the idea):** repurpose social chatter/momentum as a **secondary FACTOR in
> Strategy 8's conviction score** — *"does this catalyst have social tailwind?"* — confirming a real
> catalyst rather than generating signals on its own (same move as the Periscope/GEX salvage). Revisit
> the standalone only with a *specific* social-signal insight that beats the crowded version.

## Thesis

Identify early sector rotation themes before retail fully prices them in. Not chasing hype —
finding themes with real macro/structural backing that Reddit and news are just beginning to
pick up on. The edge is in the *convergence* of multiple signals, not any single one.

When institutional and retail attention start converging on a theme simultaneously (macro
tailwind + news catalyst + Reddit velocity), the move that follows is often 50–200% over
weeks/months — not 10–15%. You don't need many of those right to have a great year.

---

## Signal Stack (in priority order)

### 1. Benzinga — Primary Trigger
- Catches sector news catalyst first: earnings beats, analyst upgrades, regulatory approvals,
  macro events affecting a sector
- Already integrated in `us_news_stock_bot` infrastructure

### 2. Reddit — Retail Confirmation
Subreddits to monitor:
- `r/wallstreetbets` — meme stocks, biggest volume impact, but lagging
- `r/stocks` — more measured, picks up mid-cap momentum before WSB
- `r/options` — options flow discussion often precedes equity moves

**Key signal: cross-subreddit velocity** — same ticker appearing in multiple subreddits
within a 2-hour window is much stronger than a single-subreddit spike. Corroboration
suggests organic interest rather than a single poster pumping.

### 3. Opus Assessment — Qualitative Gate
Given Benzinga headline + Reddit ticker mentions, Opus evaluates:
- Is the macro environment supportive? (rates, dollar, risk appetite)
- Is the sector catalyst structural or temporary?
- Are Reddit mentions concentrated on quality names or trash?
- Historical precedent for similar rotations?
- Which vehicle (ETF vs single stock), and what hold period?

---

## Workflow

```
Benzinga sector news
    → Opus: "Is this a real multi-week theme or a one-day spike?"
        → YES (structural)
            → Scan Reddit for top mentioned tickers in that sector
            → Cross-subreddit velocity check (2-hour window)
            → Opus: "Which vehicle? ETF or single stock? Size? Hold period?"
                → Entry with bracket order (ATR stop + hold cap)
        → NO → skip
```

---

## Vehicle: ETF-First

**Prioritize sector ETFs over single stocks.**

- Liquidity is guaranteed — can always exit
- Avoids the Reddit liquidity trap (tiny float, bid disappears on exit)
- Captures the theme without single-name blow-up risk
- If the rotation is real, the ETF captures most of the move anyway

**Single stocks only if:**
- Opus identifies a clear standout with real fundamentals
- Market cap > $500M
- Average daily volume > $50M/day
- NYSE/NASDAQ listed (no OTC)
- Real catalyst behind the social hype (not pure pump)

**Example ETF candidates by theme:**
| Theme | ETF |
|---|---|
| Semiconductors | SOXX, SMH |
| AI / Tech infra | XLK, ARKQ |
| Energy | XLE, XOP |
| Biotech | XBI, IBB |
| Financials | XLF |
| Industrials | XLI |
| Commodities | DJP, GSG |

---

## Hold Period

**Swing / multi-week** — this is NOT intraday.

Structural themes play out over days to months. This strategy fills a gap not covered by the
existing 5 strategies (which are intraday, daily, or event-driven).

---

## Open Decisions (to resolve before building)

- [ ] Hold through earnings or cut before?
- [ ] Max hold cap in trading days?
- [ ] Stop-loss approach: ATR-based or % fixed?
- [ ] Which sector ETFs to whitelist as eligible vehicles?
- [ ] Minimum Reddit mention velocity threshold to qualify as a signal?
- [ ] How to weight Benzinga vs Reddit signal if they conflict?

---

## Why This Works (Structural Edge)

Pure social sentiment is noise. The edge comes from the **convergence filter**:

1. Macro tailwind → sector is structurally supported
2. Real industry catalyst → move has a fundamental reason to sustain
3. Reddit velocity → retail is starting to pile in (provides exit liquidity)
4. Benzinga coverage → institutional awareness building

At that point you're not buying hype — you're buying a theme with legs that retail will
pile into over the following weeks, giving you an exit *into* liquidity rather than away from it.

**Historical examples of this pattern:**
- Semis (SOXX/SMH) — late 2022, AI wave building
- AI infrastructure (XLK) — early 2023
- Energy (XLE/XOP) — 2021, Ukraine + supply shock

---

## Next Steps

1. **Research backtest first** — historical Benzinga sector news + Reddit mention velocity
   + price data to validate the signal before building live infrastructure
2. Build Reddit mention scraper (official API, monitor 3 subreddits)
3. Build Benzinga sector classifier (reuse existing Benzinga integration)
4. Prompt engineer Opus assessment for rotation quality scoring
5. Backtest on 2–3 historical themes
6. If edge validated → build live bot (similar architecture to `us_news_stock_bot`)

---

## Portfolio Context

This is **Strategy 6**, complementing the existing 5:

| # | Strategy | Bot | Timeframe |
|---|---|---|---|
| 1 | Core 200d MA | soxl_index_bot | Weekly/macro |
| 2 | Satellite VWAP | soxl_index_bot | Intraday |
| 3 | PM-Gap | soxl_index_bot | Intraday/daily |
| 4 | Seasonal Breakout | commodity_breakout_bot | Multi-week |
| 5 | News Sentiment | us_news_stock_bot | Intraday/event |
| 6 | Social Rotation | *(new bot)* | Swing/multi-week |

The six strategies are largely uncorrelated across timeframes and signal types — a
well-diversified signal book, not five versions of the same bet.
