from __future__ import annotations

from pathlib import Path


def is_killed(flag_file: Path) -> bool:
    return flag_file.exists()
