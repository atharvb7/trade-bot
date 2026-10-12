"""Create the database from a clean checkout."""

from bot.config import ROOT, load_config
from bot.storage import make_session_factory

cfg = load_config()
(ROOT / "data").mkdir(exist_ok=True)
make_session_factory(cfg.app.database_url)
print("DB ready:", cfg.app.database_url)
