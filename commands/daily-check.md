---
description: Daily cross-bot trade review — what we ordered today, anomalies (diagnosed), and standing improvement ideas
---

Run the daily trading review across the four bots. Use today's date from the environment.
If an argument is given (`$ARGUMENTS`), focus only on that bot; otherwise check all four.

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
- **Capacity watch — explicitly flag any `MaxActiveTrades limit reached (N/N)` skips.** These mean we were **capacity-bound, not signal-bound**: positive, tradeable catalysts were turned away purely because all position slots were full. Report the **count**, the **symbols/catalysts rejected** (were they good — credible upgrades, small/mid-cap?), and **when the cap bound** (first-come-first-served, so late-morning catalysts get squeezed). Cross-check against `max_active_trades`/`max_amm_per_trade` in `config.toml` and note that all three bots share IBKR account **U2417906** — so more slots competes for shared buying power. If this recurs, suggest a sizing tweak (more/smaller positions) as a review note — but do NOT change config without explicit OK.
- **Over-filtering watch (esp. while bedding in Opus 4.8):** compare today's **order count + positive-sentiment rate + the `confidence` distribution** against the recent ~2-week baseline. If trades are notably **fewer**, attribute it: (a) **Opus 4.8 stricter** — lower positive-sentiment rate or lower confidence scores (it may over-filter on materiality/mega-cap); (b) the **regime gate** (CAUTIOUS/RISK-OFF skips); (c) the **mega-cap/materiality guards**; or (d) just a **quiet news day** (few matched). If 4.8 looks like it's over-filtering — or its confidence scores have shifted (which also affects the `conf ≥ 8` regime bar *and* the ML labels) — **suggest a tuning** (loosen a specific prompt, or revisit `regime_min_confidence`). Review, not action.
- **Market-regime gate:** grep the session log for the latest `Market regime:` line — report today's regime (NORMAL / CAUTIOUS / RISK_OFF) and any regime-gated skips (`standing down` / `CAUTIOUS … only conf>=`). Note the line only logs when the regime is **non-NORMAL**; absence of the line = NORMAL all day. The detail string should read `ES … VIX … RTY …` (broad-market + small-cap moves from **futures**). **Data-health check:** the move labels reveal the data source — `ES`/`RTY` = live futures (good, works pre-market); a fallback to `SPY`/`IWM` means the futures fetch failed and it's on the stale-pre-market ETF (degraded — flag it). If `VIX` is missing or there's an "Error fetching VIX level", the VIX fetch is broken; `data-error` means the whole check fell back to NORMAL. The gate still works on whatever signals remain, but **flag** any missing/degraded one.

**2. soxl_index_bot** — `/home/nicu/work/repos/soxl_index_bot`
- `state/{core,satellite,pmgap}_state.json`: open positions.
- Latest `logs/session_*.log`: entries, exits, **stop fills**, errors, IBKR disconnects.
- **Reconcile**: if a state file shows shares open but the log shows that strategy's exit bracket (`order_ref`) FILLED, flag the desync. Cross-check current SOXL price vs entries.
- **Live-broker cross-check (do this — logs are NOT enough):** a state file can claim shares that the account doesn't hold if the position was closed **externally/manually** (no exit bracket in the log → invisible to log-based checks). This bit us 2026-07-01: `core_state.json` said 71 shares for *days* while the account was flat, and every review "confirmed" 71 from the stale file. So compare state files to **live IBKR positions**, not just the log.

**3. commodity_breakout_bot** — `/home/nicu/work/repos/commodity_breakout_bot`
- Today's scan + any orders/positions. Usually quiet by design — silence is normal, not a fault.

**4. fx_macro_bot** — `/home/nicu/work/repos/fx_macro_bot` (`event_drift_trader.py`)
- **FORWARD TEST, tiny real money** (OANDA acct 001-001-5457117-001, SEPARATE from the IBKR account the other
  three share). The bot is now the **intraday event-drift** strategy (the COT `fx_macro_trader.py` is retired,
  kept as a fallback file). On a US HIGH-impact **data release**, at +15min it enters EUR/USD & GBP/USD in each
  pair's own initial-reaction direction (mechanical base — backtested t≈4.6), gated by a **Claude take/skip/veto
  reasoning gate** (Phase 2), and **flattens all at 20:00 UTC (flat overnight)**. `per_trade_usd=1000`/pair.
- **Liveness first:** is the process running? It's event-driven, so **no trades on days with no US-HIGH data**
  (normal) — do NOT read silence as breakage; check process/log freshness (the watchdog tracks it). A stalled
  process through a data day is the main silent failure.
- `journal/event_drift_state.json`: today's `events` + each `status` (pending/entered/**missed**/skipped_gate),
  `nav_hwm`, and **`halted`** — if `halted:true` the **kill switch tripped** (NAV >25% below HWM); manual restart
  needed = #1 anomaly. **`missed`** = the bot wasn't up at the event's +15min window (recall gap — flag it).
