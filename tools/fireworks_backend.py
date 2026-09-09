#!/usr/bin/env python3
"""Maintained Fireworks chat-completions backend for `tools.llm_client`.

Uses the existing model-command protocol: the complete canonical prompt
arrives unchanged on stdin, and one JSON object `{"text": ...}` (optionally
with `usage`/`cache`) is written to stdout on success. Credentials come from
the `FIREWORKS_API_KEY` environment variable, the same convention used by the
temporary `tmp/*/backend.py` scripts this module supersedes as the tested,
maintained entry point.

Before returning (success) or raising/exiting nonzero (failure), this backend
appends a durable usage record -- built with `tools.model_usage.build_call` --
to a match-owned usage sidecar, so `tools/game_history.py` can import exact
counts even for a reply the client discards (empty content, `finish_reason:
length`, an HTTP error, or a malformed body). The client's own generic retry
must never see an uncertain outcome as safe to repeat, so any failure here
exits nonzero with a message starting `request_unknown:` (matching the
`uncertain` markers `CommandBackend.complete` already checks for) rather than
letting an ambiguous provider failure look like a clean local rejection.

Usage sidecar convention: one JSON object per line, appended (never
truncated) to `--usage-sidecar PATH`, or `$NORRUST_USAGE_SIDECAR` if the flag
is omitted, or `./usage.ndjson` as a last-resort default so usage is always
durably recorded somewhere. Each line is `tools.model_usage.ModelCall.to_row()`
plus `{"record_kind": "dispatch"|"final"}`. A "dispatch" line is written
immediately before the network call; the "final" line -- carrying the same
`call_id` -- is written immediately after a response or error is known. The
importer UPSERTs by `(game_id, call_id)`, so a dispatch-only line (process
killed mid-request) still reports one call with unknown final usage, per the
accounting contract.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .model_usage import FIREWORKS_USAGE_MAP, ModelCall, build_call

FIREWORKS_URL = "https://api.fireworks.ai/inference/v1/chat/completions"
DEFAULT_MODEL = "accounts/fireworks/models/deepseek-v4-flash-0731"
DEFAULT_MAX_OUTPUT_TOKENS = 16384
TRANSPORT = "fireworks_chat_completions"


def _sidecar_path(explicit: str | None) -> Path:
    return Path(explicit or os.environ.get("NORRUST_USAGE_SIDECAR") or "usage.ndjson")


def _append_sidecar(path: Path, call: ModelCall, record_kind: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = call.to_row()
    row["record_kind"] = record_kind
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _allocate_call_id(game_id: str | None, prompt_sha256: str) -> str:
    # Allocated before dispatch, per the contract -- stable regardless of
    # whether the provider ever returns a response ID.
    return f"{game_id or 'unbound'}:{time.time_ns()}:{prompt_sha256[:16]}"


_UNSET = object()


def run(prompt: str, *, model: str, max_output_tokens: int, game_id: str | None,
        request_id: str | None, sidecar_path: Path,
        opener=urllib.request.urlopen, api_key: str | None = _UNSET) -> dict[str, Any]:
    """Dispatch one Fireworks chat-completions call and return the reply envelope.

    Raises on any failure (network, HTTP, empty/invalid content); the usage
    sidecar has already recorded the dispatch and final outcome by the time
    this raises, so the caller need not catch anything to preserve evidence.
    """
    prompt_sha256 = hashlib.sha256(prompt.encode()).hexdigest()
    call_id = _allocate_call_id(game_id, prompt_sha256)
    call = ModelCall(game_id=game_id or "unbound", call_id=call_id, request_id=request_id,
                      provider="fireworks", transport=TRANSPORT, requested_model=model,
                      output_limit=max_output_tokens, status="dispatched",
                      started_at=str(time.time()), source_hash=prompt_sha256)
    _append_sidecar(sidecar_path, call, "dispatch")

    payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
               "stream": False, "max_completion_tokens": max_output_tokens,
               "context_length_exceeded_behavior": "error"}
    key = api_key if api_key is not _UNSET else os.environ.get("FIREWORKS_API_KEY")
    if not key:
        final = dataclasses.replace(call, status="failed", error_code="missing_credentials",
                                     ended_at=str(time.time()))
        _append_sidecar(sidecar_path, final, "final")
        # Never dispatched to the provider: this is a locally blocked
        # request, not a physical call. The sidecar line above exists for
        # diagnosis only; game_history's importer must not turn a
        # status="failed"+error_code="missing_credentials" dispatch line
        # lacking any provider evidence into a billed call. See docs note in
        # tools/game_history.py's usage-sidecar import.
        raise RuntimeError("request_unknown: FIREWORKS_API_KEY is not set")

    started = time.monotonic()
    request = urllib.request.Request(FIREWORKS_URL, data=json.dumps(payload).encode(),
                                      headers={"Authorization": f"Bearer {key}",
                                               "Content-Type": "application/json"})
    try:
        with opener(request, timeout=840) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        final = dataclasses.replace(call, status="failed", error_code=f"http_{exc.code}",
                                     ended_at=str(time.time()),
                                     elapsed_ms=int((time.monotonic() - started) * 1000),
                                     raw_usage_json={"http_status": exc.code, "body": body[:4000]})
        _append_sidecar(sidecar_path, final, "final")
        raise RuntimeError(f"request_unknown: Fireworks HTTP {exc.code}") from exc
    except OSError as exc:
        final = dataclasses.replace(call, status="failed", error_code="transport_error",
                                     ended_at=str(time.time()),
                                     elapsed_ms=int((time.monotonic() - started) * 1000))
        _append_sidecar(sidecar_path, final, "final")
        raise RuntimeError(f"request_unknown: Fireworks transport error: {exc}") from exc

    elapsed_ms = int((time.monotonic() - started) * 1000)
    try:
        body = json.loads(raw)
        choice = body["choices"][0]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        final = dataclasses.replace(call, status="failed", error_code="malformed_response",
                                     ended_at=str(time.time()), elapsed_ms=elapsed_ms,
                                     raw_usage_json={"raw_body": raw.decode(errors="replace")[:4000]})
        _append_sidecar(sidecar_path, final, "final")
        raise RuntimeError("request_unknown: Fireworks reply was not a well-formed chat completion") from exc

    usage_raw = body.get("usage") if isinstance(body.get("usage"), dict) else None
    finish_reason = choice.get("finish_reason")
    content = choice.get("message", {}).get("content") if isinstance(choice.get("message"), dict) else None
    call_status = "completed" if isinstance(content, str) and content.strip() else "failed"
    final = build_call(game_id=game_id or "unbound", call_id=call_id, request_id=request_id,
                        provider="fireworks", transport=TRANSPORT, raw_usage=usage_raw,
                        usage_map=FIREWORKS_USAGE_MAP, status=call_status,
                        requested_model=model, reported_model=body.get("model"),
                        provider_response_id=body.get("id"), finish_reason=finish_reason,
                        output_limit=max_output_tokens, started_at=call.started_at,
                        ended_at=str(time.time()), elapsed_ms=elapsed_ms, source_hash=prompt_sha256,
                        usage_source="provider_response" if usage_raw is not None else None)
    _append_sidecar(sidecar_path, final, "final")

    if call_status == "failed":
        # This is an inference failure the client must treat as a normal
        # stop, not a transport fault to retry -- exact usage is already
        # durably recorded above regardless of what the client does next.
        raise RuntimeError(f"model_backend_failure: Fireworks returned no answer content "
                            f"(finish_reason={finish_reason})")

    text = content.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    reply: dict[str, Any] = {"text": text, "cache": {
        "requested_model": model, "runtime_model": body.get("model"),
        "requested_reasoning_effort": None, "runtime_reasoning_effort": None,
        "runtime_settings_source": "provider_response", "transport": TRANSPORT}}
    normalized = {field: getattr(final, field) for field in
                  ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens")}
    if any(value is not None for value in normalized.values()):
        reply["usage"] = normalized
    return reply


def read_request_context(path: str | None) -> dict[str, object]:
    """Read the client's per-dispatch request context, or an empty mapping.

    Absent or unreadable context must never stop a game: the call is still made
    and its usage still recorded, it simply stays unlinked to a harness request
    rather than being attributed by guesswork.
    """
    if not path:
        return {}
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    parser.add_argument("--game-id", default=os.environ.get("NORRUST_GAME_ID"))
    parser.add_argument("--request-id", default=os.environ.get("NORRUST_REQUEST_ID"))
    parser.add_argument("--request-context", default=os.environ.get("NORRUST_REQUEST_CONTEXT_FILE"),
                        help="context file the client publishes before each dispatch; supplies the "
                             "harness request identity when --request-id is not given")
    parser.add_argument("--usage-sidecar", default=None)
    args = parser.parse_args(argv)
    # The client publishes one context file per match and rewrites it before each
    # dispatch, so an adapter needs no per-call flag to know which harness
    # request it is spending against. An explicit --request-id still wins.
    context = read_request_context(args.request_context)
    if not args.request_id:
        args.request_id = context.get("harness_request_id")
    if not args.game_id:
        args.game_id = context.get("conversation_id")
    prompt = sys.stdin.read()
    sidecar = _sidecar_path(args.usage_sidecar)
    try:
        reply = run(prompt, model=args.model, max_output_tokens=args.max_output_tokens,
                    game_id=args.game_id, request_id=args.request_id, sidecar_path=sidecar)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps(reply) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
