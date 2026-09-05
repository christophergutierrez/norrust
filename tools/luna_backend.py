#!/usr/bin/env python3
"""Small, restricted Luna adapter for repeatable headless matches.

The client supplies one complete game prompt on stdin.  The adapter runs one
Codex decision with no project tools and returns the command-backend envelope.
Conversation continuity is supplied by the client as bounded explicit context.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    prompt = sys.stdin.read()
    effort = os.environ.get("NORRUST_REASONING_EFFORT", "high")
    instruction = (
        "You are the Luna player in a Norrust match. Return JSON only: either "
        "the legal action array, an {actions,intent} envelope, or one read-only "
        "tool request allowed by the game prompt. Treat the current game prompt "
        "as authoritative. Use the existing tactical surface, protect the "
        "recruiter, coordinate the whole army, and consider all useful remaining "
        "units before EndTurn. In incremental mode, partial actions may omit "
        "EndTurn. Do not use shell, web, files, skills, or unrelated tools.\n\n"
        "GAME PROMPT:\n" + prompt
    )
    command = [
        "codex", "exec", "--ephemeral", "--ignore-user-config", "--ignore-rules",
        "--skip-git-repo-check", "--sandbox", "read-only", "--model", "gpt-5.6-luna",
        "--color", "never", "-c", f"model_reasoning_effort={effort}", instruction,
    ]
    result = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=840)
    if result.returncode:
        print(result.stderr[-2000:], file=sys.stderr)
        return result.returncode
    text = result.stdout.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    json.loads(text)
    sys.stdout.write(json.dumps({"text": text}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
