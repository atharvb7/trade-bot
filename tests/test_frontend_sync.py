"""The website's trade ticket mirrors config by hand; fail if it drifts from the YAML files."""

import re

from bot.config import ROOT, load_config

HOME_JS = ROOT / "frontend" / "assets" / "js" / "home.js"


def _js_object(src: str, name: str) -> dict[str, float]:
    m = re.search(rf"var {name} = \{{(.*?)\}};", src, re.S)
    assert m, f"{name} not found in home.js"
    return {k: float(v) for k, v in re.findall(r"(\w+):\s*(-?[\d.]+)", m.group(1))}


def test_ticket_costs_match_costs_yaml() -> None:
    js = _js_object(HOME_JS.read_text(), "COSTS")
    assert js == load_config().costs.model_dump()


def test_ticket_risk_and_capital_match_config() -> None:
    src = HOME_JS.read_text()
    cfg = load_config()
    js = _js_object(src, "RISK")
    assert js == {k: float(getattr(cfg.risk, k)) for k in js}
    m = re.search(r"var CAPITAL = ([\d.]+);", src)
    assert m and float(m.group(1)) == cfg.app.starting_capital
