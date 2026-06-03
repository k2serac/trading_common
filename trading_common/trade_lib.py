"""
trade_lib.py — Core trading library for the US Stock Trader bot.

Provides six main components:

  TradeHour          — NYSE market-status detection (RTH / extended / closed).
  Obb                — News ingestion via OpenBB + Benzinga, with dedup checksums.
  BenzingaWebSocket  — Real-time streaming via the Benzinga WebSocket API.
  ClaudeSentiment    — Headline sentiment scoring via the Anthropic Claude API.
  IBapi              — Thin wrapper around ib_async for order and position management.
  TradeManager       — Orchestrates the full news-to-trade pipeline.
  TradeUtils         — Shared numeric helpers.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import numbers
import os
import re
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal
import pytz

import websocket

import anthropic
from ib_async import IB, LimitOrder, MarketOrder, Stock, StopLimitOrder, StopOrder
from openbb import obb

# ---------------------------------------------------------------------------
# Module-level logger — callers configure handlers/level via logging.basicConfig
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

_STALE_NEWS_PREFIXES = re.compile(
    r"^(reported\s+earlier|previously\s+reported|breaking\s+earlier|earlier\s+reported)",
    re.IGNORECASE,
)


def _is_stale_news(title: str) -> bool:
    """Return True if the headline is a re-report of older news."""
    return bool(_STALE_NEWS_PREFIXES.match(title.strip()))

MARKET_TZ = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# TradeHour
# ---------------------------------------------------------------------------

class TradeHour:
    """Determines the current NYSE market session."""

    def __init__(self) -> None:
        self._nyse = mcal.get_calendar("NYSE")

    def check_market_status(self) -> str:
        """Return the current NYSE session.

        Returns:
            "rth"    — regular trading hours
            "ext"    — pre-market or after-hours
            "closed" — market is closed (weekend / holiday)
        """
        market_tz = MARKET_TZ
        now = datetime.now(market_tz)

        today = now.strftime("%Y-%m-%d")
        tomorrow = (now + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        schedule = self._nyse.schedule(start_date=today, end_date=tomorrow)

        try:
            is_ext = self._nyse.open_at_time(schedule, now, only_rth=False)
        except (ValueError, IndexError):
            is_ext = False

        try:
            is_rth = self._nyse.open_at_time(schedule, now, only_rth=True)
        except (ValueError, IndexError):
            is_rth = False

        time_str = now.strftime("%I:%M %p %Z")
        if is_rth:
            logger.info("Regular trading hours (%s).", time_str)
            return "rth"
        if is_ext:
            logger.info("Extended hours (pre-market / after-hours) (%s).", time_str)
            return "ext"

        logger.info("Market closed (%s).", time_str)
        return "closed"

    def is_trading_day(self, date: datetime | None = None) -> bool:
        """Return ``True`` when NYSE has a scheduled session on the given date.

        Args:
            date: Date to check (default: today in America/New_York).
        """
        if date is None:
            date = datetime.now(MARKET_TZ)
        date_str = date.strftime("%Y-%m-%d")
        try:
            schedule = self._nyse.schedule(start_date=date_str, end_date=date_str)
            return not schedule.empty
        except Exception as exc:
            logger.error("Error checking trading day for %s: %s", date_str, exc)
            return False

    def days_to_next_session(self) -> int:
        """Return the number of calendar days until the next NYSE trading session.

        Returns 0 when today is a trading day, 1 when tomorrow is, etc.
        Looks ahead up to 7 days; returns 7 if no session is found in that window
        (e.g. an extended holiday period).
        """
        market_tz = MARKET_TZ
        today = datetime.now(market_tz)
        for offset in range(8):
            candidate = today + pd.Timedelta(days=offset)
            if self.is_trading_day(candidate):
                return offset
        return 7

    def should_collect_news(self) -> bool:
        """Return ``True`` when news collection is worthwhile.

        Before 4 PM: returns True if today is a trading day (overnight / pre-market
        window for the current session).  After 4 PM: returns True if tomorrow is a
        trading day (after-hours collection for the next session).

        Examples:
            - Friday   2 AM   → True  (today, Friday, is a trading day)
            - Friday   5 PM   → False (tomorrow, Saturday, is not a trading day)
            - Saturday 8 AM   → False (today, Saturday, is not a trading day)
            - Saturday 8 PM   → False (tomorrow, Sunday, is not a trading day)
            - Sunday   5 PM   → True  (tomorrow, Monday, is a trading day)
            - Wednesday 6 PM  → True  (tomorrow, Thursday, is a trading day)
            - Wed before Thanksgiving → False (tomorrow, Thursday, is a holiday)
        """
        market_tz = MARKET_TZ
        now = datetime.now(market_tz)

        # Before 4 PM we're in the pre-session window — collect news if TODAY is a
        # trading day (e.g. 2 AM Friday → collect for Friday's open).
        # From 4 PM onwards RTH is over — collect only if TOMORROW is a trading day
        # (e.g. 6 PM Wednesday → collect for Thursday; 6 PM Friday → skip for Saturday).
        if now.hour < 16:
            target = now.date()
        else:
            target = (now + timedelta(days=1)).date()

        if not self.is_trading_day(target):
            logger.info(
                "News collection skipped — %s is not a trading day.",
                target.strftime("%Y-%m-%d"),
            )
            return False

        return True

    def _get_raw_news_window(self) -> tuple[datetime, datetime]:
        """Return the news collection window anchored to the previous session close.

        The window spans from the **actual close time of the previous trading
        session** to **now**.  Using the real close (from the NYSE schedule)
        rather than a hardcoded 3:00 PM correctly handles early-close days
        such as the day before Thanksgiving (1:00 PM close).

        Examples:
            - Monday after-hours (4 PM+) → Monday close → now
            - Tuesday pre-open  (5 AM)   → Monday close → now
            - Monday pre-open   (5 AM)   → Friday close → now  (skips weekend)
            - Post-holiday open          → last session close → now

        Returns:
            ``(from_time, to_time)`` as timezone-aware datetimes (America/New_York).
        """
        market_tz = MARKET_TZ
        now = datetime.now(market_tz)

        # Look back up to 10 calendar days to find the previous trading session
        start = (now - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        schedule = self._nyse.schedule(start_date=start, end_date=end)

        if schedule.empty:
            logger.warning("No NYSE sessions found in the last 10 days — using 24h fallback.")
            return now - pd.Timedelta(hours=24), now

        # Determine the most recently *completed* trading session:
        #   - Not a trading day → last row is the previous session.
        #   - Trading day, market still open (pre-market / RTH) → use the
        #     second-to-last row (e.g. Monday 5 AM → Friday's close).
        #   - Trading day, market already closed (after-hours) → use today's
        #     row (e.g. Monday 4 PM → Monday's close, not Friday's).
        if self.is_trading_day():
            today_close = schedule.iloc[-1]["market_close"].to_pydatetime().astimezone(market_tz)
            if now >= today_close:
                # Today's session has ended — anchor from today's close
                prev_row = schedule.iloc[-1]
            else:
                # Today hasn't closed yet — anchor from the previous session
                prev_row = schedule.iloc[-2] if len(schedule) >= 2 else schedule.iloc[-1]
        else:
            prev_row = schedule.iloc[-1]

        from_time = prev_row["market_close"].to_pydatetime().astimezone(market_tz)

        return from_time, now

    def get_news_window(self, start_floor: datetime | None = None) -> tuple[datetime, datetime]:
        """Return the news collection window, optionally floored to ``start_floor``.

        ``start_floor`` is typically the program start time — it prevents
        fetching a backlog of articles published before the bot was launched.
        ``from_time`` becomes ``max(previous_session_close, start_floor)``.
        """
        from_time, to_time = self._get_raw_news_window()
        if start_floor is not None and start_floor > from_time:
            from_time = start_floor
        logger.info(
            "News window: %s → %s",
            from_time.strftime("%Y-%m-%d %H:%M %Z"),
            to_time.strftime("%Y-%m-%d %H:%M %Z"),
        )
        return from_time, to_time

    def get_next_open_date(self) -> date:
        """Return the date of the next RTH open — i.e. the day a limit order placed now will execute.

        - Pre-market (before today's open)  → today's date
        - After-hours / closed              → next trading day's date
        """
        now = datetime.now(MARKET_TZ)
        today_open = self.get_market_open_time()
        if today_open is not None and now < today_open:
            return now.date()
        # After close or non-trading day — find the next trading session
        for offset in range(1, 8):
            candidate = now + pd.Timedelta(days=offset)
            if self.is_trading_day(candidate):
                return candidate.date()
        return (now + pd.Timedelta(days=1)).date()  # fallback

    def get_market_open_time(self) -> datetime | None:
        """Return the RTH open time for today's NYSE session.

        Returns:
            A timezone-aware :class:`datetime` (America/New_York) representing
            today's market open, or ``None`` when the market is not scheduled
            to trade today (weekend / holiday).
        """
        market_tz = MARKET_TZ
        now = datetime.now(market_tz)
        today = now.strftime("%Y-%m-%d")

        try:
            schedule = self._nyse.schedule(start_date=today, end_date=today)
            if schedule.empty:
                return None
            open_utc = schedule.iloc[0]["market_open"]
            return open_utc.to_pydatetime().astimezone(market_tz)
        except Exception as exc:
            logger.error("Error retrieving NYSE open time: %s", exc)
            return None

    def get_market_close_time(self) -> datetime | None:
        """Return the RTH close time for today's NYSE session.

        Returns:
            A timezone-aware :class:`datetime` (America/New_York) representing
            today's market close, or ``None`` when the market is not scheduled
            to trade today (weekend / holiday).
        """
        market_tz = MARKET_TZ
        now = datetime.now(market_tz)
        today = now.strftime("%Y-%m-%d")

        try:
            schedule = self._nyse.schedule(start_date=today, end_date=today)
            if schedule.empty:
                logger.info("No NYSE session scheduled for %s.", today)
                return None

            # market_close is stored as UTC in the schedule — convert to ET
            close_utc = schedule.iloc[0]["market_close"]
            close_et = close_utc.to_pydatetime().astimezone(market_tz)
            logger.info("NYSE close today: %s.", close_et.strftime("%I:%M %p %Z"))
            return close_et
        except Exception as exc:
            logger.error("Error retrieving NYSE close time: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Obb
# ---------------------------------------------------------------------------

class Obb:
    """News ingestion layer backed by OpenBB / Benzinga.

    Fetches company news, optionally filters by recency, and matches
    headlines against regex patterns defined in a CSV config file.
    Duplicate headlines are suppressed via an in-memory MD5 checksum cache.

    Args:
        provider:        OpenBB news provider (default ``"benzinga"``).
        config_csv_file: Path to the news-pattern config CSV.
        limit:           Maximum number of headlines to fetch per call.
        updated_since:   Only keep headlines published within the last N minutes.
    """

    def __init__(
        self,
        provider: str = "benzinga",
        config_csv_file: str | None = None,
        limit: int | None = None,
        updated_since: int | None = None,
    ) -> None:
        self.provider = provider
        self.config_csv_file = config_csv_file
        self.limit = limit
        self.updated_since = updated_since

        self.config_csv_data: pd.DataFrame | None = None
        self.news_data: pd.DataFrame | None = None
        # Maps MD5 checksum → datetime the item was first seen
        self._checksum_cache: dict[str, datetime] = {}

    def get_config_csv(self) -> pd.DataFrame | None:
        """Load the news-pattern config from disk into ``self.config_csv_data``.

        Returns the DataFrame on success, or ``None`` on error.
        """
        try:
            self.config_csv_data = pd.read_csv(self.config_csv_file)
            return self.config_csv_data
        except Exception as exc:
            logger.error("Failed to read config CSV '%s': %s", self.config_csv_file, exc)
            return None

    def get_news(
        self,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> pd.DataFrame | None:
        """Fetch company news from the configured OpenBB provider.

        When ``from_time`` and ``to_time`` are provided they are passed
        directly to OpenBB as ``start_date`` / ``end_date``, which lets the
        provider filter server-side (e.g. to cover the overnight window from
        the previous day's close to the current day's open).

        When they are omitted the call falls back to the ``limit`` /
        ``updated_since`` behaviour used during the live trading loop.

        Args:
            from_time: Start of the time window (timezone-aware recommended).
            to_time:   End of the time window (timezone-aware recommended).

        Returns:
            A DataFrame of news items, or ``None`` on error.
        """
        try:
            kwargs: dict = {"provider": self.provider}

            if from_time is not None and to_time is not None:
                # Format as the string Benzinga / OpenBB expects
                kwargs["start_date"] = from_time.strftime("%Y-%m-%d")
                kwargs["end_date"] = to_time.strftime("%Y-%m-%d")
                logger.info(
                    "Fetching news: %s → %s",
                    from_time.strftime("%Y-%m-%d %H:%M %Z"),
                    to_time.strftime("%Y-%m-%d %H:%M %Z"),
                )
            elif self.limit is not None:
                kwargs["limit"] = self.limit
                logger.info("Fetching news: last %d headline(s) (no time window).", self.limit)

            self.news_data = obb.news.company(**kwargs)

            # OpenBB only accepts date-only strings, so it may return headlines
            # from earlier in the day than from_time (e.g. all of Monday when we
            # only want from Monday 4 PM close onwards).  Apply a precise
            # client-side filter to restore the intended boundary.
            if from_time is not None:
                self.news_data["updated"] = pd.to_datetime(self.news_data["updated"], utc=True)
                cutoff = pd.Timestamp(from_time).tz_convert("UTC")
                before = len(self.news_data)
                self.news_data = self.news_data[self.news_data["updated"] >= cutoff]
                dropped = before - len(self.news_data)
                if dropped:
                    logger.debug(
                        "Dropped %d headline(s) published before %s.",
                        dropped,
                        from_time.strftime("%Y-%m-%d %H:%M %Z"),
                    )

            # Fallback in-process recency filter (used when no explicit window given)
            elif self.updated_since is not None:
                cutoff = datetime.now(pytz.utc) - timedelta(minutes=self.updated_since)
                self.news_data["updated"] = pd.to_datetime(self.news_data["updated"], utc=True)
                self.news_data = self.news_data[self.news_data["updated"] >= cutoff]

            return self.news_data
        except Exception as exc:
            logger.error("Failed to retrieve news: %s", exc)
            return None

    def process_news(self) -> dict:
        """Match news items against the config CSV patterns.

        Each unprocessed headline is hashed to prevent re-processing across
        loop iterations.  Symbols with multiple tickers (comma-separated)
        are skipped because the trade leg is ambiguous.

        Returns:
            A dict mapping ``symbol → config_row_dict`` for every match.
            Includes the matched ``title`` key in each value.
        """
        if self.news_data is None:
            logger.warning("process_news called with no news data loaded.")
            return {}

        matched: dict = {}

        for _, row in self.news_data.iterrows():
            title: str = row["title"]
            updated = row["updated"]
            symbols: str = row["symbols"]
            body: str = row.get("body", "") or ""  # full article text; may be absent

            # Dedup: skip headlines we have already acted on
            checksum = hashlib.md5(f"{title}_{updated}".encode()).hexdigest()
            if checksum in self._checksum_cache:
                logger.debug("Already processed '%s' — skipping.", title)
                continue

            if _is_stale_news(title):
                logger.info("Skipping stale/re-reported headline: %s", title)
                self._checksum_cache[checksum] = datetime.now()
                continue

            logger.info("Processing: [%s] %s", updated, title)
            self._checksum_cache[checksum] = datetime.now()

            if self.config_csv_data is None:
                logger.warning("No config CSV loaded — cannot match news items.")
                continue

            for _, cfg_row in self.config_csv_data.iterrows():
                if cfg_row["Active"] != "Yes":
                    continue

                pattern: str = cfg_row["Pattern"]
                if not re.search(pattern, title, re.IGNORECASE):
                    continue

                logger.info(
                    "Headline matched pattern '%s' (symbols: %s): %s",
                    pattern, symbols, title,
                )

                # Reject articles with no ticker — no actionable symbol to trade
                if not symbols:
                    logger.debug("Skipping match — no ticker in article: %s", title)
                    continue
                if "," in symbols:
                    # Multiple tickers — skip; trade leg is ambiguous
                    continue

                matched[symbols] = {**cfg_row.to_dict(), "title": title, "body": body}

        return matched

    def clean_old_checksums(self, retention_minutes: int | None = None) -> None:
        """Evict checksum entries older than ``retention_minutes``.

        Defaults to ``5 × updated_since`` minutes, or 60 minutes when
        ``updated_since`` is not set.
        """
        if retention_minutes is None:
            retention_minutes = (self.updated_since * 5) if self.updated_since else 60

        cutoff = datetime.now()
        stale = [
            cs for cs, ts in self._checksum_cache.items()
            if (cutoff - ts).total_seconds() > retention_minutes * 60
        ]
        for cs in stale:
            del self._checksum_cache[cs]

        if stale:
            logger.debug("Evicted %d stale checksum(s).", len(stale))


# ---------------------------------------------------------------------------
# BenzingaWebSocket
# ---------------------------------------------------------------------------

class BenzingaWebSocket:
    """Real-time data streaming via the Benzinga WebSocket API.

    Connects to one of Benzinga's stream endpoints and delivers messages to a
    caller-supplied callback as they arrive.  The connection runs in a daemon
    background thread so the caller is never blocked.

    Connection URL pattern::

        wss://api.benzinga.com/api/v1/{stream}/stream?token=<api_key>

    Each incoming message is decoded from JSON and passed to ``on_message`` as
    a dict with the standard Benzinga envelope fields:

    .. code-block:: json

        {
          "id": "<unique-message-id>",
          "api_version": "websocket/v1",
          "kind": "<stream-type>",
          "data": {
            "action": "created|updated|deleted",
            "id": "<record-id>",
            "timestamp": "<ISO-8601>",
            "content": {}
          }
        }

    Supported actions (sent to the server as plain text):

    * ``ping``   — keepalive; server replies with ``pong``.
    * ``replay`` — server replays the last ≤100 cached messages.

    Args:
        api_key:         Benzinga API token (from api.benzinga.com/token).
        stream:          Stream name (default ``"news"``).  Must be one of
                         :attr:`STREAMS`.
        on_message:      Callable ``(msg: dict) -> None`` invoked for every
                         decoded message.
        on_error:        Optional callable ``(exc: Exception) -> None`` fired
                         on connection errors.
        on_open:         Optional callable ``() -> None`` fired on connect.
        on_close:        Optional callable ``(code: int | None, reason: str | None) -> None``
                         fired when the connection closes.
        ping_interval:   Seconds between automatic client-initiated WebSocket
                         ping frames (default 30).  The Benzinga server also
                         initiates a ping every 10 s; most libraries handle
                         that automatically.
        reconnect_delay: Seconds to wait before reconnecting after an
                         unexpected close (default 5).  Set to 0 to disable
                         automatic reconnection.
    """

    _BASE_URL = "wss://api.benzinga.com/api/v1/{stream}/stream"

    STREAMS: frozenset[str] = frozenset({
        "analyst_insights",
        "ratings",
        "consensus_ratings",
        "earnings",
        "bulls_bears_say",
        "news",
        "transcripts",
    })

    def __init__(
        self,
        api_key: str,
        stream: str = "news",
        on_message=None,
        on_error=None,
        on_open=None,
        on_close=None,
        ping_interval: int = 10,
        reconnect_delay: int = 5,
    ) -> None:
        if stream not in self.STREAMS:
            raise ValueError(
                f"Unknown stream '{stream}'. Valid values: {sorted(self.STREAMS)}"
            )

        self.api_key = api_key
        self.stream = stream
        self._on_message_cb = on_message
        self._on_error_cb = on_error
        self._on_open_cb = on_open
        self._on_close_cb = on_close
        self.ping_interval = ping_interval
        self.reconnect_delay = reconnect_delay

        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        """Fully-formed WebSocket URL including the API token query parameter."""
        return f"{self._BASE_URL.format(stream=self.stream)}?token={self.api_key}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the WebSocket connection in a background daemon thread.

        Returns immediately; all messages are delivered via the ``on_message``
        callback.  Call :meth:`disconnect` to shut down cleanly.
        """
        self._ws = websocket.WebSocketApp(
            self.url,
            on_open=self._handle_open,
            on_message=self._handle_message,
            on_error=self._handle_error,
            on_close=self._handle_close,
        )
        self._thread = threading.Thread(
            target=self._run,
            name=f"benzinga-ws-{self.stream}",
            daemon=True,
        )
        self._thread.start()
        logger.info("Benzinga WebSocket thread started (stream=%s).", self.stream)

    def disconnect(self) -> None:
        """Close the WebSocket connection and join the background thread."""
        if self._ws is not None:
            self._ws.close()
            logger.info("Benzinga WebSocket closed (stream=%s).", self.stream)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)

    def replay(self) -> None:
        """Ask the server to replay the last ≤100 cached messages.

        Useful after a reconnect to recover messages that arrived while the
        client was disconnected.  The ``id`` field on each replayed message
        can be used for idempotent processing.
        """
        self._send_text("replay")

    def ping(self) -> None:
        """Send a manual application-level ping; server responds with ``pong``."""
        self._send_text("ping")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """Thread target — runs the WebSocketApp event loop."""
        reconnect = self.reconnect_delay if self.reconnect_delay > 0 else None
        self._ws.run_forever(
            ping_interval=self.ping_interval,
            ping_timeout=min(5, self.ping_interval - 1),
            reconnect=reconnect,
        )

    def _send_text(self, text: str) -> None:
        if self._ws is None:
            logger.warning("Cannot send '%s' — WebSocket not connected.", text)
            return
        try:
            self._ws.send(text)
        except Exception as exc:
            logger.error("Error sending '%s' to Benzinga: %s", text, exc)

    # ------------------------------------------------------------------
    # WebSocketApp callbacks
    # ------------------------------------------------------------------

    def _handle_open(self, _ws) -> None:
        logger.info("Benzinga WebSocket connected (stream=%s).", self.stream)
        if self._on_open_cb is not None:
            self._on_open_cb()

    def _handle_message(self, _ws, raw: str) -> None:
        logger.debug("Benzinga raw message (stream=%s): %r", self.stream, raw)
        # Application-level pong arrives as the plain string "pong"
        if raw == "pong":
            logger.debug("Benzinga pong received (stream=%s).", self.stream)
            return

        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Non-JSON message from Benzinga (stream=%s): %r", self.stream, raw)
            return

        logger.debug(
            "Benzinga message — stream=%s kind=%s action=%s id=%s",
            self.stream,
            msg.get("kind"),
            msg.get("data", {}).get("action"),
            msg.get("id"),
        )

        if self._on_message_cb is not None:
            try:
                self._on_message_cb(msg)
            except Exception as exc:
                logger.error("on_message callback raised (stream=%s): %s", self.stream, exc)

    def _handle_error(self, _ws, exc: Exception) -> None:
        logger.error("Benzinga WebSocket error (stream=%s): %s", self.stream, exc)
        if self._on_error_cb is not None:
            self._on_error_cb(exc)

    def _handle_close(self, _ws, close_status_code, close_msg) -> None:
        logger.info(
            "Benzinga WebSocket closed (stream=%s) — code=%s msg=%s",
            self.stream,
            close_status_code,
            close_msg,
        )
        if self._on_close_cb is not None:
            self._on_close_cb(close_status_code, close_msg)


