"""Daily Fyers login: exchanges the one-time auth code for an access token and saves it to .env.

Needs FYERS_APP_ID, FYERS_SECRET_KEY, FYERS_REDIRECT_URI in .env. The token is written to
.env only; it is never printed. Fyers tokens expire daily, so re-run this each trading day.
"""

import re
from urllib.parse import parse_qs, urlparse

from fyers_apiv3 import fyersModel

from bot.config import ROOT, Secrets

LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

sec = Secrets()
missing = [
    n
    for n, v in [
        ("FYERS_APP_ID", sec.fyers_app_id),
        ("FYERS_SECRET_KEY", sec.fyers_secret_key),
        ("FYERS_REDIRECT_URI", sec.fyers_redirect_uri),
    ]
    if not v
]
if missing:
    raise SystemExit(f"Missing in .env: {', '.join(missing)}")

session = fyersModel.SessionModel(
    client_id=sec.fyers_app_id,
    secret_key=sec.fyers_secret_key,
    redirect_uri=sec.fyers_redirect_uri,
    response_type="code",
    grant_type="authorization_code",
)
print("1) Open this URL in your browser and log in to Fyers:\n")
print(session.generate_authcode())
print("\n2) After login the browser goes to your redirect URL (it may fail to load; fine).")
raw = input("3) Paste the FULL address-bar URL here: ").strip()
code = parse_qs(urlparse(raw).query).get("auth_code", [raw])[0]
session.set_token(code)
resp = session.generate_token()
token = resp.get("access_token")
if not token:
    raise SystemExit(f"Login failed: {resp.get('message', 'unknown error')}")

env = ROOT / ".env"
text = env.read_text() if env.exists() else ""
line = f"FYERS_ACCESS_TOKEN={token}"
text = (
    re.sub(r"^FYERS_ACCESS_TOKEN=.*$", line, text, flags=re.M)
    if "FYERS_ACCESS_TOKEN=" in text
    else text + f"\n{line}\n"
)
env.write_text(text)
env.chmod(0o600)

fy = fyersModel.FyersModel(
    client_id=sec.fyers_app_id, token=token, is_async=False, log_path=str(LOG_DIR) + "/"
)
prof = fy.get_profile()
print(
    "Login OK."
    if prof.get("s") == "ok"
    else f"Token saved but profile check failed: {prof.get('message')}"
)
