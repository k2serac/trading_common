"""
journal_lib.py — Shared trading journal infrastructure.

OpenTradeRegistry — Persistent registry of open trades that survives bot restarts.
TradingJournal    — Appends structured events to a daily JSON file as they happen.
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal

logger = logging.getLogger(__name__)

MARKET_TZ = ZoneInfo("America/New_York")



# ---------------------------------------------------------------------------
# TradingJournal
# ---------------------------------------------------------------------------

class OpenTradeRegistry:
    """Persistent registry of open trades that survives bot restarts.

    Stored in ``journal/open_trades.json`` — entries remain until explicitly
    closed so the bot can recover strategy, order ref, and sizing for positions
    that were opened in a prior session.
    """

    def __init__(self, path: str = "journal/open_trades.json") -> None:
        self._path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._entries: list[dict] = self._load()
        logger.info(
            "Open trade registry loaded: %d entry(ies) from %s",
            len(self._entries), path,
        )

    def _load(self) -> list[dict]:
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception as exc:
                logger.error("Failed to load open trade registry: %s", exc)
        return []

    def _save(self) -> None:
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(self._entries, fh, indent=2, default=str)

    def add(
        self,
        symbol: str,
        order_ref: str,
        strategy: str,
        quantity: int,
        limit_price: float | None,
        order_id: int = 0,
        perm_id: int = 0,
    ) -> None:
        """Register a newly placed order."""
        self._entries.append({
            "symbol": symbol,
            "order_ref": order_ref,
            "strategy": strategy,
            "quantity": quantity,
            "limit_price": limit_price,
            "order_id": order_id,
            "perm_id": perm_id,
            "status": "pending",
            "opened_at": datetime.now(MARKET_TZ).isoformat(),
            "fill_price": None,
            "sell_price": None,
            "closed_at": None,
        })
        self._save()
        logger.info("Registry: added %s (order_ref=%s)", symbol, order_ref)

    def update_perm_id(self, order_ref: str, perm_id: int) -> None:
        """Update the permId for an entry once TWS assigns it."""
        for entry in self._entries:
            if entry["order_ref"] == order_ref and not entry.get("perm_id"):
                entry["perm_id"] = perm_id
                self._save()
                logger.info(
                    "Registry: updated permId=%d for %s", perm_id, entry["symbol"]
                )
                return

    def sync_perm_ids(self, open_trades: list) -> None:
        """Update permIds for pending entries from the current session's open trades."""
        for t in open_trades:
            ref = getattr(t.order, "orderRef", "") or ""
            perm_id = getattr(t.order, "permId", 0) or 0
            if ref and perm_id:
                self.update_perm_id(ref, perm_id)

    def mark_closed(
        self,
        symbol: str,
        sell_price: float | None = None,
        fill_price: float | None = None,
    ) -> bool:
        """Mark the most recent open entry for symbol as closed.

        Returns ``True`` if an open entry was found and flipped to closed, or
        ``False`` if there was nothing open to close (already closed). Callers
        use the return value to journal a close exactly once even when the
        closing order fills in several partial executions — only the execution
        that actually flips the position closed returns ``True``.
        """
        for entry in reversed(self._entries):
            if entry["symbol"] == symbol and entry["status"] in ("pending", "filled"):
                entry["status"] = "closed"
                entry["sell_price"] = sell_price
                if fill_price is not None:
                    entry["fill_price"] = fill_price
                entry["closed_at"] = datetime.now(MARKET_TZ).isoformat()
                self._save()
                logger.info("Registry: marked %s as closed (fill=%.4f sell=%.4f)",
                            symbol, fill_price or 0, sell_price or 0)
                return True
        return False

    def mark_filled(
        self,
        symbol: str,
        fill_price: float,
        fill_time: str | None = None,
    ) -> None:
        """Mark the most recent pending entry for symbol as filled with the actual execution price."""
        for entry in reversed(self._entries):
            if entry["symbol"] == symbol and entry["status"] == "pending":
                entry["status"] = "filled"
                entry["fill_price"] = fill_price
                if fill_time:
                    entry["opened_at"] = fill_time
                self._save()
                logger.info("Registry: marked %s as filled @ %.4f", symbol, fill_price)
                return

    def mark_cancelled(self, symbol: str) -> None:
        """Mark the most recent pending entry for symbol as cancelled (unfilled at close)."""
        for entry in reversed(self._entries):
            if entry["symbol"] == symbol and entry["status"] == "pending":
                entry["status"] = "cancelled"
                entry["closed_at"] = datetime.now(MARKET_TZ).isoformat()
                self._save()
                logger.info("Registry: marked %s as cancelled (unfilled)", symbol)
                return

    def get_open(self, symbol: str) -> dict | None:
        """Return the most recent non-closed entry for symbol, or None."""
        for entry in reversed(self._entries):
            if entry["symbol"] == symbol and entry["status"] in ("pending", "filled"):
                return entry
        return None

    def get_all_open(self) -> list[dict]:
        """Return all non-closed entries."""
        return [e for e in self._entries if e["status"] in ("pending", "filled")]


