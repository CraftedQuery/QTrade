"""Operator kill switch: environment variable or flag file."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

KILL_SWITCH_ENV = "LAB_KILL_SWITCH"
KILL_SWITCH_PATH_ENV = "LAB_KILL_SWITCH_PATH"
_ENGAGED = frozenset({"1", "true", "yes", "on", "engaged"})


def kill_switch_engaged(
    env: Mapping[str, str] | None = None,
    path: Path | None = None,
) -> bool:
    """Return whether the operator has engaged the kill switch.

    ``LAB_KILL_SWITCH`` wins when set. Otherwise a flag file is consulted:
    an empty file or a first line in ``{1,true,yes,on,engaged}`` means halt.
    """
    mapping = os.environ if env is None else env
    raw = mapping.get(KILL_SWITCH_ENV, "").strip().lower()
    if raw:
        return raw in _ENGAGED
    flag = path
    if flag is None:
        configured = mapping.get(KILL_SWITCH_PATH_ENV, "").strip()
        flag = Path(configured) if configured else None
    if flag is None or not flag.is_file():
        return False
    text = flag.read_text(encoding="utf-8")
    if text.strip() == "":
        return True
    first = text.splitlines()[0].strip().lower()
    return first in _ENGAGED


__all__ = ["KILL_SWITCH_ENV", "KILL_SWITCH_PATH_ENV", "kill_switch_engaged"]
