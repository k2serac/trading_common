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

**3. commodity_breakout_bot** — `/home/nicu/work/repos/commodity_breakout_bot`
- Today's scan + any orders/positions. Usually quiet by design — silence is normal, not a fault.

**4. fx_macro_bot** — `/home/nicu/work/repos/fx_macro_bot` (`fx_macro_trader.py`)
- **FORWARD TEST, tiny real money** (OANDA acct 001-001-5457117-001, ~$2k gross of ~$11k NAV — SEPARATE
  from the IBKR account the other three share). Base = weekly COT-positioning; overlay = Claude
  central-bank regime-VETO. Thin/unproven by design — the point of the daily check is to accumulate the
  forward-validation record and catch breakage, not to expect P&L yet.
- **Liveness first:** is the process running? It polls hourly and rebalances weekly (on a new COT week),
  so most days = "no new COT week, no trade" (normal). Check the newest log's timestamp for freshness;
  a stalled process is the main silent failure.
- `journal/fx_state.json`: `last_rebalance_week`, active `vetoes`, `nav_hwm`, and **`halted`** — if
  `halted: true` the **kill switch tripped** (NAV fell >25% below HWM); flatten+halt fired and it needs a
  manual restart. That is the #1 anomaly to surface.
- `journal/counterfactual.jsonl` (the forward record): latest `rebalance` (asof_week, weights,
  base_units vs applied_units, active_vetoes, NAV) and any `veto_eval` (regime_change / action /
  confidence / reason). **On FOMC/ECB days**, report whether Claude fired a veto and, later, whether it
  was right (did the flattened ccy keep moving against us?). **Base-vs-overlay attribution** is the whole
  experiment — is the veto adding or subtracting?
- `journal/trades.jsonl`: fills (`sent` true/false), reconcile deltas. Cross-check OANDA positions vs the
  base target (run `python3 fx_macro_trader.py --mode live --audit`) — flag any drift beyond the deadband.
- **Known v2 gaps to keep raising:** overlay only triggers on FOMC/ECB — it MISSES BOE/BOJ/RBA/RBNZ/BOC/SNB
  and all unscheduled shocks (e.g. an emergency cut), which recall analysis showed is the binding risk.
  Flag any such event that occurred and was NOT assessed.

**Anomaly checks (the valuable part — DIAGNOSE, don't just list):** skip floods · state↔IBKR desync ·
connection errors · **dead/stalled bot — use PROCESS liveness, not log freshness** (the IBKR bots sleep
between sessions, so a stale log is normal; a missing *process* is the fault — run
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
- **New data sources / feeds** — e.g. a real-time macro feed for the FX overlay v2 (BOE/BOJ/RBA/RBNZ/BOC/SNB
  + unscheduled shocks); a better/broader news feed or CB calendar; alternative sentiment inputs; funding/
  swap data; options-implied vol for regime detection; a practice-account token for safe FX shakeouts.
- **New signals / strategies / filters** — a candidate factor, a guard for a recurring loss pattern, a
  per-strategy threshold, a cross-bot regime signal.
- **Prompt / model tuning** — where Claude over- or under-filters (materiality, mega-cap, confidence
  calibration), reusing what works in one bot for another.
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
