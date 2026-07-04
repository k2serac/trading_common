# If We'd Built This Without AI — The Team-Equivalent (a fun aside)

> A back-of-envelope answer to: *"Based on everything we built here from scratch, without AI help,
> how large a team should this have been, and what would each person do?"* — 2026-07-03.

What's assembled across these repos isn't "some scripts" — it's a **small multi-asset systematic
trading shop**: live equities (SOXL regime/momentum + news catalyst), commodities, FX, a shared
execution/data library, a launcher GUI, a research pipeline (backtests, exit-timing / factor studies,
ML logging), and the risk/ops scaffolding (regime gates, journaling, reconciliation, alerting).
Traditionally that's a team, not a person.

## How you'd staff it (mapped to the actual artifacts)

| Role | Heads | What they'd own here |
|---|---|---|
| **PM / Head of trading** *(you)* | 1 | Capital allocation, go/no-go calls, the "this is beta not alpha — kill it" judgment, domain thesis. The seat that can't be delegated. |
| **Quant researcher — equities** | 1–2 | SOXL regime/momentum strategies, us_news catalyst, S9 cross-sectional momentum, exit-timing study, factor set + IC/regression roadmap. |
| **Quant researcher — cross-asset** | 1 | Commodities (dormancy breakout) + FX (event-drift, COT). Different data, microstructure, and seasonality — genuinely a separate skill set. |
| **Trading-systems engineer** | 1–2 | `trading_common`, IBKR/OANDA connectors, bracket/OMS, `OpenTradeRegistry`, restart-idempotency, the state-desync self-heal, stops/brackets. |
| **Data engineer** | 1 | Polygon/Finnhub/yfinance/Benzinga-Massive ingestion, the EDGAR 10-K peer pipeline, caching, the ET/UTC timestamp correctness that bit us. |
| **ML / NLP engineer** | 1 | Claude sentiment gates, prompt engineering + the critique loop, `ml_feature_logging` / `factor_report`, mega-cap materiality guards. |
| **DevOps / SRE** | 0.5–1 | `bot_launcher_gui`, deployment, monitoring, Telegram alerting, logging, credit-exhaustion shutdown, "is it actually running at 9:35 ET." |
| **Risk + trade-ops** | 0.5–1 | Regime gates, position sizing, drawdown controls, the fund-level risk-parity layer, `reconcile_pnl.py` / journaling QA. Often the PM's second hat early on. |

## Bottom line

**~6–8 people including you** — realistically a founder-PM plus a lean 5-team (one systems eng, one
data eng, one ML/NLP, and two researchers split equities vs commodities/FX), stretching toward 8 if
you want real depth per asset class, proper risk separation, and enough redundancy that one person on
vacation doesn't stop the bots trading.

## The honest footnote

The AI collapsed the **six technical/execution seats** — it wrote the connectors, the backtests, the
docs, the memory-tracking refactor. What it did *not* replace is the **top row**: the capital, the
accountability, and the judgment calls (Micron/Synopsys → *"the multi-day edge is beta, park it"*).
Those stayed with the human the entire time — which is exactly the right seat for the human to keep.

So: an 8-person shop, minus 6 engineers, plus a very fast intern who never sleeps and occasionally
hallucinates an API. 🙂
