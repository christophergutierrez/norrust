"""Offline streaming player: exercises the maintained Fireworks adapter, no network."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

from tools import fireworks_backend as backend


class Stream:
    headers = {}

    def __init__(self):
        reply = '{"actions":[{"action":"Resign"}]}'
        if os.environ.get("NORRUST_WATCHDOG_REPEAT_REASONING") == "1":
            # Keep the provider open after the detector sees the second copy.
            # This is deliberately opt-in so the fixture remains a normal
            # streaming player for recorder-only tests.
            repeated = (
                "The same bounded investigation remains unresolved across the "
                "current state snapshot; I will compare the committed action "
                "and request identity before deciding whether to finish. "
            )
            reasoning = (repeated,) * 150 + ("The fixture will now finish. ",)
        else:
            reasoning = ("I am checking the current state. ",
                         "The fixture will now finish. ")
        events = [
            {"id": "offline-watchdog-response", "model": "offline-watchdog-player",
             "choices": [{"delta": {"reasoning_content": text}}]}
            for text in reasoning
        ]
        events += [{"choices": [{"delta": {"content": reply}, "finish_reason": "stop"}]},
                   {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                                               "total_tokens": 120}}]
        self.chunks = iter([(f"data: {json.dumps(event)}\n\n").encode() for event in events]
                           + [b"data: [DONE]\n\n"])

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read1(self, _size):
        time.sleep(0.2 if os.environ.get("NORRUST_WATCHDOG_REPEAT_REASONING") == "1" else 0.15)
        return next(self.chunks, b"")


def main():
    context = backend.read_request_context(os.environ.get("NORRUST_REQUEST_CONTEXT_FILE"))
    prompt = sys.stdin.read()
    reply = backend.run(
        prompt, model="offline-watchdog-player", max_output_tokens=512,
        game_id=context["conversation_id"], request_id=context["harness_request_id"],
        sidecar_path=Path(context["game_log"]).parent / "usage.ndjson",
        opener=lambda *_args, **_kwargs: Stream(), api_key="offline-fixture-key",
        stream=True, evidence_dir=Path(os.environ["NORRUST_EVIDENCE_DIR"]),
        request_context=context)
    print(json.dumps(reply))


if __name__ == "__main__":
    main()
