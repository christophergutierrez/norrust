"""Legacy command alias selecting the explicit luna-high Codex preset."""
from __future__ import annotations

if __package__:
    from .codex_backend import cli
else:
    from codex_backend import cli

if __name__ == "__main__":
    raise SystemExit(cli(default_preset="luna-high"))
