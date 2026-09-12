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
        events = [
            {"id": "offline-watchdog-response", "model": "offline-watchdog-player",
             "choices": [{"delta": {"reasoning_content": text}}]}
            for text in ("I am checking the current state. ", "The fixture will now finish. ")
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
        time.sleep(0.15)
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
