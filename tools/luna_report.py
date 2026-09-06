"""Compatibility entry point for the renamed match reporter."""
from __future__ import annotations

import sys

if __package__:
    from .match_report import main
else:
    from match_report import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
