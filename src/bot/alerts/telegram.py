"""Telegram notifier and /kill command. The token is never logged or put in a message."""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger("bot.alerts")
API = "https://api.telegram.org/bot{}/{}"


class Telegram:
    def __init__(self, token: str, chat_id: str, kill_file: Path) -> None:
        self._token, self._chat, self._kill = token, str(chat_id), kill_file
        self._offset = 0

    def _call(self, method: str, **params: object) -> dict[str, object]:
        data = urllib.parse.urlencode(params).encode()
        with urllib.request.urlopen(API.format(self._token, method), data=data, timeout=10) as r:
            reply: dict[str, object] = json.loads(r.read())
            return reply

    def send(self, text: str) -> None:
        """Best effort: an alert that fails must never stop the trading loop."""
        try:
            self._call("sendMessage", chat_id=self._chat, text=text[:4000])
        except Exception as err:  # noqa: BLE001
            log.warning("telegram send failed: %s", type(err).__name__)

    def poll_kill(self) -> bool:
        """Create the kill-switch file if the configured chat sent /kill. True if it did."""
        try:
            reply = self._call("getUpdates", offset=self._offset, timeout=0)
        except Exception as err:  # noqa: BLE001
            log.warning("telegram poll failed: %s", type(err).__name__)
            return False
        hit = False
        updates = reply.get("result")
        for upd in updates if isinstance(updates, list) else []:
            self._offset = max(self._offset, int(upd.get("update_id", 0)) + 1)
            msg = upd.get("message") or {}
            same_chat = str((msg.get("chat") or {}).get("id")) == self._chat
            if same_chat and str(msg.get("text", "")).strip().lower().startswith("/kill"):
                hit = True
        if hit:
            self._kill.parent.mkdir(parents=True, exist_ok=True)
            self._kill.touch()
        return hit