- `journal/event_drift_counterfactual.jsonl` (**the core forward record**): per event, `reactions`, `base_take`
  (what the mechanical base would do) vs the `gate` decision (take/skip/veto + confidence + reason) and `gated_ok`.
  **This is the whole experiment — is the Claude gate ADDING value or subtracting?** For each event assess, with
  hindsight: did SKIPPED/vetoed events reverse (good skip) or drift (bad skip)? did TAKEN events drift (good) or
  reverse (bad)? Track gate hit-rate vs the mechanical base over time. Read the gate `reason` for calibration.
- `journal/event_drift_trades.jsonl`: fills (`sent` true/false), reaction/direction/units. `event_drift_equity.jsonl`:
  NAV/**financing** — since the book is flat overnight, **financing should be ≈0**; any nonzero financing delta
  means a position was held overnight (a bug — flag it).
- **Exposure watch (no aggregate cap by design):** positions **stack** across a multi-event day until the 20:00
  flatten. On busy data days, add up the day's entries and flag if peak notional approached/﻿exceeded NAV
  (~$11k) — at $1k/pair that's ~5+ concurrent events; unlikely but watch it.
- **Cross-check** open positions vs intent: `python3 event_drift_trader.py --mode live --audit`. Confirm all flat
  after 20:00 UTC.
- **Known gaps to keep raising:** USD-HIGH data releases only (pairs' own-currency events untested); **FOMC** is
  vetoed by design (naive-follow reverses there) pending the **Flavor-B presser manager**; speeches excluded.

**Live-broker position cross-check (run once; covers all 3 IBKR bots — they share acct U2417906):** query
IBKR directly and compare to every bot's state/journal. Catches positions closed **externally/manually** that
log-based checks miss (the 2026-07-01 soxl stale-71 desync). Read-only, unique clientId so it won't disturb
running bots:
```python
from ib_async import IB
ib = IB(); ib.connect("127.0.0.1", 4001, clientId=88, timeout=20)   # 4001 = live gateway
print({r.tag: r.value for r in ib.accountSummary() if r.tag in ("NetLiquidation","TotalCashValue","GrossPositionValue")})
for p in ib.positions(): print(p.contract.symbol, p.position, p.avgCost)
ib.disconnect()
```
Then flag any mismatch: a state file / journal claiming a position the account doesn't hold (or vice-versa).

**Anomaly checks (the valuable part — DIAGNOSE, don't just list):** skip floods · state↔IBKR desync (use the
live cross-check above, not just logs) · connection errors · **dead/stalled bot — use PROCESS liveness, not log
freshness** (the IBKR bots sleep between sessions, so a stale log is normal; a missing *process* is the fault — run
`trading_common/bot_watchdog.py`, or `pgrep -af "--mode live"`) · stops fired / whipsaw · positions
underwater · mega-cap catalysts that didn't react · fill-vs-limit gaps.

**Weak-trade post-mortem (the learning loop):** for every **losing or near-flat** closed trade — and
any same-day **fade** (popped, then gave it back) — do a quick post-mortem: *why* did it underperform?
Candidates: mega-cap non-reaction · anticipated / priced-in · label-expansion vs new approval ·
"sell the news" · late or bad entry · wrong catalyst type · whipsaw. Then suggest **one concrete
improvement** (a prompt tweak, a new filter/guard, a threshold) as a **review note for future
iteration**, and flag any pattern that recurs across days. Winners need no post-mortem — focus the
effort on what didn't work. This is *review*, not action.

**★ Continuous improvement (MANDATORY — never skip this, even on a quiet day).** The point of this review
is not just to catch breakage but to make the bots **better over time**. ALWAYS end with a short
**"Ideas to do better"** section — concrete, specific, and prioritized (most valuable first). Actively
think about what would move the needle; do not wait to be asked. Draw from, at minimum:
- **New data sources / feeds** — e.g. a structured economic-calendar feed with lower latency than the
  FXStreet/ForexFactory scrape (Finnhub/FMP free tier) for the event-drift bot; each pair's own-currency events
  (BOE→GBP etc.) beyond USD-HIGH; a better/broader news feed; alternative sentiment inputs; a practice-account
  token for safe FX shakeouts.
- **New signals / strategies / filters** — a candidate factor, a guard for a recurring loss pattern, a
  per-strategy threshold, a cross-bot regime signal; **Flavor-B FOMC-presser manager** (the event-drift bot vetoes
  FOMC today — the step-by-step presser reasoning is the planned unlock); more pairs/events once validated.
- **Prompt / model tuning** — where Claude over- or under-filters (materiality, mega-cap, confidence
  calibration); **tune the event-drift GATE prompt against its base-vs-gated counterfactual** (is it skipping
  winners / taking reversers?); reuse what works in one bot for another.
- **Risk & sizing** — capacity/leverage, correlation/concentration caps, kill-switch thresholds, the
  shared-buying-power constraint across the IBKR bots.
- **Observability / infra** — logging gaps, reconciliation blind spots, alerting, stale-process detection,
  automating a manual step.
Tie each idea to something SEEN in the data where possible (a loss, a skip, a miss, a gap), give a one-line
rationale + rough effort, and **flag recurring themes across days** (if the same idea recurs, escalate it).
These are proposals for future iteration — surface them proactively, but this is *review*: implement nothing
without my OK.

If something needs a fix, say so and propose it — but **do not change live trading code, configs, prompts,
or state files without my explicit OK.** Detection is yours; remediation is mine to approve.
