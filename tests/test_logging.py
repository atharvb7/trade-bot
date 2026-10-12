import logging
from pathlib import Path

from bot.logging_setup import setup_logging


def test_redacts_secrets(tmp_path: Path) -> None:
    log = setup_logging(tmp_path)
    log.info("calling with api_key=abc123XYZ and token: tok999")
    for h in log.handlers:
        h.flush()
    text = (tmp_path / "bot.log").read_text()
    assert "abc123XYZ" not in text and "tok999" not in text
    assert "***" in text
    logging.getLogger("bot").handlers.clear()
