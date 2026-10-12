"""Typed configuration: YAML files for settings, .env for secrets."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


class DecisionCfg(BaseModel):
    mode: Literal["rules_only", "rules_ml", "rules_ml_jev"] = "rules_only"
    ml_min_prob: float = 0.60
    jev_min_conf: float = 0.70
    jev_min_quality: float = 1.5
    jev_max_trap: float = 0.35


class DetectorCfg(BaseModel):
    atr_stop_mult: float = 1.0
    reward_risk: float = 1.5


class MLCfg(BaseModel):
    train_months: int = 6
    val_months: int = 1
    test_months: int = 1
    min_val_candidates: int = 20  # threshold must keep at least this many on validation
    threshold_grid: list[float] = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
    seed: int = 7
    lgb_params: dict[str, float | int] = {
        "n_estimators": 200,
        "learning_rate": 0.05,
        "num_leaves": 15,
        "min_child_samples": 50,
        "subsample": 0.8,
        "subsample_freq": 1,
        "colsample_bytree": 0.8,
        "reg_lambda": 1.0,
    }


class AppCfg(BaseModel):
    timezone: str = "Asia/Kolkata"
    database_url: str = "sqlite:///data/bot.db"
    log_dir: str = "logs"
    live_confirmation_file: str = "config/LIVE_CONFIRMED"
    kill_switch_file: str = "config/KILL"
    starting_capital: float = 1000
    stale_feed_seconds: int = 60
    timeframes: list[str] = ["1m", "5m"]
    bar_minutes: int = 5  # detector timeframe; see docs/experiments/2026-10-12-timeframe.md
    decision: DecisionCfg = DecisionCfg()
    ml: MLCfg = MLCfg()
    detectors: DetectorCfg = DetectorCfg()


class RiskCfg(BaseModel):
    risk_per_trade_pct: float = 1.0
    max_position_value_pct_of_cash: float = 100
    max_daily_loss_pct: float = 3.0
    max_trades_per_day: int = 3
    max_open_positions: int = 1
    max_consecutive_losses: int = 2
    no_entry_before: str = "09:30"
    no_entry_after: str = "14:45"
    square_off_time: str = "15:10"
    min_edge_cost_multiple: float = 3.0
    leverage: float = 1


class CostsCfg(BaseModel):
    brokerage_pct: float
    brokerage_cap_per_order: float
    stt_sell_pct: float
    exchange_txn_pct: float
    sebi_pct: float
    stamp_buy_pct: float
    gst_pct: float
    slippage_pct: float


class WatchlistCfg(BaseModel):
    symbols: list[str]
    index: str = "NIFTY 50"


class Secrets(BaseSettings):
    """Loaded from environment / .env. Never log these."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    trading_mode: Literal["paper", "live"] = "paper"
    kite_api_key: str = ""
    kite_api_secret: str = ""
    kite_access_token: str = ""
    typesafe_api_key: str = ""
    fyers_app_id: str = ""
    fyers_secret_key: str = ""
    fyers_redirect_uri: str = ""
    fyers_access_token: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    def __repr__(self) -> str:
        return "Secrets(<redacted>)"

    __str__ = __repr__


def _load(name: str, config_dir: Path) -> dict[str, object]:
    with open(config_dir / name) as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


class Config(BaseModel):
    app: AppCfg
    risk: RiskCfg
    costs: CostsCfg
    watchlist: WatchlistCfg

    def is_live_allowed(self, secrets: Secrets) -> bool:
        """Live only if TRADING_MODE=live AND the confirmation flag file exists."""
        flag = ROOT / self.app.live_confirmation_file
        return secrets.trading_mode == "live" and flag.exists()


def load_config(config_dir: Path = CONFIG_DIR) -> Config:
    return Config(
        app=AppCfg(**_load("settings.yaml", config_dir)),
        risk=RiskCfg(**_load("risk.yaml", config_dir)),
        costs=CostsCfg(**_load("costs.yaml", config_dir)),
        watchlist=WatchlistCfg(**_load("watchlist.yaml", config_dir)),
    )
