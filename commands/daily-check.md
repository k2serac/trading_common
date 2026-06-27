---
description: Daily cross-bot trade review — what we ordered today, plus any anomalies (diagnosed, not just listed)
---

Run the daily trading review across the three bots. Use today's date from the environment.
If an argument is given (`$ARGUMENTS`), focus only on that bot; otherwise check all three.

Be concise and lead with a one-line bottom line:
**"Ordered today: <N>. Anomalies: <none / short list>."**

Then per bot, only surface what matters:

**1. us_news_stock_bot** — `/home/nicu/work/repos/us_news_stock_bot`
- `journal/daytrader/<today>.json`: `orders_placed` (symbol, strategy, key `features` incl. confidence + gap), `positions_closed` (P&L vs the **fill** price, not the limit), and a **deduped** view of `trades_skipped` (group by reason; flag any single symbol/reason that repeats heavily — a re-skip flood).
- Note positive-sentiment candidates that did NOT convert, and why.

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
