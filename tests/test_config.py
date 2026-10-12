from pathlib import Path

from bot.config import Secrets, load_config


def test_config_loads() -> None:
    cfg = load_config()
    assert cfg.app.starting_capital == 1000
    assert cfg.app.decision.mode == "rules_only"
    assert cfg.risk.max_open_positions == 1
    assert cfg.risk.leverage == 1
    assert "NTPC" in cfg.watchlist.symbols


def test_paper_is_default(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("TRADING_MODE", raising=False)
    assert Secrets(_env_file=None).trading_mode == "paper"  # type: ignore[call-arg]


def test_live_requires_flag_file(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    cfg = load_config()
    cfg.app.live_confirmation_file = "config/__no_such_flag__"
    monkeypatch.setenv("TRADING_MODE", "live")
    assert cfg.is_live_allowed(Secrets(_env_file=None)) is False  # type: ignore[call-arg]


def test_secrets_never_repr(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("KITE_API_KEY", "supersecret123")
    s = Secrets(_env_file=None)  # type: ignore[call-arg]
    assert "supersecret123" not in repr(s)
    assert "supersecret123" not in str(s)
