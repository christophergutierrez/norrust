#!/usr/bin/env python3
"""Deterministic fake backend transport for strategy decision fixtures.

Reads the prompt from stdin, logs it to an append-only ndjson log, resolves
template placeholders (such as '__FROM_PROMPT__' for decision_id), and returns
the canned model response with valid usage metadata.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="Deterministic fake backend transport")
  parser.add_argument("--responses", required=True, help="Path to JSON file containing list of canned response objects")
  parser.add_argument("--request-log", help="Path to ndjson log for recorded requests")
  args = parser.parse_args(argv)

  responses_path = Path(args.responses).resolve()
  if not responses_path.is_file():
    print(f"error: response file not found: {responses_path}", file=sys.stderr)
    return 1

  log_path = Path(args.request_log).resolve() if args.request_log else responses_path.with_name("requests.ndjson")
  log_path.parent.mkdir(parents=True, exist_ok=True)

  prompt = sys.stdin.read()
  with log_path.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"prompt": prompt}) + "\n")

  data = json.loads(responses_path.read_text(encoding="utf-8"))
  if isinstance(data, dict) and "fake_responses" in data:
    responses = data["fake_responses"]
  elif isinstance(data, list):
    responses = data
  else:
    responses = [data]
  call_count = sum(1 for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip())
  index = max(0, call_count - 1)
  raw_response = responses[min(index, len(responses) - 1)]
  response = dict(raw_response)

  if response.get("kind") == "choose" and response.get("decision_id") == "__FROM_PROMPT__":
    match = re.search(r'"decision_id":\s*"([^"]+)"', prompt)
    if match:
      response["decision_id"] = match.group(1)

  response_text = json.dumps(response, separators=(",", ":"))
  reply = {
    "text": response_text,
    "usage": {
      "input_tokens": max(10, len(prompt) // 4),
      "output_tokens": max(5, len(response_text) // 4),
      "reasoning_tokens": 0,
    },
  }
  print(json.dumps(reply, separators=(",", ":")))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
