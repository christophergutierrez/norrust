"""Compatibility entry point for the renamed match reporter."""
from __future__ import annotations

from .match_report import *  # noqa: F401,F403
from .match_report import main

if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv))
