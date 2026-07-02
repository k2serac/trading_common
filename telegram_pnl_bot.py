#!/usr/bin/env python3
"""telegram_pnl_bot.py — reply to "pnl" in Telegram with live account P&L.

Motivation: checking P&L by logging into TWS from another machine kills the IBKR
gateway here (single session). Instead, message the Telegram bot "pnl" (or
"balance"/"positions") and it queries the accounts READ-ONLY and replies with:
balance/NAV, day P&L, and each open position's unrealized $ and % gain/loss.

Covers IBKR (the 3 stock bots, shared acct) via ib_async, and OANDA (the FX bot)
via its REST API. Both best-effort — one failing doesn't block the other.
Only responds to the authorized TELEGRAM_CHAT_ID. Read-only (no orders).

Run:  python3 telegram_pnl_bot.py     (long-running; creds from a bot .env.launcher)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

REPOS = Path("/home/nicu/work/repos")
IBKR_HOST, IBKR_PORT, IBKR_CLIENT = "127.0.0.1", 4001, 77
TRIGGERS = {"pnl", "/pnl", "balance", "bal", "positions", "status", "/status"}


def load_env() -> None:
    """Pull TELEGRAM_* and OANDA_* from the first bot .env.launcher that has them."""
    for name in ("us_news_stock_bot", "fx_macro_bot", "soxl_index_bot", "commodity_breakout_bot"):
        p = REPOS / name / ".env.launcher"
        if p.is_file():
            try:
                env = json.loads(p.read_text())
            except Exception:
                continue
            for k, v in env.items():
                os.environ.setdefault(k, str(v))


def _tg(method: str, **params):
    tok = os.environ["TELEGRAM_BOT_TOKEN"]
    return requests.get(f"https://api.telegram.org/bot{tok}/{method}", params=params, timeout=40)


def _send(text: str) -> None:
    _tg("sendMessage", chat_id=os.environ["TELEGRAM_CHAT_ID"], text=text)


def ibkr_report() -> str:
    from ib_async import IB
    ib = IB()
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT, timeout=20)
    except Exception as exc:
        return f"IBKR: unavailable ({type(exc).__name__}) — gateway down or logged in elsewhere?"
    try:
        s = {r.tag: r.value for r in ib.accountSummary()}
        nav = float(s.get("NetLiquidation", 0) or 0)
        cash = float(s.get("TotalCashValue", 0) or 0)
        daily = None
        try:
            acct = (ib.managedAccounts() or [""])[0]
            pnl = ib.reqPnL(acct); ib.sleep(2.0)
            daily = pnl.dailyPnL if pnl and pnl.dailyPnL == pnl.dailyPnL else None  # NaN check
        except Exception:
            pass
        lines = [f"📊 IBKR  NAV ${nav:,.0f}  cash ${cash:,.0f}"
                 + (f"  dayP&L ${daily:+,.0f}" if daily is not None else "")]
        port = [it for it in ib.portfolio() if it.position]
        if not port:
            lines.append("  (flat — no open positions)")
        for it in sorted(port, key=lambda x: (x.unrealizedPNL or 0)):
            cost = (it.averageCost or 0) * abs(it.position)
            pct = (it.unrealizedPNL / cost * 100) if cost else 0.0
            lines.append(f"  {it.contract.symbol:6} {it.position:+.0f} | "
                         f"{it.unrealizedPNL:+,.0f} ({pct:+.1f}%)")
        return "\n".join(lines)
    finally:
        ib.disconnect()


def oanda_report() -> str:
    tok = os.environ.get("OANDA_API_TOKEN"); acct = os.environ.get("OANDA_ACCOUNT_ID")
    if not tok or not acct:
        return ""
    h = {"Authorization": f"Bearer {tok}"}
    base = "https://api-fxtrade.oanda.com/v3/accounts/" + acct
    try:
        a = requests.get(base + "/summary", headers=h, timeout=20).json().get("account", {})
        pos = requests.get(base + "/openPositions", headers=h, timeout=20).json().get("positions", [])
    except Exception as exc:
        return f"OANDA: unavailable ({type(exc).__name__})"
    nav = float(a.get("NAV", 0) or 0); upl = float(a.get("unrealizedPL", 0) or 0)
    lines = [f"💱 OANDA  NAV ${nav:,.0f}  unrealized ${upl:+,.0f}"]
    if not pos:
        lines.append("  (flat — no open positions)")
    for p in pos:
        side = p["long"] if float(p["long"]["units"]) != 0 else p["short"]
        units = float(side["units"]); avg = float(side.get("averagePrice", 0) or 0)
        pl = float(p.get("unrealizedPL", 0) or 0)
        basis = abs(units) * avg if avg else 0
        pct = (pl / basis * 100) if basis else 0.0
        lines.append(f"  {p['instrument']:8} {units:+.0f} | {pl:+,.0f} ({pct:+.2f}%)")
    return "\n".join(lines)


def build_report() -> str:
    parts = []
    try:
        parts.append(ibkr_report())
    except Exception as exc:
        parts.append(f"IBKR: error ({exc})")
    o = oanda_report()
    if o:
        parts.append(o)
    return "\n\n".join(parts) or "no accounts reachable"


def main() -> int:
    load_env()
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        if not os.environ.get(k):
            raise EnvironmentError(f"{k} not found in any .env.launcher")
    chat_id = str(os.environ["TELEGRAM_CHAT_ID"])
    _send("✅ P&L bot online — send 'pnl' anytime for balance + open positions.")
    offset = None
    while True:
        try:
            r = _tg("getUpdates", timeout=30, offset=offset)
            for u in r.json().get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or u.get("edited_message") or {}
                if str((msg.get("chat") or {}).get("id", "")) != chat_id:
                    continue                                   # authorized chat only
                text = (msg.get("text") or "").strip().lower()
                if text in TRIGGERS:
                    _send(build_report())
        except Exception as exc:
            print(f"loop error: {exc}"); time.sleep(5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
