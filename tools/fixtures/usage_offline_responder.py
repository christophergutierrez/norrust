#!/usr/bin/env python3
"""Offline model-command fixture for real-driver usage-accounting tests.

Reads the complete prompt on stdin (as `tools/llm_client.py`'s CommandBackend
protocol requires), always replies with a legal `EndTurn`, and appends a
dispatch + final usage-sidecar record for the call, using the same shape
`tools/fireworks_backend.py` writes. No network access -- this is a synthetic
provider fixture for CI, not a live backend.

Env vars (set by the test): NORRUST_USAGE_SIDECAR (sidecar path),
NORRUST_FIXTURE_GAME_ID (game id to stamp on each call).
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.model_usage import ModelCall  # noqa: E402


def main() -> int:
    prompt = sys.stdin.read()
    sidecar = Path(os.environ["NORRUST_USAGE_SIDECAR"])
    game_id = os.environ.get("NORRUST_FIXTURE_GAME_ID", "unbound")
    counter_path = sidecar.parent / "usage_offline_responder_counter"
    sequence = int(counter_path.read_text()) + 1 if counter_path.is_file() else 1
    counter_path.write_text(str(sequence))
    call_id = f"{game_id}:offline:{sequence}"
    prompt_sha256 = hashlib.sha256(prompt.encode()).hexdigest()

    def append(call: ModelCall, record_kind: str) -> None:
        row = call.to_row()
        row["record_kind"] = record_kind
        with sidecar.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")

    dispatched = ModelCall(game_id=game_id, call_id=call_id, provider="offline_fixture",
                           transport="offline_fixture", status="dispatched",
                           started_at=str(time.time()), source_hash=prompt_sha256)
    append(dispatched, "dispatch")
    final = ModelCall(game_id=game_id, call_id=call_id, provider="offline_fixture",
                      transport="offline_fixture", status="completed", finish_reason="stop",
                      ended_at=str(time.time()), source_hash=prompt_sha256,
                      input_tokens=len(prompt), output_tokens=1, usage_source="fixture")
    append(final, "final")

    print(json.dumps({"text": json.dumps([{"action": "EndTurn"}])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
