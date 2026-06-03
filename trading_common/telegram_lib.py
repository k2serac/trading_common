"""
telegram_lib.py — Telegram notification support for trading bots.

TelegramNotifier — Sends messages via the Telegram Bot API using plain HTTP.

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from environment variables.
All methods fail silently (log the error) so a Telegram outage never crashes the bot.
"""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    def __init__(
        self,
        token: str | None = None,
        chat_id: str | None = None,
        timeout: int = 10,
        enabled: bool | None = None,
    ) -> None:
        env_enabled = os.environ.get("TELEGRAM_ENABLED", "true").strip().lower()
        self._enabled = enabled if enabled is not None else (env_enabled != "false")
        self._token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        self._timeout = timeout
        if not self._enabled:
            logger.info("TelegramNotifier: disabled via TELEGRAM_ENABLED=false")
        elif not self._token or not self._chat_id:
            missing = [v for v, val in [
                ("TELEGRAM_BOT_TOKEN", self._token),
                ("TELEGRAM_CHAT_ID", self._chat_id),
            ] if not val]
            raise ValueError(
                f"TelegramNotifier is enabled but missing env var(s): {', '.join(missing)}"
            )

    def send(self, text: str) -> None:
        """Send a plain-text message. Silently logs on failure."""
        if not self._enabled or not self._token or not self._chat_id:
            return
        try:
            url = _API_BASE.format(token=self._token)
            resp = requests.post(
                url,
                json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"},
                timeout=self._timeout,
            )
            if not resp.ok:
                logger.error("Telegram send failed: %s %s", resp.status_code, resp.text)
        except Exception as exc:
            logger.error("Telegram send error: %s", exc)

    def trade_opened(
        self,
        symbol: str,
        strategy: str,
        quantity: int,
        entry_price: float,
        stop_price: float | None = None,
        bot: str = "",
    ) -> None:
        stop_line = f"\nStop:     <b>{stop_price:.4f}</b>" if stop_price else ""
        bot_line = f" [{bot}]" if bot else ""
        self.send(
            f"TRADE OPENED{bot_line}\n"
            f"Symbol:   <b>{symbol}</b>\n"
            f"Strategy: {strategy}\n"
            f"Qty:      {quantity} contract(s)\n"
            f"Entry:    <b>{entry_price:.4f}</b>"
            f"{stop_line}"
        )

    def trade_closed(
        self,
        symbol: str,
        strategy: str,
        quantity: int,
        entry_price: float,
        exit_price: float,
        pnl_pct: float | None = None,
        bot: str = "",
    ) -> None:
        pnl_line = ""
        if pnl_pct is not None:
            sign = "+" if pnl_pct >= 0 else ""
            pnl_line = f"\nPnL:      <b>{sign}{pnl_pct:.2f}%</b>"
        bot_line = f" [{bot}]" if bot else ""
        self.send(
            f"TRADE CLOSED{bot_line}\n"
            f"Symbol:   <b>{symbol}</b>\n"
            f"Strategy: {strategy}\n"
            f"Qty:      {quantity} contract(s)\n"
            f"Entry:    {entry_price:.4f}\n"
            f"Exit:     <b>{exit_price:.4f}</b>"
            f"{pnl_line}"
        )

    def alert(self, message: str, bot: str = "") -> None:
        """Generic alert — connection down, risk limit hit, etc."""
        bot_line = f" [{bot}]" if bot else ""
        self.send(f"ALERT{bot_line}\n{message}")
