#!/usr/bin/env python3
"""bot_watchdog.py — external liveness watchdog for ALL trading bots.

The bots can't reliably alert their own death, so run this periodically (cron) to
catch a crashed/stopped process. It is PROCESS-based, not log-based: the IBKR bots
are sleep-heavy (e.g. "Sleeping 19.8h" overnight/weekends is normal), so a stale
log is NOT a fault — a missing PROCESS is. Touches no bot code.

Checks, per bot:
  - is a live daemon running?  (pgrep for the script + "--mode live", excluding
    one-shot --audit/--dry-run/--once invocations)  -> alert if missing.
  - fx_macro_bot extra depth-check: read journal/fx_state.json — alert if the
    kill switch tripped (halted) or the heartbeat (last_cycle_utc) is stale
    (process alive but hung). Skipped gracefully if that state isn't present.

Sends ONE Telegram summary of all problems (+ non-zero exit) when unhealthy;
quiet + exit 0 when all bots are up.

Cron example (every 15 min):
    */15 * * * * cd /home/nicu/work/repos/trading_common && /usr/bin/python3 bot_watchdog.py
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPOS = Path("/home/nicu/work/repos")

# name -> {script substring, optional fx-style heartbeat state file}
BOTS = {
    "us_news_stock_bot":      {"script": "daytrader.py"},
    "soxl_index_bot":         {"script": "soxl_trader.py"},
    "commodity_breakout_bot": {"script": "commodity_trader.py"},
    "fx_macro_bot":           {"script": "fx_macro_trader.py",
                               "state": REPOS / "fx_macro_bot/journal/fx_state.json"},
}
_ONESHOT = ("--audit", "--dry-run", "--once")


def _cmdlines() -> list[str]:
    r = subprocess.run(["pgrep", "-af", "python"], capture_output=True, text=True)
    return r.stdout.splitlines()


def _is_running(script: str, lines: list[str]) -> bool:
    """A live daemon = a python cmdline with the script + --mode live, and NOT a
    one-shot audit/dry-run/once run."""
    for ln in lines:
        if script in ln and "--mode live" in ln and not any(f in ln for f in _ONESHOT):
            return True
    return False


def _fx_depth_check(state_path: Path, max_age_min: int) -> list[str]:
    """fx-only: halted flag + heartbeat staleness (alive-but-hung)."""
    issues: list[str] = []
    if not state_path.is_file():
        return issues                                    # nothing to check yet
    try:
        st = json.loads(state_path.read_text())
    except Exception as exc:
        return [f"fx_macro_bot: cannot read state ({exc})"]
    if st.get("halted"):
        issues.append("fx_macro_bot: KILL SWITCH tripped (halted) — flat + halted, manual restart needed.")
    last = st.get("last_cycle_utc")
    if last:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 60
        if age > max_age_min:
            issues.append(f"fx_macro_bot: heartbeat stale — no cycle in {age:.0f} min (alive but hung?).")
    return issues


def _load_telegram_env() -> None:
    """Pull Telegram creds from the first bot .env.launcher that has them."""
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        return
    for name in BOTS:
        p = REPOS / name / ".env.launcher"
        if p.is_file():
            try:
                env = json.loads(p.read_text())
            except Exception:
                continue
            if env.get("TELEGRAM_BOT_TOKEN"):
                for k, v in env.items():
                    os.environ.setdefault(k, str(v))
                return


def _notify(msg: str) -> None:
    print(msg, file=sys.stderr)
    try:
        from trading_common import TelegramNotifier
        if os.environ.get("TELEGRAM_ENABLED", "").lower() == "true":
            TelegramNotifier().send(f"[bot-watchdog] {msg}")
    except Exception as exc:
        print(f"(telegram notify failed: {exc})", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fx-max-age-min", type=int, default=90,
                    help="fx heartbeat staleness threshold in minutes (default 90)")
    ap.add_argument("--only", help="check a single bot by name")
    args = ap.parse_args()

    lines = _cmdlines()
    issues: list[str] = []
    checked = []
    for name, cfg in BOTS.items():
        if args.only and name != args.only:
            continue
        checked.append(name)
        if not _is_running(cfg["script"], lines):
            issues.append(f"{name}: NOT RUNNING (no live daemon for {cfg['script']}).")
            continue
        if "state" in cfg:
            issues += _fx_depth_check(cfg["state"], args.fx_max_age_min)

    if issues:
        _load_telegram_env()
        _notify("⚠️ " + " | ".join(issues))
        return 1
    print(f"ok — all up: {', '.join(checked)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
