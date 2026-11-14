"""Run the paper-trading loop (news gap fade). Paper only: there is no live broker yet.

Needs a fresh FYERS_ACCESS_TOKEN in .env (run scripts/fyers_login.py each morning before
09:00; the token expires daily). Stop it with the kill switch: create config/KILL, or send
/kill to the Telegram bot. Usage: python scripts/run_paper.py
"""

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.alerts.telegram import Telegram
from bot.config import ROOT, Secrets, load_config
from bot.data.fyers_provider import FyersProvider
from bot.data.live import LiveMarketData
from bot.logging_setup import setup_logging
from bot.runner import PaperRunner
from bot.storage import make_session_factory

STEP_SECONDS = 20

os.chdir(ROOT)  # the database URL and log directory are relative to the project root
cfg, sec = load_config(), Secrets()
log = setup_logging(ROOT / cfg.app.log_dir)
if sec.trading_mode != "paper":
    raise SystemExit("TRADING_MODE is not 'paper'. This script only paper trades.")
if not (sec.fyers_app_id and sec.fyers_access_token):
    raise SystemExit("Set FYERS_APP_ID and FYERS_ACCESS_TOKEN in .env first.")

kill_file = ROOT / cfg.app.kill_switch_file
fyers = FyersProvider(sec.fyers_app_id, sec.fyers_access_token, pause_s=1.3)  # 50 requests/min
data = LiveMarketData(fyers, ROOT / "data" / "raw" / "bhavcopy")
telegram = None
if sec.telegram_bot_token and sec.telegram_chat_id:
    telegram = Telegram(sec.telegram_bot_token, sec.telegram_chat_id, kill_file)
runner = PaperRunner(
    cfg,
    data,
    make_session_factory(cfg.app.database_url),
    kill_file,
    telegram.send if telegram else None,
)
log.info("paper runner started, equity %.2f", runner.equity)
zone = ZoneInfo(cfg.app.timezone)
while True:
    if telegram:
        telegram.poll_kill()
    if not runner.step(datetime.now(zone).replace(tzinfo=None)):
        log.warning("kill switch: runner stopped")
        break
    time.sleep(STEP_SECONDS)