class TradingJournal:
    """Logs all trading activity for the current day to a JSON file.

    Events are flushed to disk after every write so data is preserved
    even if the process crashes mid-session.

    Args:
        journal_dir: Directory where ``YYYY-MM-DD.json`` files are written
                     (default ``"journal/daytrader"``).
    """

    def __init__(self, journal_dir: str = "journal/daytrader") -> None:
        self.journal_dir = journal_dir
        self._nyse = mcal.get_calendar("NYSE")
        os.makedirs(journal_dir, exist_ok=True)

        self._session_date = self._get_session_date()
        self._path = os.path.join(journal_dir, f"{self._session_date}.json")
        self._data = self._load_or_create()

        # Persistent dedup set — survives journal rollovers within one bot run
        # so the same headline is never re-evaluated after a session file changes.
        self._sentiment_seen: set[str] = {
            hashlib.md5(f"{e['title']}{e['strategy']}{e['symbol']}".encode()).hexdigest()
            for e in self._data.get("sentiment_decisions", [])
        }
        # Per-session skip dedup — the live loop re-evaluates pending symbols every
        # poll and would otherwise re-log the same (symbol, reason) hundreds of times
        # per session (e.g. liquidity / conflicting-signal skips). Log each once.
        self._skipped_seen: set[str] = {
            f"{e.get('symbol')}|{e.get('reason')}" for e in self._data.get("trades_skipped", [])
        }
        logger.info("Trading journal opened: %s", self._path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_session_date(self) -> str:
        """Return the date string for the current or next NYSE trading session.

        Rules:
        - Today is a trading day and market has not yet closed → today's date.
        - Today is a trading day but market has closed, or today is not a
          trading day → date of the next trading session.

        Examples:
            - Sunday  any time  → Monday's date
            - Monday  8 AM      → Monday's date  (pre-market, session not over)
            - Monday  5 PM      → Tuesday's date (after close)
            - Friday  5 PM      → Monday's date  (skips weekend)
        """
        now = datetime.now(MARKET_TZ)
        today_str = now.strftime("%Y-%m-%d")

        # Check if today has a session and it hasn't ended yet
        try:
            schedule = self._nyse.schedule(start_date=today_str, end_date=today_str)
            if not schedule.empty:
                market_close = (
                    schedule.iloc[0]["market_close"]
                    .to_pydatetime()
                    .astimezone(MARKET_TZ)
                )
                if now <= market_close:
                    return today_str
        except Exception:
            pass

        # Find the next trading day (look ahead up to 7 days)
        for offset in range(1, 8):
            candidate = now + timedelta(days=offset)
            candidate_str = candidate.strftime("%Y-%m-%d")
            try:
                schedule = self._nyse.schedule(
                    start_date=candidate_str, end_date=candidate_str
                )
                if not schedule.empty:
                    return candidate_str
            except Exception:
                continue

        return today_str  # fallback

    def _check_rollover(self) -> None:
        """Roll over to a new file when the target trading session changes.

        Called at the top of every log method so the journal always writes
        to the correct session's file even when the bot runs continuously
        across multiple days.
        """
        session_date = self._get_session_date()
        if session_date != self._session_date:
            logger.info(
                "Journal session rollover: %s → %s. Starting new journal file.",
                self._session_date, session_date,
            )
            # Check if the bot has an open session in the old journal before switching
            had_open_session = any(
                s.get("stop") is None for s in self._data.get("bot_sessions", [])
            )
            self._session_date = session_date
            self._path = os.path.join(self.journal_dir, f"{self._session_date}.json")
            self._data = self._load_or_create()
            # Reset per-session skip dedup for the new journal file
            self._skipped_seen = {
                f"{e.get('symbol')}|{e.get('reason')}" for e in self._data.get("trades_skipped", [])
            }
            # Carry the running session forward so the new journal knows the bot
            # was already running when this session started (multi-day runs)
            if had_open_session:
                now = datetime.now(MARKET_TZ).isoformat()
                self._data.setdefault("bot_sessions", []).append({"start": now, "stop": None})
                self._save()

    def _load_or_create(self) -> dict:
        """Load the session's journal from disk, or start a fresh one."""
        if os.path.exists(self._path):
            with open(self._path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        return {
            "date": self._session_date,
            "bot_sessions": [],        # [{start, stop}] — running periods; stop is null if still running
            "news_fetched": [],        # every raw headline from Benzinga
            "news_matched": [],        # headlines that passed regex
            "sentiment_decisions": [], # Claude yes/no for every matched headline
            "orders_placed": [],       # limit/market orders sent to IBKR
            "positions_closed": [],    # close orders sent to IBKR, with buy/sell prices and PnL
            "trades_skipped": [],      # trades blocked by a risk limit
            "strategy_pnl": {},        # per-strategy PnL summary (updated on every close)
        }

    def _save(self) -> None:
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, default=str)

    # ------------------------------------------------------------------
    # Public logging methods
    # ------------------------------------------------------------------

    def log_bot_start(self) -> None:
        """Record the bot start time, opening a new session entry."""
        self._check_rollover()
        now = datetime.now(MARKET_TZ).isoformat()
        self._data.setdefault("bot_sessions", []).append({"start": now, "stop": None})
        self._save()
        logger.info("Journal: bot session started at %s.", now)

    def log_bot_stop(self) -> None:
        """Stamp the stop time on the most recent open session entry."""
        self._check_rollover()
        now = datetime.now(MARKET_TZ).isoformat()
        sessions = self._data.setdefault("bot_sessions", [])
        # Find the last entry that has no stop time and close it
        for entry in reversed(sessions):
            if entry.get("stop") is None:
                entry["stop"] = now
                break
        self._save()
        logger.info("Journal: bot session stopped at %s.", now)

    def log_news_fetched(self, news_df: pd.DataFrame) -> None:
        """Record all raw headlines returned by the news provider.

        Duplicate entries (same title + timestamp) are silently skipped
        so repeated loop iterations don't inflate the log.
        """
        self._check_rollover()
        if news_df is None or news_df.empty:
            return

        existing = {
            hashlib.md5(e["title"].encode()).hexdigest()
            for e in self._data["news_fetched"]
        }
        added = 0
        for _, row in news_df.iterrows():
            title = str(row.get("title", ""))
            key = hashlib.md5(title.encode()).hexdigest()
            if key in existing:
                continue
            self._data["news_fetched"].append({
                "title": title,
                "symbols": str(row.get("symbols", "")),
                "updated": str(row.get("updated", "")),
            })
            existing.add(key)
            added += 1

        if added:
            self._save()
            logger.debug("Journal: logged %d new headline(s).", added)

    def log_news_matched(
        self,
        symbol: str,
        title: str,
        body: str,
        strategy: str,
        pattern: str,
    ) -> None:
        """Record a headline that matched a regex pattern."""
        self._check_rollover()
        self._data["news_matched"].append({
            "timestamp": datetime.now(MARKET_TZ).isoformat(),
            "symbol": symbol,
            "title": title,
            "body": (body or "")[:500],  # truncate; full text is in news_fetched
            "strategy": strategy,
            "pattern": pattern,
        })
        self._save()

    def log_sentiment_decision(
        self,
        symbol: str,
        title: str,
        strategy: str,
        is_positive: bool,
        reason: str,
    ) -> None:
        """Record Claude's yes/no sentiment verdict for a headline.

        Both positive and negative decisions are logged so the end-of-day
        analysis can review false negatives.
        """
        self._check_rollover()
        key = hashlib.md5(f"{title}{strategy}{symbol}".encode()).hexdigest()
        if key in self._sentiment_seen:
            return
        self._sentiment_seen.add(key)
        self._data["sentiment_decisions"].append({
            "timestamp": datetime.now(MARKET_TZ).isoformat(),
            "symbol": symbol,
            "title": title,
            "strategy": strategy,
            "is_positive": is_positive,
            "reason": reason,
        })
        self._save()

    def log_order_placed(
        self,
        symbol: str,
        quantity: int,
        order_type: str,
        strategy: str,
        order_ref: str,
        limit_price: float | None = None,
        stop_price: float | None = None,
        features: dict | None = None,
    ) -> None:
        """Record an order successfully submitted to IBKR.

        ``features`` is an optional structured snapshot of the entry conditions
        (strategy, sector, gap, regime, sentiment confidence, time-of-day) for
        later ML/weekly-analysis use — purely additive, never affects trading.
        """
        self._check_rollover()
        self._data["orders_placed"].append({
            "timestamp": datetime.now(MARKET_TZ).isoformat(),
            "symbol": symbol,
            "quantity": quantity,
            "order_type": order_type,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "strategy": strategy,
            "order_ref": order_ref,
            "features": features or {},
        })
        self._save()

    def log_fill(
        self,
        symbol: str,
        fill_price: float,
        order_ref: str,
        fill_time: str | None = None,
    ) -> None:
        """Record an IBKR fill confirmation with the actual execution price."""
        self._check_rollover()
        self._data.setdefault("fills", []).append({
            "timestamp": fill_time or datetime.now(MARKET_TZ).isoformat(),
            "symbol": symbol,
            "fill_price": fill_price,
            "order_ref": order_ref,
        })
        self._save()

    def log_trade_skipped(
        self,
        symbol: str,
        strategy: str,
        reason: str,
        title: str = "",
        limit_name: str = "",
        limit_value: int = 0,
        current_count: int = 0,
    ) -> None:
        """Record a trade that was blocked because a risk-limit counter was full.

        Args:
            symbol:        Ticker that would have been traded.
            strategy:      ``TradeStrategy`` value for this candidate.
            reason:        Human-readable explanation of why the trade was skipped.
            limit_name:    Name of the breached limit (e.g. ``"MaxTradesPerTradingStrategy"``).
            limit_value:   The configured cap.
            current_count: Counter value at the time of the skip.
        """
        self._check_rollover()
        # Dedup: log each (symbol, reason) only once per session file.
        key = f"{symbol}|{reason}"
        if key in self._skipped_seen:
            return
        self._skipped_seen.add(key)
        self._data.setdefault("trades_skipped", []).append({
            "timestamp": datetime.now(MARKET_TZ).isoformat(),
            "symbol": symbol,
            "title": title,
            "strategy": strategy,
            "reason": reason,
            "limit_name": limit_name,
            "limit_value": limit_value,
            "current_count": current_count,
        })
        self._save()

    def log_position_closed(
        self,
        symbol: str,
        quantity: int,
        order_type: str,
        order_ref: str,
        strategy: str = "",
        buy_price: float | None = None,
        sell_price: float | None = None,
        limit_price: float | None = None,
    ) -> None:
        """Record a position close order submitted to IBKR.

        ``buy_price`` is the average fill cost from IBKR (``pos.avgCost``).
        ``sell_price`` is the limit price for limit closes, or the last known
        market price for market closes (approximate).
        ``pnl_pct`` is computed only when both prices are available.
        """
        self._check_rollover()
        pnl_pct: float | None = None
        if buy_price and sell_price and buy_price > 0:
            pnl_pct = round((sell_price - buy_price) / buy_price * 100, 2)

        self._data["positions_closed"].append({
            "timestamp": datetime.now(MARKET_TZ).isoformat(),
            "symbol": symbol,
            "quantity": quantity,
            "order_type": order_type,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "pnl_pct": pnl_pct,
            "limit_price": limit_price,
            "strategy": strategy,
            "order_ref": order_ref,
        })

        # Update per-strategy PnL summary
        if strategy and pnl_pct is not None:
            sp = self._data.setdefault("strategy_pnl", {})
            s = sp.setdefault(strategy, {
                "trades": 0, "wins": 0, "losses": 0,
                "total_pnl_pct": 0.0, "avg_pnl_pct": 0.0,
            })
            s["trades"] += 1
            if pnl_pct >= 0:
                s["wins"] += 1
            else:
                s["losses"] += 1
            s["total_pnl_pct"] = round(s["total_pnl_pct"] + pnl_pct, 2)
            s["avg_pnl_pct"] = round(s["total_pnl_pct"] / s["trades"], 2)
            logger.info(
                "Strategy PnL [%s] trade=%s pnl=%.2f%% | total=%.2f%% avg=%.2f%% (%d W / %d L)",
                strategy, symbol, pnl_pct,
                s["total_pnl_pct"], s["avg_pnl_pct"], s["wins"], s["losses"],
            )

        self._save()

