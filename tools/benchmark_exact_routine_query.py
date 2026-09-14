"""Run a bounded, read-only exact-progress routine query benchmark.

The command is intentionally protocol-level: it resumes a checkpoint, waits
for the top-level state line, and sends the same ``Query/routine_next`` payload
one or more times. It never sends an engine action or writes the checkpoint.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import select
import subprocess
import time
from pathlib import Path
from typing import Any


POLICY = {
    "holds": [1], "rally": {"col": 10, "row": 6}, "recruits": [],
    "reserve_gold": 30, "scouts": [3, 4, 5],
    "villages": [{"col": 2, "row": 4}, {"col": 5, "row": 3},
                 {"col": 6, "row": 11}, {"col": 17, "row": 2}],
}
PROGRESS = {
    "recruited": [], "scout_assignments": [], "completed_villages": [],
    "scout_ids": [3, 4, 5], "installation_id": "pol-f9e7f4ac4721",
    "policy_complete": False,
}


def digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_line(process: subprocess.Popen[str], deadline: float) -> dict[str, Any]:
    ready, _, _ = select.select([process.stdout.fileno()], [], [],
                                max(0.0, deadline - time.monotonic()))
    if not ready:
        raise TimeoutError("driver output deadline exceeded")
    line = process.stdout.readline()
    if not line:
        raise RuntimeError("driver closed stdout")
    return json.loads(line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")

    query = {"action": "Query", "what": "routine_next", "state_revision": 84,
             "policy": POLICY, "progress": PROGRESS}
    checkpoint_before = hashlib.sha256(args.checkpoint.read_bytes()).hexdigest()
    command = [str(args.binary), "--scenario", "big_battle_6",
               "--faction0", "undead", "--faction1", "undead", "--gold", "300",
               "--seed", "2038", "--llm-side", "0", "--max-turns", "6",
               "--incremental-turns", "--max-partial-batches-per-turn", "64",
               "--resume-checkpoint", str(args.checkpoint)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True)
    started = time.monotonic()
    try:
        while True:
            initial = read_line(process, started + args.timeout_seconds)
            if initial.get("type") == "state":
                break
        state_hash = digest(initial)
        replies = []
        for _ in range(args.repeats):
            sent = time.monotonic()
            process.stdin.write(json.dumps(query, separators=(",", ":")) + "\n")
            process.stdin.flush()
            reply = read_line(process, sent + args.timeout_seconds)
            if reply.get("type") != "status" or reply.get("what") != "routine_next":
                raise RuntimeError(f"unexpected routine query reply: {reply}")
            replies.append({
                "elapsed_ms": round((time.monotonic() - sent) * 1000, 1),
                "state_revision": reply.get("state_revision"),
                "body": reply.get("body"),
                "body_sha256": digest(reply.get("body")),
                "alive_after_reply": process.poll() is None,
            })
        result = {
            "binary": str(args.binary),
            "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
            "checkpoint": str(args.checkpoint),
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": hashlib.sha256(
                args.checkpoint.read_bytes()).hexdigest(),
            "checkpoint_unchanged": checkpoint_before == hashlib.sha256(
                args.checkpoint.read_bytes()).hexdigest(),
            "policy_sha256": digest(POLICY), "progress_sha256": digest(PROGRESS),
            "query_sha256": digest(query), "initial_state_revision": initial.get(
                "state_revision"), "initial_state_sha256": state_hash,
            "replies": replies,
            "same_process_body_equal": len({r["body_sha256"] for r in replies}) == 1,
            "same_process_revision_equal": len({r["state_revision"] for r in replies}) == 1,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    finally:
        process.kill()
        process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
