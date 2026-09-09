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
from datetime import datetime, timezone
from pathlib import Path



def request_context() -> dict[str, object]:
    """Read the harness request context the client published for this dispatch.

    Absent or unreadable context is not an error: the transport still works, the
    handshake simply records no harness identity and any host usage collected
    against it stays unlinked rather than being guessed.
    """
    path = os.environ.get("NORRUST_REQUEST_CONTEXT_FILE")
    if not path:
        return {}
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    keep = ("harness_request_id", "request_sequence", "conversation_id", "side",
            "side_turn_id", "state_revision", "requested_model",
            "requested_reasoning_effort", "dispatched_at")
    return {key: value[key] for key in keep if key in value}


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
    # The transport's own request_id is a sequence plus prompt hash; it is NOT
    # the harness request ID that owns the spending. When the client publishes a
    # request context, carry that ID and the handshake timestamps into the
    # waiting record, so host inference calls can be attributed to the request
    # whose prompt was open at the time. That is proven handshake ordering, not
    # timestamp proximity: this transport blocks until the reply appears, so at
    # most one harness request is open at once.
    handshake = {"request_id": request_id,
                 "prompt_bytes": len(prompt.encode()),
                 "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                 "published_at": datetime.now(timezone.utc).isoformat()}
    handshake.update(request_context())
    waiting_path.write_text(json.dumps(handshake, sort_keys=True), encoding="utf-8")
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if reply_path.is_file():
                text = reply_path.read_text(encoding="utf-8")
                # Durable close of the handshake window. Everything the host
                # inferred between published_at and answered_at belongs to this
                # harness request; a collector reconciles by recorded identity
                # and event order within that window.
                record = dict(handshake, answered_at=datetime.now(timezone.utc).isoformat(),
                              reply_bytes=len(text.encode()))
                with (directory / "handshake_log.ndjson").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, sort_keys=True) + "\n")
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
