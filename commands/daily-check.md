---
description: Daily cross-bot trade review — what we ordered today, plus any anomalies (diagnosed, not just listed)
---

Run the daily trading review across the three bots. Use today's date from the environment.
If an argument is given (`$ARGUMENTS`), focus only on that bot; otherwise check all three.

Be concise and lead with a one-line bottom line:
**"Ordered today: <N>. Anomalies: <none / short list>."**

Then per bot, only surface what matters:

**1. us_news_stock_bot** — `/home/nicu/work/repos/us_news_stock_bot`
- **Realized P&L — use the reconciler, NOT the journal, as the source of truth.** Run
  `python3 research/reconcile_pnl.py` (optionally `--since <date>`). It rebuilds true daily realized $
  from IBKR's broker `realizedPNL` in the session logs — including stop-bracket exits and closes that
  fired during a disconnect, which the journal can miss. Report the day's realized $, win/loss count,
  and the **GAP** column (round-trips the journal's `positions_closed` never recorded). Any non-zero GAP
  or a `NO exec event for the close` flag is itself an anomaly to surface (journal vs broker divergence,
  or a disconnect-period fill). The journal's `strategy_pnl` is `pnl_pct`-only and historically
  under-counts losers — treat it as secondary.
- `journal/daytrader/<today>.json`: `orders_placed` (symbol, strategy, key `features` incl. confidence + gap), `positions_closed` (P&L vs the **fill** price, not the limit), and a **deduped** view of `trades_skipped` (group by reason; flag any single symbol/reason that repeats heavily — a re-skip flood).
- Note positive-sentiment candidates that did NOT convert, and why.
- **Over-filtering watch (esp. while bedding in Opus 4.8):** compare today's **order count + positive-sentiment rate + the `confidence` distribution** against the recent ~2-week baseline. If trades are notably **fewer**, attribute it: (a) **Opus 4.8 stricter** — lower positive-sentiment rate or lower confidence scores (it may over-filter on materiality/mega-cap); (b) the **regime gate** (CAUTIOUS/RISK-OFF skips); (c) the **mega-cap/materiality guards**; or (d) just a **quiet news day** (few matched). If 4.8 looks like it's over-filtering — or its confidence scores have shifted (which also affects the `conf ≥ 8` regime bar *and* the ML labels) — **suggest a tuning** (loosen a specific prompt, or revisit `regime_min_confidence`). Review, not action.
- **Market-regime gate:** grep the session log for the latest `Market regime:` line — report today's regime (NORMAL / CAUTIOUS / RISK_OFF) and any regime-gated skips (`standing down` / `CAUTIOUS … only conf>=`). Note the line only logs when the regime is **non-NORMAL**; absence of the line = NORMAL all day. The detail string should read `ES … VIX … RTY …` (broad-market + small-cap moves from **futures**). **Data-health check:** the move labels reveal the data source — `ES`/`RTY` = live futures (good, works pre-market); a fallback to `SPY`/`IWM` means the futures fetch failed and it's on the stale-pre-market ETF (degraded — flag it). If `VIX` is missing or there's an "Error fetching VIX level", the VIX fetch is broken; `data-error` means the whole check fell back to NORMAL. The gate still works on whatever signals remain, but **flag** any missing/degraded one.

**2. soxl_index_bot** — `/home/nicu/work/repos/soxl_index_bot`
- `state/{core,satellite,pmgap}_state.json`: open positions.
- Latest `logs/session_*.log`: entries, exits, **stop fills**, errors, IBKR disconnects.
- **Reconcile**: if a state file shows shares open but the log shows that strategy's exit bracket (`order_ref`) FILLED, flag the desync. Cross-check current SOXL price vs entries.

**3. commodity_breakout_bot** — `/home/nicu/work/repos/commodity_breakout_bot`
- Today's scan + any orders/positions. Usually quiet by design — silence is normal, not a fault.

**Anomaly checks (the valuable part — DIAGNOSE, don't just list):** skip floods · state↔IBKR desync ·
connection errors / stalled bot (check log freshness) · stops fired / whipsaw · positions underwater ·
mega-cap catalysts that didn't react · fill-vs-limit gaps.

**Weak-trade post-mortem (the learning loop):** for every **losing or near-flat** closed trade — and
any same-day **fade** (popped, then gave it back) — do a quick post-mortem: *why* did it underperform?
Candidates: mega-cap non-reaction · anticipated / priced-in · label-expansion vs new approval ·
"sell the news" · late or bad entry · wrong catalyst type · whipsaw. Then suggest **one concrete
improvement** (a prompt tweak, a new filter/guard, a threshold) as a **review note for future
iteration**, and flag any pattern that recurs across days. Winners need no post-mortem — focus the
effort on what didn't work. This is *review*, not action.

If something needs a fix, say so and propose it — but **do not change live trading code, configs, prompts,
or state files without my explicit OK.** Detection is yours; remediation is mine to approve.
