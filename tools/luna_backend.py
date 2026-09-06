"""Compatibility entry point for the renamed Codex backend."""
from __future__ import annotations

import sys
from .codex_backend import *  # noqa: F401,F403
from .codex_backend import main

if __name__ == "__main__":
    raise SystemExit(main())
