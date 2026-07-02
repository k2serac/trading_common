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

Alert de-duplication (so a persistent outage doesn't spam every run): each
distinct problem is alerted ONCE when it appears, RE-reminded every
--remind-hours (default 6) while it persists, and an all-clear "recovered" is
sent when it clears. State is kept in logs/watchdog_state.json.

Sends Telegram + non-zero exit while unhealthy; quiet + exit 0 when all up.

Cron example (every 15 min):
    */15 * * * * /usr/miniconda3/bin/python3 /home/nicu/work/repos/trading_common/bot_watchdog.py
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPOS = Path("/home/nicu/work/repos")
_STATE = HERE / "logs" / "watchdog_state.json"

# name -> {script substring, optional fx-style heartbeat state file}
BOTS = {
    "us_news_stock_bot":      {"script": "daytrader.py"},
    "soxl_index_bot":         {"script": "soxl_trader.py"},
    "commodity_breakout_bot": {"script": "commodity_trader.py"},
    # fx_macro_bot repo now runs the event-drift bot (COT trader retired as fallback)
    "fx_macro_bot":           {"script": "event_drift_trader.py",
                               "state": REPOS / "fx_macro_bot/journal/event_drift_state.json"},
    # P&L Telegram service — a utility daemon, no --mode live flag
    "telegram_pnl_bot":       {"script": "telegram_pnl_bot.py", "require_mode_live": False},
}
_ONESHOT = ("--audit", "--dry-run", "--once")


def _cmdlines() -> list[str]:
    r = subprocess.run(["pgrep", "-af", "python"], capture_output=True, text=True)
    return r.stdout.splitlines()


def _is_running(script: str, lines: list[str], require_live: bool = True) -> bool:
    """Running = a python cmdline with the script, not a one-shot run. Trading bots
    also require '--mode live'; utility daemons (require_live=False) just need the script."""
    for ln in lines:
        if script in ln and not any(f in ln for f in _ONESHOT) and (not require_live or "--mode live" in ln):
            return True
    return False


def _fx_depth_check(state_path: Path, max_age_min: int) -> list[tuple[str, str]]:
    """fx-only: halted flag + heartbeat staleness. Returns (code, message) pairs;
    the code is STABLE (no varying numbers) so de-dup keys don't churn."""
    issues: list[tuple[str, str]] = []
    if not state_path.is_file():
        return issues
    try:
        st = json.loads(state_path.read_text())
    except Exception as exc:
        return [("fx_macro_bot:state_unreadable", f"fx_macro_bot: cannot read state ({exc})")]
    if st.get("halted"):
        issues.append(("fx_macro_bot:halted",
                       "fx_macro_bot: KILL SWITCH tripped (halted) — flat + halted, manual restart needed."))
    last = st.get("last_cycle_utc")
    if last:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 60
        if age > max_age_min:
            issues.append(("fx_macro_bot:heartbeat_stale",
                           f"fx_macro_bot: heartbeat stale — no cycle in {age:.0f} min (alive but hung?)."))
    return issues


def _check_all(fx_max_age_min: int, only: str | None) -> list[tuple[str, str]]:
    lines = _cmdlines()
    issues: list[tuple[str, str]] = []
    for name, cfg in BOTS.items():
        if only and name != only:
            continue
        if not _is_running(cfg["script"], lines, cfg.get("require_mode_live", True)):
            issues.append((f"{name}:down", f"{name}: NOT RUNNING (no process for {cfg['script']})."))
            continue                                     # if down, skip deeper checks
        if "state" in cfg:
            issues += _fx_depth_check(cfg["state"], fx_max_age_min)
    return issues


def _load_state() -> dict:
    if _STATE.is_file():
        try:
            return json.loads(_STATE.read_text())
        except Exception:
            pass
    return {"alerted": {}}          # code -> last-alert ISO timestamp


def _save_state(state: dict) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(json.dumps(state, indent=2))


def _load_telegram_env() -> None:
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
    ap.add_argument("--remind-hours", type=float, default=6.0,
                    help="re-alert an ongoing problem every N hours (default 6)")
    ap.add_argument("--only", help="check a single bot by name")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    issues = _check_all(args.fx_max_age_min, args.only)
    cur = {code: msg for code, msg in issues}

    state = _load_state()
    alerted: dict = state.get("alerted", {})

    # New problems (never alerted) or ones due for a re-reminder.
    remind_secs = args.remind_hours * 3600
    to_alert = []
    for code, msg in cur.items():
        last = alerted.get(code)
        due = last is None or (now - datetime.fromisoformat(last)).total_seconds() >= remind_secs
        if due:
            to_alert.append(msg)
            alerted[code] = now.isoformat()

    # Recovered problems (were alerted, no longer present).
    recovered = [code for code in list(alerted) if code not in cur]
    for code in recovered:
        alerted.pop(code, None)

    _load_telegram_env()
    if to_alert:
        _notify("⚠️ " + " | ".join(to_alert))
    if recovered:
        _notify("✅ recovered: " + ", ".join(recovered))

    state["alerted"] = alerted
    _save_state(state)

    if issues:
        print(f"UNHEALTHY: {', '.join(cur)}", file=sys.stderr)
        return 1
    print("ok — all up" + ("" if not recovered else f" (recovered: {', '.join(recovered)})"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
