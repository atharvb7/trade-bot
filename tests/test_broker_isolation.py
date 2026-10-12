"""Rule 2: only bot/execution may import broker order functions (kiteconnect)."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "bot"
FORBIDDEN = {"kiteconnect"}


def test_only_execution_imports_broker_sdk() -> None:
    offenders = []
    for py in SRC.rglob("*.py"):
        if "execution" in py.relative_to(SRC).parts:
            continue
        for node in ast.walk(ast.parse(py.read_text())):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n.split(".")[0] in FORBIDDEN for n in names):
                offenders.append(str(py))
    assert not offenders, offenders
