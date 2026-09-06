#!/usr/bin/env python3
"""Small provider-neutral file handshake for model subagents.

The client sends one complete prompt on stdin. This backend writes it unchanged
to an isolated request file and waits for a reply file containing model text.
It emits the existing ``{"text": ...}`` stdout envelope and never reads files
outside its configured directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path


def run(directory: Path, prompt: str, timeout: float = 600.0, poll: float = 0.05) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    counter = directory / "next_request"
    try:
        sequence = int(counter.read_text(encoding="utf-8")) + 1
    except (FileNotFoundError, ValueError):
        sequence = 1
    counter.write_text(str(sequence), encoding="utf-8")
    request_id = f"{sequence:06d}-{hashlib.sha256(prompt.encode()).hexdigest()[:16]}"
    prompt_path = directory / f"prompt_{request_id}.txt"
    reply_path = directory / f"reply_{request_id}.txt"
    waiting_path = directory / f"waiting_{request_id}"
    prompt_path.write_text(prompt, encoding="utf-8")
    waiting_path.write_text(json.dumps({"request_id": request_id,
                                        "prompt_bytes": len(prompt.encode()),
                                        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}),
                            encoding="utf-8")
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if reply_path.is_file():
                text = reply_path.read_text(encoding="utf-8")
                return json.dumps({"text": text}, separators=(",", ":"))
            time.sleep(poll)
    finally:
        waiting_path.unlink(missing_ok=True)
    raise TimeoutError(f"timed out waiting for {reply_path.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args(argv)
    prompt = sys.stdin.read()
    try:
        sys.stdout.write(run(args.directory, prompt, args.timeout) + "\n")
        sys.stdout.flush()
    except (OSError, TimeoutError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
