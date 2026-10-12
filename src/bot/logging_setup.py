"""Logging with secret redaction and a live-mode warning banner."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_SECRET_RE = re.compile(r"(api[_-]?key|secret|token|password)(\s*[=:]\s*)([^\s,;]+)", re.IGNORECASE)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _SECRET_RE.sub(r"\1\2***", str(record.getMessage()))
        record.args = None
        return True


def setup_logging(log_dir: Path, level: int = logging.INFO) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("bot")
    logger.setLevel(level)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    for h in (
        logging.StreamHandler(),
        RotatingFileHandler(log_dir / "bot.log", maxBytes=5_000_000, backupCount=5),
    ):
        h.setFormatter(fmt)
        h.addFilter(RedactingFilter())
        logger.addHandler(h)
    return logger


def log_live_banner(logger: logging.Logger) -> None:
    bar = "!" * 60
    logger.warning(bar)
    logger.warning("LIVE TRADING MODE - REAL MONEY AT RISK")
    logger.warning(bar)