# ---------------------------------------------------------------------------
# Massive
# ---------------------------------------------------------------------------

class Massive:
    """Benzinga news ingestion via the Massive REST API (formerly Polygon.io).

    Primary mode is REST polling via :meth:`get_news` + :meth:`process_news`,
    which mirrors the :class:`Obb` interface so the two are interchangeable in
    :class:`TradeManager`.

    REST news endpoint::

        GET https://api.massive.com/benzinga/v2/news

    Key response fields per article:

    .. code-block:: json

        {
          "title":        "<headline>",
          "body":         "<full article text>",
          "teaser":       "<short summary>",
          "published":    "<ISO-8601>",
          "last_updated": "<ISO-8601>",
          "tickers":      ["AAPL", "MSFT"],
          "channels":     ["Health Care"],
          "tags":         ["FDA"],
          "author":       "<author name>",
          "benzinga_id":  "<unique id>",
          "url":          "<source link>"
        }

    Pagination is cursor-based: follow ``next_url`` in the response until it
    is absent or the result set is exhausted.

    Args:
        api_key:         Massive API key (sent as ``Authorization: Bearer <key>``).
        config_csv_file: Path to the news-pattern config CSV (same as :class:`Obb`).
        base_url:        REST base URL (default ``"https://api.massive.com"``).
        limit:           Max articles per page (default 100, max 50 000).
    """

    _BASE_URL = "https://api.massive.com"
    _NEWS_PATH = "/benzinga/v2/news"

    def __init__(
        self,
        api_key: str,
        config_csv_file: str | None = None,
        base_url: str | None = None,
        limit: int = 100,
    ) -> None:
        self.api_key = api_key
        self.config_csv_file = config_csv_file
        self._base_url = (base_url or self._BASE_URL).rstrip("/")
        self.limit = limit

        self.config_csv_data: pd.DataFrame | None = None
        self.news_data: pd.DataFrame | None = None
        self._checksum_cache: dict[str, datetime] = {}

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    # ------------------------------------------------------------------
    # Public API — mirrors Obb
    # ------------------------------------------------------------------

    def get_config_csv(self) -> pd.DataFrame | None:
        """Load the news-pattern config from disk into ``self.config_csv_data``."""
        try:
            self.config_csv_data = pd.read_csv(self.config_csv_file)
            return self.config_csv_data
        except Exception as exc:
            logger.error("Failed to read config CSV '%s': %s", self.config_csv_file, exc)
            return None

    def get_news(
        self,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> pd.DataFrame | None:
        """Fetch Benzinga news from the Massive REST API.

        Follows ``next_url`` pagination until all results in the window are
        collected.  Results are stored in ``self.news_data`` and returned as a
        DataFrame with columns ``title``, ``symbols``, ``body``, ``updated``.

        Args:
            from_time: Start of the time window (``published.gte``).
            to_time:   End of the time window (``published.lte``).
        """
        import requests as _requests

        params: dict = {"limit": self.limit, "sort": "published.asc"}
        if from_time is not None:
            params["published.gte"] = from_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            logger.info(
                "Fetching Massive news: %s → %s",
                from_time.strftime("%Y-%m-%d %H:%M %Z"),
                (to_time.strftime("%Y-%m-%d %H:%M %Z") if to_time else "now"),
            )
        if to_time is not None:
            params["published.lte"] = to_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        url: str | None = self._base_url + self._NEWS_PATH
        rows: list[dict] = []

        try:
            while url:
                resp = _requests.get(url, headers=self._headers, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                for article in data.get("results", []):
                    tickers = article.get("tickers") or article.get("stocks") or []
                    symbols = ",".join(tickers) if isinstance(tickers, list) else str(tickers)
                    rows.append({
                        "title":   article.get("title", ""),
                        "symbols": symbols,
                        "body":    article.get("body", "") or article.get("teaser", ""),
                        "updated": article.get("published", "") or article.get("last_updated", ""),
                    })

                # Follow cursor-based pagination; clear params so next_url is used as-is
                url = data.get("next_url")
                params = {}

        except Exception as exc:
            logger.error("Failed to retrieve Massive news: %s", exc)
            return None

        logger.info("Massive: fetched %d article(s).", len(rows))
        self.news_data = pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=["title", "symbols", "body", "updated"]
        )
        return self.news_data

    def process_news(self) -> dict:
        """Match news items against the config CSV patterns.

        Identical behaviour to :meth:`Obb.process_news` — deduplicates via
        MD5 checksum and skips multi-ticker headlines.

        Returns:
            A dict mapping ``symbol → config_row_dict`` for every match.
        """
        if self.news_data is None:
            logger.warning("process_news called with no news data loaded.")
            return {}

        matched: dict = {}

        for _, row in self.news_data.iterrows():
            title: str = row["title"]
            updated = row["updated"]
            symbols: str = row["symbols"]
            body: str = row.get("body", "") or ""

            checksum = hashlib.md5(f"{title}_{updated}".encode()).hexdigest()
            if checksum in self._checksum_cache:
                logger.debug("Already processed '%s' — skipping.", title)
                continue

            if _is_stale_news(title):
                logger.info("Skipping stale/re-reported headline: %s", title)
                self._checksum_cache[checksum] = datetime.now()
                continue

            logger.info("Processing: [%s] %s", updated, title)
            self._checksum_cache[checksum] = datetime.now()

            if self.config_csv_data is None:
                logger.warning("No config CSV loaded — cannot match news items.")
                continue

            for _, cfg_row in self.config_csv_data.iterrows():
                if cfg_row["Active"] != "Yes":
                    continue

                pattern: str = cfg_row["Pattern"]
                if not re.search(pattern, title, re.IGNORECASE):
                    continue

                logger.info(
                    "Headline matched pattern '%s' (symbols: %s): %s",
                    pattern, symbols, title,
                )

                if not symbols:
                    logger.debug("Skipping match — no ticker in article: %s", title)
                    continue
                if "," in symbols:
                    continue

                matched[symbols] = {**cfg_row.to_dict(), "title": title, "body": body}

        return matched

    def clean_old_checksums(self, retention_minutes: int = 60) -> None:
        """Evict checksum entries older than ``retention_minutes``."""
        cutoff = datetime.now()
        stale = [
            cs for cs, ts in self._checksum_cache.items()
            if (cutoff - ts).total_seconds() > retention_minutes * 60
        ]
        for cs in stale:
            del self._checksum_cache[cs]
        if stale:
            logger.debug("Massive: evicted %d stale checksum(s).", len(stale))


# ---------------------------------------------------------------------------
# IBNewsStream
# ---------------------------------------------------------------------------

class IBNewsStream:
    """Per-symbol news polling via the Interactive Brokers TWS API.

    Calls ``reqHistoricalNews`` for each symbol in a watchlist CSV every
    ``poll_interval`` seconds using the providers that support historical
    queries (BZ and BRFG).  BRFUPDN and DJ are excluded because they cause
    ``reqHistoricalNews`` to time out even when the combined provider string
    contains working providers.

    IBKR prepends metadata to headlines (``{A:...:K:...:C:...}`` for BRFG,
    ``{A:...}!`` for BZ).  These are stripped before passing the headline to
    Claude so sentiment analysis sees clean text.

    Args:
        ib_api:          Connected :class:`IBapi` instance.
        provider_codes:  Full list of IBKR provider codes on the account.
                         Only ``BZ`` and ``BRFG`` are used for polling;
                         others are stored for reference.
        on_news:         Callback ``(title, symbols, body, updated) -> None``
                         invoked for every new article.
        watchlist_csv:   Path to CSV with columns ``Symbol`` and ``Active``.
        poll_interval:   Seconds between full-watchlist sweeps (default 60).
        lock:            Shared :class:`threading.Lock` that serialises IBKR
                         API calls across threads.
    """

    # Providers confirmed to support reqHistoricalNews without timeouts.
    _HISTORICAL_PROVIDERS = {"BZ", "BRFG"}

    def __init__(
        self,
        ib_api: "IBapi",
        provider_codes: list[str],
        on_news,
        watchlist_csv: str = "config/ibkr_news_watchlist.csv",
        poll_interval: int = 60,
        lock: threading.Lock | None = None,
    ) -> None:
        self._ib = ib_api
        # Only keep providers that reliably support reqHistoricalNews.
        working = [c for c in provider_codes if c in self._HISTORICAL_PROVIDERS]
        self._provider_str = "+".join(working) if working else "BZ"
        self._on_news_cb = on_news
        self._watchlist_csv = watchlist_csv
        self._poll_interval = poll_interval
        self._lock = lock or threading.Lock()
        self._seen: set[str] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._contracts: dict[str, int] = {}   # symbol -> conId

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Qualify watchlist contracts and start the polling thread."""
        self._qualify_watchlist()
        self._thread = threading.Thread(
            target=self._run,
            name="ibkr-news-stream",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "IBNewsStream started — %d symbol(s), providers: %s, poll every %ds",
            len(self._contracts), self._provider_str, self._poll_interval,
        )

    def disconnect(self) -> None:
        """Stop the polling thread."""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        logger.info("IBNewsStream stopped.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _qualify_watchlist(self) -> None:
        try:
            df = pd.read_csv(self._watchlist_csv)
        except Exception as exc:
            logger.error("IBNewsStream: cannot load watchlist %s: %s", self._watchlist_csv, exc)
            return
        symbols = df[df["Active"].str.strip().str.upper() == "YES"]["Symbol"].tolist()
        logger.info("IBNewsStream: qualifying %d symbol(s)…", len(symbols))
        for symbol in symbols:
            if self._stop.is_set():
                break
            try:
                with self._lock:
                    q = self._ib.ib.qualifyContracts(Stock(symbol, "SMART", "USD"))
                if q:
                    self._contracts[symbol] = q[0].conId
                    logger.debug("IBNewsStream: qualified %s (conId=%d)", symbol, q[0].conId)
                else:
                    logger.warning("IBNewsStream: could not qualify %s", symbol)
            except Exception as exc:
                logger.warning("IBNewsStream: qualification error %s: %s", symbol, exc)
        logger.info("IBNewsStream: %d/%d symbols qualified", len(self._contracts), len(symbols))

    def _run(self) -> None:
        """Background thread — polls reqHistoricalNews for each watchlist symbol."""
        logger.debug("IBNewsStream: polling thread started, interval=%ds", self._poll_interval)
        while not self._stop.is_set():
            lookback = self._poll_interval + 30
            start_str = (
                datetime.now(MARKET_TZ) - timedelta(seconds=lookback)
            ).strftime("%Y%m%d %H:%M:%S.0")

            for symbol, con_id in list(self._contracts.items()):
                if self._stop.is_set():
                    break
                try:
                    with self._lock:
                        articles = self._ib.ib.reqHistoricalNews(
                            conId=con_id,
                            providerCodes=self._provider_str,
                            startDateTime=start_str,
                            endDateTime="",
                            totalResults=10,
                        )
                    new_count = 0
                    for article in (articles or []):
                        key = f"{article.providerCode}:{article.articleId}"
                        if key in self._seen:
                            continue
                        self._seen.add(key)
                        new_count += 1
                        headline = self._clean_headline(article.headline)
                        logger.info(
                            "IBNewsStream: %s [%s] %s",
                            symbol, article.providerCode, headline,
                        )
                        self._deliver(article, symbol, headline)
                    if new_count:
                        logger.debug("IBNewsStream: %s — %d new article(s)", symbol, new_count)
                except Exception as exc:
                    logger.error("IBNewsStream: reqHistoricalNews failed for %s: %s", symbol, exc)

                self._stop.wait(0.2)   # brief pause between symbols

            self._stop.wait(self._poll_interval)

    @staticmethod
    def _clean_headline(raw: str) -> str:
        """Strip IBKR metadata prefix and Benzinga alert marker from a headline.

        BRFG format: ``{A:800015:L:en:K:0.56:C:0.557}NVIDIA Powers Up…``
        BZ format:   ``{A:800015:L:en}!Tech Leads, Dow Lags…``
        """
        cleaned = re.sub(r"^\{[^}]*\}", "", raw).lstrip("!").strip()
        return cleaned if cleaned else raw

    def _deliver(self, article, symbol: str, headline: str) -> None:
        """Fetch full article text then invoke the on_news callback."""
        body = ""
        try:
            with self._lock:
                full = self._ib.ib.reqNewsArticle(
                    providerCode=article.providerCode,
                    articleId=article.articleId,
                )
            if full and full.articleType == 0:
                body = full.articleText or ""
        except Exception as exc:
            logger.warning(
                "IBNewsStream: reqNewsArticle failed — %s %s: %s",
                article.providerCode, article.articleId, exc,
            )

        if self._on_news_cb:
            try:
                self._on_news_cb(
                    title=headline,
                    symbols=symbol,
                    body=body,
                    updated=str(article.time),
                )
            except Exception as exc:
                logger.error("IBNewsStream: on_news callback raised: %s", exc)


# ---------------------------------------------------------------------------
# ClaudeSentiment
# ---------------------------------------------------------------------------

class ClaudeSentiment:
    """Headline sentiment classification via the Anthropic Claude API.

    Invoked only after a headline has already matched a regex pattern, so
    API usage stays low.  Claude makes a binary Yes/No judgment on whether
    the headline is a genuine bullish catalyst, and provides a plain-English
    reason that serves as the audit trail for every decision.

    Each ``TradeStrategy`` can have its own system prompt loaded from a file
    in ``prompts_dir`` (e.g. ``config/prompts/CompanyUpgrade.txt``).  A
    ``default.txt`` prompt is used as fallback when no strategy-specific file
    exists.  The response format instruction is appended in code so prompt
    files stay focused on domain logic and never need to repeat boilerplate.

    Args:
        model:       Anthropic model ID to use (default ``"claude-opus-4-6"``).
        prompts_dir: Directory containing per-strategy ``.txt`` prompt files.
    """

    # Appended to every prompt so the response contract stays in one place
    _RESPONSE_FORMAT = (
        "\n\nRespond ONLY with a JSON object — no markdown, no extra text:\n"
        '{"is_positive": true|false, "reason": "<one sentence>"}\n\n'
        "Fields:\n"
        "  is_positive — true only if the event is clearly bullish\n"
        "  reason      — plain-English justification of your yes/no decision"
    )

    def __init__(
        self,
        model: str = "claude-opus-4-6",
        prompts_dir: str = "config/prompts",
        context_dir: str = "config/context",
        use_web_search: bool = False,
    ) -> None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise EnvironmentError(
                "ANTHROPIC_API_KEY is not set — Claude sentiment analysis will not work. "
                "Set the environment variable before starting the bot."
            )
        self.model = model
        self._use_web_search = use_web_search
        self._client = anthropic.Anthropic()
        self._prompts: dict[str, str] = self._load_prompts(prompts_dir)
        self._context: dict[str, str] = self._load_context(context_dir)
        # Keyed on MD5(title + strategy) — survives timestamp changes on re-fetched articles
        self._sentiment_cache: dict[str, dict] = {}
        logger.info(
            "ClaudeSentiment initialised — web_search=%s.", use_web_search
        )

    @staticmethod
    def _load_context(context_dir: str) -> dict[str, str]:
        """Load per-strategy learning/rule files from ``context_dir``.

        Files are named ``<StrategyName>.txt`` (same convention as prompts).
        A ``default.txt`` applies to all strategies that have no specific file.
        Missing directory is silently ignored — context is always optional.
        """
        context: dict[str, str] = {}
        if not os.path.isdir(context_dir):
            return context
        for filename in os.listdir(context_dir):
            if filename.endswith(".txt"):
                strategy = filename[:-4]
                path = os.path.join(context_dir, filename)
                with open(path, "r", encoding="utf-8") as fh:
                    context[strategy] = fh.read().strip()
                logger.debug("Loaded context for strategy '%s' from %s", strategy, path)
        logger.info("Loaded %d context file(s) from '%s'.", len(context), context_dir)
        return context

    @staticmethod
    def _load_prompts(prompts_dir: str) -> dict[str, str]:
        """Load all ``.txt`` files from ``prompts_dir`` keyed by stem name.

        Always requires a ``default.txt`` to be present as the fallback.
        """
        prompts: dict[str, str] = {}
        if not os.path.isdir(prompts_dir):
            raise FileNotFoundError(
                f"Prompts directory not found: '{prompts_dir}'"
            )

        for filename in os.listdir(prompts_dir):
            if filename.endswith(".txt"):
                strategy = filename[:-4]  # strip .txt
                path = os.path.join(prompts_dir, filename)
                with open(path, "r", encoding="utf-8") as fh:
                    prompts[strategy] = fh.read().strip()
                logger.debug("Loaded prompt for strategy '%s' from %s", strategy, path)

        if "default" not in prompts:
            raise FileNotFoundError(
                f"'default.txt' is required in '{prompts_dir}' as a fallback prompt."
            )

        logger.info("Loaded %d prompt(s) from '%s'.", len(prompts), prompts_dir)
        return prompts

    def is_strategy_configured(self, strategy: str) -> bool:
        """Return ``True`` when ``strategy`` has both a prompt and a context file."""
        return strategy in self._prompts and strategy in self._context

    def _parse_context_sections(self, strategy: str) -> tuple[str, str]:
        """Return (always_section, web_search_section) from the context file.

        Splits on ``[ALWAYS]`` and ``[WEB_SEARCH]`` markers.
        """
        raw = self._context[strategy]
        always, web = "", ""
        current = None
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped == "[ALWAYS]":
                current = "always"
            elif stripped == "[WEB_SEARCH]":
                current = "web"
            elif current == "always":
                always += line + "\n"
            elif current == "web":
                web += line + "\n"
        return always.strip(), web.strip()

    def _get_system_prompt(self, strategy: str) -> str:
        """Return the system prompt for ``strategy``.

        Always appends the [ALWAYS] context section. Appends [WEB_SEARCH]
        section only when use_web_search=True.

        Raises ``KeyError`` if no dedicated prompt or context file exists —
        callers must check :meth:`is_strategy_configured` before calling this.
        """
        if strategy not in self._prompts:
            raise KeyError(
                f"No prompt file found for strategy '{strategy}' — "
                f"create config/prompts/{strategy}.txt before trading."
            )
        if strategy not in self._context:
            raise KeyError(
                f"No context file found for strategy '{strategy}' — "
                f"create config/context/{strategy}.txt before trading."
            )
        base = self._prompts[strategy]
        always_rules, web_rules = self._parse_context_sections(strategy)
        if always_rules:
            base = base + "\n\n## Trading Rules\n" + always_rules
        if web_rules and self._use_web_search:
            base = base + "\n\n## Research Instructions (use web search)\n" + web_rules
        return base + self._RESPONSE_FORMAT

    def _assess_headline(
        self,
        title: str,
        body: str = "",
        strategy: str = "",
        symbol: str = "",
    ) -> dict:
        """Call the Claude API and return a parsed sentiment result.

        Claude may use the web_search tool to research whether the news is
        genuinely new or was already known/priced-in.  The conversation loops
        until Claude either responds with the final JSON or exhausts the tool
        turn budget.

        Args:
            title:    The news headline (always present).
            body:     Full article text — used for deeper reasoning when available.
            strategy: ``TradeStrategy`` value used to select the system prompt.
            symbol:   Ticker symbol — included in the prompt so Claude knows
                      what to search for.

        Returns a dict with keys ``is_positive`` (bool) and ``reason`` (str).
        On error returns a safe default with ``is_positive=False``.
        """
        cache_key = hashlib.md5(f"{title}_{strategy}".encode()).hexdigest()
        if cache_key in self._sentiment_cache:
            logger.debug("Sentiment cache hit for '%s' — skipping Claude call.", title)
            return self._sentiment_cache[cache_key]

        system_prompt = self._get_system_prompt(strategy)

        parts = [f'Headline: "{title}"']
        if symbol:
            parts.append(f"Ticker: {symbol}")
        if body:
            parts.append(f"Article body:\n{body}")
        user_content = "\n\n".join(parts)

        tools = (
            [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]
            if self._use_web_search else []
        )
        messages = [{"role": "user", "content": user_content}]
        max_tokens = 1024 if self._use_web_search else 128

        _RETRYABLE_CODES = (429, 500, 529)
        _MAX_RETRIES = 3

        for attempt in range(_MAX_RETRIES + 1):
            try:
                for _ in range(6):  # cap tool-use turns to avoid runaway loops
                    kwargs: dict = dict(
                        model=self.model,
                        max_tokens=max_tokens,
                        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
                        messages=messages,
                    )
                    if tools:
                        kwargs["tools"] = tools
                    response = self._client.messages.create(**kwargs)

                    if response.stop_reason == "end_turn":
                        raw = next(
                            (b.text for b in response.content if hasattr(b, "text")), "{}"
                        )
                        result = json.loads(raw)
                        self._sentiment_cache[cache_key] = result
                        return result

                    if response.stop_reason == "tool_use":
                        # web_search_20250305 is server-side: search results are already
                        # embedded in the response as web_search_tool_result blocks.
                        messages.append({"role": "assistant", "content": response.content})
                        tool_results = []
                        for block in response.content:
                            if getattr(block, "type", "") == "tool_use":
                                result_block = next(
                                    (
                                        b for b in response.content
                                        if getattr(b, "tool_use_id", None) == block.id
                                    ),
                                    None,
                                )
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": getattr(result_block, "content", ""),
                                })
                        messages.append({"role": "user", "content": tool_results})
                        continue

                    break  # unexpected stop reason

                logger.warning("Claude tool loop exhausted for '%s' — defaulting to False.", title)
                return {"is_positive": False, "reason": "tool loop exhausted"}

            except json.JSONDecodeError as exc:
                logger.error("Claude returned non-JSON for '%s': %s", title, exc)
                return {"is_positive": False, "reason": "parse error"}
            except anthropic.APIStatusError as exc:
                if exc.status_code == 400 and "credit balance is too low" in str(exc.body):
                    logger.critical(
                        "Anthropic credit balance exhausted — shutting down to prevent further charges."
                    )
                    raise SystemExit(1)
                if exc.status_code in _RETRYABLE_CODES and attempt < _MAX_RETRIES:
                    wait = 2 ** attempt
                    logger.warning(
                        "Claude API %s for '%s' — retrying in %ss (attempt %d/%d).",
                        exc.status_code, title, wait, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue
                logger.error("Claude API error for '%s': %s %s", title, exc.status_code, exc)
                return {"is_positive": False, "reason": f"api error: {exc.status_code}"}
            except Exception as exc:
                logger.error("Claude API error for '%s': %s", title, exc)
                return {"is_positive": False, "reason": f"api error: {type(exc).__name__}"}

    def analyze_sentiment(self, matched_config: dict, journal=None) -> dict:
        """Classify sentiment for each matched news item.

        Selects the system prompt based on each symbol's ``TradeStrategy``,
        then filters ``matched_config`` down to symbols Claude judges as a
        genuine bullish catalyst.  The ``reason`` field is preserved in the
        output as an audit trail.

        Both positive *and* negative decisions are written to ``journal`` (when
        provided) so the end-of-day analysis can review false negatives.

        Args:
            matched_config: Output of :meth:`Obb.process_news`.
            journal:        Optional :class:`~journal_lib.TradingJournal` instance.

        Returns:
            All analyzed symbols enriched with ``is_positive`` and ``sentiment_reason``.
        Callers should filter on ``is_positive`` themselves.
        """
        all_decisions: dict = {}

        for symbol, config in matched_config.items():
            if "EMPTY" in symbol:
                continue
            if ":" in symbol:
                logger.info("Skipping non-US symbol '%s' — exchange-prefixed symbols are not supported.", symbol)
                continue

            title: str = config.get("title", "")
            body: str = config.get("body", "") or ""
            strategy: str = config.get("TradeStrategy", "")

            if not self.is_strategy_configured(strategy):
                logger.error(
                    "Strategy '%s' is missing a prompt or context file — skipping %s. "
                    "Create config/prompts/%s.txt and config/context/%s.txt to enable it.",
                    strategy, symbol, strategy, strategy,
                )
                continue

            result = self._assess_headline(title, body, strategy, symbol)
            is_positive: bool = result.get("is_positive", False)
            reason: str = result.get("reason", "")

            logger.info(
                "Sentiment [%s][%s] is_positive=%s — %s",
                symbol, strategy, is_positive, reason,
            )

            if journal is not None:
                journal.log_sentiment_decision(symbol, title, strategy, is_positive, reason)

            all_decisions[symbol] = {**config, "is_positive": is_positive, "sentiment_reason": reason}

        return all_decisions


# ---------------------------------------------------------------------------
# IBapi helpers
# ---------------------------------------------------------------------------

def ensure_ibkr_connected(ib: IB, host: str, port: int, client_id: int) -> None:
    """Verify the IBKR connection is alive and reconnect if needed.

    isConnected() alone can miss stale sessions — e.g. TWS's 24-hour
    auto-disconnect where the socket appears open but the session has expired.
    reqCurrentTime() is a lightweight roundtrip that catches those cases before
    the first real API call fails.
    """
    if not ib.isConnected():
        logger.warning("IBKR not connected — reconnecting...")
        _ibkr_reconnect(ib, host, port, client_id)
        return
    try:
        ib.reqCurrentTime()
    except Exception as exc:
        logger.warning("IBKR heartbeat failed (%s) — session likely expired; reconnecting...", exc)
        try:
            ib.disconnect()
        except Exception:
            pass
        _ibkr_reconnect(ib, host, port, client_id)


def _ibkr_reconnect(ib: IB, host: str, port: int, client_id: int) -> None:
    """Connect to TWS / IB Gateway, retrying every 10 s until successful."""
    while True:
        try:
            ib.connect(host, port, clientId=client_id)
            logger.info("Connected to IB API at %s:%d (clientId=%d).", host, port, client_id)
            return
        except Exception as exc:
            logger.error("IB connection error: %s — retrying in 10 s.", exc)
            time.sleep(10)


# ---------------------------------------------------------------------------
# IBapi
# ---------------------------------------------------------------------------

class IBapi:
    """Wrapper around :class:`ib_async.IB` for order and position management.

    Method names follow the Interactive Brokers API convention (camelCase)
    to keep the call-site mapping obvious.

    Args:
        client_id: IB API client identifier (must be unique per connection).
        host:      TWS / IB Gateway host address.
        port:      TWS / IB Gateway port (7496 = live, 7497 = paper).
    """

    def __init__(
        self,
        client_id: int = 0,
        host: str = "127.0.0.1",
        port: int = 7496,
    ) -> None:
        self.client_id = client_id
        self.host = host
        self.port = port
        self.ib = IB()

    def connect(self) -> None:
        """Connect to TWS / IB Gateway, retrying every 10 s on failure."""
        while True:
            try:
                self.ib.connect(self.host, self.port, clientId=self.client_id)
                logger.info(
                    "Connected to IB API at %s:%d (clientId=%d).",
                    self.host, self.port, self.client_id,
                )
                if self.port == 7497:
                    self.ib.reqMarketDataType(3)
                    logger.info("Paper trading account — using delayed market data (type 3).")
                return
            except Exception as exc:
                logger.error("IB connection error: %s — retrying in 10 s.", exc)
                time.sleep(10)

    def isConnected(self) -> bool:
        """Return ``True`` when an active IB connection exists."""
        if self.ib.isConnected():
            logger.info("IBKR connection is active.")
            return True
        logger.warning("IBKR not connected — check TWS/Gateway status and API settings.")
        return False

    def ensure_connected(self) -> None:
        """Verify the connection is alive and reconnect if needed (see ensure_ibkr_connected)."""
        ensure_ibkr_connected(self.ib, self.host, self.port, self.client_id)

    def disconnect(self) -> None:
        """Disconnect from TWS / IB Gateway."""
        try:
            self.ib.disconnect()
            logger.info("Disconnected from IB API.")
        except Exception as exc:
            logger.error("Error disconnecting from IB API: %s", exc)

    def getPositions(self) -> list | None:
        """Return all currently held positions, or ``None`` on error."""
        try:
            positions = self.ib.positions()
            for pos in positions:
                logger.debug(
                    "Position — %s: qty=%s contract=%s avgCost=%s",
                    pos.contract.symbol, pos.position, pos.contract, pos.avgCost,
                )
            return positions
        except Exception as exc:
            logger.error("Error retrieving positions: %s", exc)
            return None

    def getTrades(self) -> list | None:
        """Return all open (working) trades, or ``None`` on error."""
        try:
            live_trades = self.ib.openTrades()
            if live_trades:
                logger.info("Found %d open trade(s).", len(live_trades))
                for trade in live_trades:
                    logger.debug(
                        "Open trade — %s: %s %s",
                        trade.contract.symbol,
                        trade.order.action,
                        trade.order.totalQuantity,
                    )
            else:
                logger.info("No open trades found.")
            return live_trades
        except Exception as exc:
            logger.error("Error retrieving trades: %s", exc)
            return None

    def closeTrade(self, trade) -> None:
        """Cancel an open order and wait for confirmation.

        Args:
            trade: A :class:`ib_async.Trade` object returned by :meth:`getTrades`.
        """
        self.ib.cancelOrder(trade.order)
        logger.info("Cancellation requested for order ID: %s.", trade.order.orderId)

        while trade.orderStatus.status != "Cancelled":
            self.ib.sleep(1)
            logger.debug("Order status: %s", trade.orderStatus.status)

        logger.info("Order %s successfully cancelled.", trade.order.orderId)

    def getClosingPrice(self, symbol: str) -> float | None:
        """Return the most recent daily closing price for ``symbol``.

        Requests two calendar days of daily TRADES bars so that a
        mid-session call still returns yesterday's close.

        Returns:
            The closing price as a float, or ``None`` on error.
        """
        try:
            contract = Stock(symbol, "SMART", "USD")
            qualified = self.ib.qualifyContracts(contract)

            if len(qualified) != 1:
                logger.error(
                    "Ambiguous contract for %s — found %d matches.",
                    symbol, len(qualified),
                )
                return None

            # ib_async returns the unqualified contract (conId=0) when IBKR
            # sends Error 200 "No security definition" — skip the historical
            # data request to avoid a second Error 200 and an IndexError.
            if qualified[0].conId == 0:
                logger.warning("Symbol %s not found on IBKR — no closing price.", symbol)
                return None

            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr="2 D",
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
            )
            return bars[-1].close
        except Exception as exc:
            logger.error("Error retrieving closing price for %s: %s", symbol, exc)
            return None

    def getCurrentPrice(self, symbol: str) -> float | None:
        """Return the current market price for ``symbol``.

        Tries TWS portfolio data first (already maintained by TWS, no extra
        subscription needed). Falls back to a reqTickers snapshot request.

        Returns:
            The market price as a float, or ``None`` on error.
        """
        # Primary: portfolio items carry a live marketPrice maintained by TWS.
        try:
            for item in self.ib.portfolio():
                if item.contract.symbol == symbol:
                    price = item.marketPrice
                    if price and not math.isnan(price) and price > 0:
                        logger.debug("Portfolio price for %s: %.2f", symbol, price)
                        return float(price)
        except Exception as exc:
            logger.warning("Portfolio price lookup failed for %s: %s", symbol, exc)

        # Fallback: snapshot market-data request.
        try:
            contract = Stock(symbol, "SMART", "USD")
            self.ib.qualifyContracts(contract)
            [ticker] = self.ib.reqTickers(contract)
            price = ticker.marketPrice()
            if price is None or math.isnan(price):
                logger.warning("No live price available for %s.", symbol)
                return None
            logger.debug("Snapshot price for %s: %.2f", symbol, price)
            return float(price)
        except Exception as exc:
            logger.error("Error retrieving current price for %s: %s", symbol, exc)
            return None

    def getOrderReference(self, pos) -> str | None:
        """Return the ``orderRef`` string for the trade that opened ``pos``.

        Returns:
            The order reference string, or ``None`` when not found.
        """
        all_trades = self.ib.trades()
        trade = next((t for t in all_trades if t.contract == pos.contract), None)

        if trade:
            ref = trade.order.orderRef
            logger.info("Position %s — orderRef: %s", pos.contract.symbol, ref)
            return ref

        logger.warning("No matching trade found for position %s.", pos.contract.symbol)
        return None

    def placeOrder(
        self,
        symbol: str,
        quantity: int,
        order: str,
        stop: float | None = None,
        limit: float | None = None,
        trade_strategy: str = "",
    ):
        """Place an order for the given symbol.

        Args:
            symbol:          Ticker symbol (e.g. ``"AAPL"``).
            quantity:        Positive = BUY, negative = SELL.
            order:           Order type: ``"market"``, ``"limit"``, ``"stop"``,
                             or ``"stop_limit"``.
            stop:            Stop price — required for ``stop`` and ``stop_limit``.
            limit:           Limit price — required for ``limit`` and ``stop_limit``.
            trade_strategy:  ``TradeStrategy`` value embedded in the order reference
                             (e.g. ``"PharmaDrugApproval"``).

        Returns:
            The :class:`ib_async.Trade` object, or ``None`` on error.
        """
        action = "BUY" if quantity > 0 else "SELL"
        qty = abs(quantity)
        order_type = order.lower()

        if order_type == "market":
            ib_order = MarketOrder(action, qty, tif="GTC")

        elif order_type == "limit":
            if limit is None:
                raise ValueError("'limit' price is required for a limit order.")
            ib_order = LimitOrder(action, qty, limit, outsideRth=True)

        elif order_type == "stop":
            if stop is None:
                raise ValueError("'stop' price is required for a stop order.")
            ib_order = StopOrder(action, qty, stop, outsideRth=True)

        elif order_type == "stop_limit":
            if stop is None or limit is None:
                raise ValueError("Both 'stop' and 'limit' prices are required for a stop-limit order.")
            ib_order = StopLimitOrder(action, qty, limit, stop, outsideRth=True)

        else:
            raise ValueError(
                f"Unknown order type '{order}'. Valid values: market, limit, stop, stop_limit."
            )

        ib_order.transmit = True
        ib_order.outsideRth = True
        ib_order.orderRef = (
            f"AlgoUSTrade_{trade_strategy}_{datetime.now().strftime('%Y%m%d')}"
        )

        contract = Stock(symbol, "SMART", "USD")
        self.ib.qualifyContracts(contract)

        trade = self.ib.placeOrder(contract, ib_order)
        logger.info(
            "Order placed — %s %d %s [%s] stop=%s limit=%s",
            action, qty, symbol, order_type, stop, limit,
        )
        return trade


# ---------------------------------------------------------------------------
# TradeUtils
# ---------------------------------------------------------------------------

class TradeUtils:
    """Miscellaneous shared helpers."""

    @staticmethod
    def var_is_num(value) -> bool:
        """Return ``True`` when *value* is a real number (not a bool)."""
        return isinstance(value, numbers.Number) and not isinstance(value, bool)
