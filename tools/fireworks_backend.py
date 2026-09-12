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
length`, an HTTP error, or a malformed body). Output exhaustion returns a typed
`error.code=output_limit` envelope for the shared harness policy; partial text
is never executable. Other failures exit with `request_unknown:` so they are
not mistaken for safe, generic transport retries.

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
import base64
import codecs
import dataclasses
import hashlib
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .model_usage import FIREWORKS_USAGE_MAP, ModelCall, build_call, TOKEN_FIELDS
from .output_limits import INITIAL_OUTPUT_LIMIT, MAX_OUTPUT_LIMIT

FIREWORKS_URL = "https://api.fireworks.ai/inference/v1/chat/completions"
DEFAULT_MODEL = "accounts/fireworks/models/deepseek-v4-flash-0731"
TRANSPORT = "fireworks_chat_completions"

# Verified 2026-09-11 against three sources: the Z.ai GLM-5.3-Flash model
# card (https://huggingface.co/zai-org/GLM-5.3-Flash) -- "GLM-5.3-Flash
# supports controlling the thinking budget through the `reasoning_effort`
# parameter, which accepts three levels: `low`, `high`, and `max`. It
# defaults to `max` if not passed (or if set to any other value)."; the
# vLLM recipe (https://recipes.vllm.ai/zai-org/GLM-5.3-Flash), which
# confirms the same three levels and that "the chat template resolves
# effort to max unless reasoning_effort is explicitly low or high"; and
# Fireworks' reasoning guide plus API reference
# (https://docs.fireworks.ai/guides/reasoning,
# https://docs.fireworks.ai/api-reference/post-chatcompletions), which pass
# `reasoning_effort` straight through to the served model and document no
# response field reporting which effort was actually applied.
#
# Fireworks' own generic `reasoning_effort` surface additionally lists
# "medium" for other reasoning models, but GLM-5.3-Flash's chat template
# would silently resolve any value outside {low, high, max} to max. Sending
# such a value here would be exactly the silent nearby-value mapping this
# adapter must not perform, so only the model's own three documented levels
# are accepted.
SUPPORTED_REASONING_EFFORTS = ("low", "high", "max")


class UnsupportedReasoningEffort(ValueError):
    """An explicitly requested reasoning effort this adapter will not send.

    Raised before any network call -- never silently remapped to a nearby
    supported value.
    """


def endpoint_url() -> str:
    """Return the provider endpoint, with a local-test override only."""
    return os.environ.get("NORRUST_FIREWORKS_URL", FIREWORKS_URL)


class StreamProtocolError(RuntimeError):
    """The provider ended a stream without a trustworthy completion."""


def _json_file(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8")


class _EvidenceRecorder:
    """Small append-and-flush recorder for one physical provider call."""

    def __init__(self, root: Path | None, call_id: str, prompt: str,
                 payload: dict[str, Any], request_context: dict[str, object] | None):
        self.path: Path | None = None
        self._chunks = None
        self._sequence = 0
        if root is None:
            return
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", call_id)
        self.path = root / safe_id
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "prompt.txt").write_text(prompt, encoding="utf-8")
        (self.path / "prompt.sha256").write_text(
            hashlib.sha256(prompt.encode()).hexdigest() + "\n", encoding="ascii")
        _json_file(self.path / "payload.json", payload)
        _json_file(self.path / "request_context.json", request_context or {})
        self._chunks = (self.path / "chunks.ndjson").open("a", encoding="utf-8")

    def chunk(self, raw: bytes) -> None:
        if self._chunks is None:
            return
        self._chunks.write(json.dumps({
            "sequence": self._sequence,
            "data_b64": base64.b64encode(raw).decode("ascii"),
            "received_at": str(time.time()),
        }, sort_keys=True) + "\n")
        self._sequence += 1
        self._chunks.flush()

    def receipt(self, filename: str, value: dict[str, Any]) -> None:
        if self.path is not None:
            _json_file(self.path / filename, value)
        if self._chunks is not None:
            self._chunks.close()
            self._chunks = None


def _read_response_chunk(response: Any) -> bytes:
    """Read one bounded response chunk without assuming read() is incremental."""
    reader = getattr(response, "read1", None)
    if callable(reader):
        return reader(4096)
    reader = getattr(response, "read")
    try:
        return reader(4096)
    except TypeError:
        return reader()


def _iter_sse_events(response: Any, recorder: _EvidenceRecorder):
    """Yield JSON data-only SSE frames, preserving UTF-8 across reads."""
    decoder = codecs.getincrementaldecoder("utf-8")()
    pending = ""
    while True:
        raw = _read_response_chunk(response)
        if not raw:
            break
        if not isinstance(raw, bytes):
            raise StreamProtocolError("response chunk was not bytes")
        recorder.chunk(raw)
        try:
            pending += decoder.decode(raw, final=False)
        except UnicodeDecodeError as exc:
            raise StreamProtocolError("stream contained invalid UTF-8") from exc
        while True:
            match = re.search(r"\r?\n\r?\n", pending)
            if match is None:
                break
            frame, pending = pending[:match.start()], pending[match.end():]
            lines = frame.splitlines()
            data = []
            saw_data = False
            for line in lines:
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    raise StreamProtocolError("stream frame was not data-only")
                saw_data = True
                data.append(line[5:].lstrip(" "))
            if not saw_data:
                continue
            value = "\n".join(data)
            if value == "[DONE]":
                yield None
                continue
            try:
                event = json.loads(value)
            except (TypeError, ValueError) as exc:
                raise StreamProtocolError("stream data was not valid JSON") from exc
            if not isinstance(event, dict):
                raise StreamProtocolError("stream data was not an object")
            if isinstance(event.get("error"), dict):
                message = event["error"].get("message", "provider stream error")
                raise StreamProtocolError(str(message))
            yield event
    try:
        pending += decoder.decode(b"", final=True)
    except UnicodeDecodeError as exc:
        raise StreamProtocolError("stream ended in an incomplete UTF-8 sequence") from exc
    if pending.strip():
        raise StreamProtocolError("stream ended with an incomplete SSE frame")


def validate_reasoning_effort(reasoning_effort: str | None) -> None:
    """Reject an unsupported effort honestly before any network call.

    `None` means the option was omitted -- the payload then carries no
    `reasoning_effort` field at all, byte-identical to before this option
    existed, so the provider/model applies its own documented default.
    """
    if reasoning_effort is not None and reasoning_effort not in SUPPORTED_REASONING_EFFORTS:
        raise UnsupportedReasoningEffort(
            f"unsupported reasoning_effort {reasoning_effort!r}; "
            f"supported values are {SUPPORTED_REASONING_EFFORTS}")


def _stream_payload(model: str, prompt: str, max_output_tokens: int,
                    reasoning_effort: str | None = None) -> dict[str, Any]:
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
               "stream": True, "stream_options": {"include_usage": True},
               "max_completion_tokens": max_output_tokens,
               "context_length_exceeded_behavior": "error"}
    if reasoning_effort is not None:
        payload["reasoning_effort"] = reasoning_effort
    return payload


def _reply_from_final(content: str, call: ModelCall, final: ModelCall,
                  model: str, reported_model: Any, session_affinity: str | None,
                  finish_reason: str, reasoning_effort: str | None = None) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    reply: dict[str, Any] = {"text": text, "cache": {
        "requested_model": model, "runtime_model": reported_model,
        # Requested is exactly what we sent (or None/unknown if the option
        # was omitted and the provider/model default applied instead).
        # Fireworks' chat-completions response schema reports no field for
        # the effort actually applied (verified 2026-09-11 against
        # docs.fireworks.ai/api-reference/post-chatcompletions), so runtime
        # stays unknown (None) regardless of what was requested -- this
        # adapter never claims a runtime effort the provider did not report.
        "requested_reasoning_effort": reasoning_effort, "runtime_reasoning_effort": None,
        "runtime_settings_source": "provider_response", "transport": TRANSPORT,
        "session_affinity": session_affinity,
        "prompt_layout_version": call.prompt_layout_version,
        "session_affinity_status": "sent" if session_affinity else "unavailable"}}
    normalized = {field: getattr(final, field) for field in TOKEN_FIELDS}
    if any(value is not None for value in normalized.values()):
        reply["usage"] = normalized
    if finish_reason == "length":
        reply["error"] = {"code": "output_limit", "output_limit": call.output_limit,
                           "call_id": call.call_id}
    return reply


def _run_stream(prompt: str, *, model: str, max_output_tokens: int, game_id: str | None,
                request_id: str | None, sidecar_path: Path, call: ModelCall,
                payload: dict[str, Any], key: str, opener: Any,
                session_affinity: str | None, prompt_layout_version: str | None,
                request_context: dict[str, object] | None,
                evidence: _EvidenceRecorder, timeout: float,
                reasoning_effort: str | None = None) -> dict[str, Any]:
    started = time.monotonic()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if session_affinity:
        headers["x-session-affinity"] = session_affinity
    request = urllib.request.Request(endpoint_url(), data=json.dumps(payload).encode(), headers=headers)
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    usage_raw: dict[str, Any] | None = None
    response_id = None
    reported_model = None
    finish_reason = None
    saw_done = False
    response_headers = None
    header_counts: dict[str, int] = {}
    header_names: dict[str, str] = {}

    def fail(code: str, message: str) -> None:
        raw = dict(usage_raw) if usage_raw else None
        final = build_call(
            game_id=game_id or "unbound", call_id=call.call_id, request_id=request_id,
            provider="fireworks", transport=TRANSPORT, raw_usage=raw,
            usage_map=FIREWORKS_USAGE_MAP, status="failed", requested_model=model,
            reported_model=reported_model, provider_response_id=response_id,
            retry_of_call_id=call.retry_of_call_id,
            finish_reason=finish_reason, output_limit=max_output_tokens,
            started_at=call.started_at, ended_at=str(time.time()),
            elapsed_ms=int((time.monotonic() - started) * 1000), source_hash=call.source_hash,
            requested_affinity=session_affinity, prompt_layout_version=prompt_layout_version,
            usage_source="provider_response" if raw is not None else None, error_code=code,
            requested_reasoning_effort=reasoning_effort)
        _append_sidecar(sidecar_path, final, "final")
        evidence.receipt("incomplete.json", {
            "status": "incomplete", "error_code": code, "message": message,
            "response_id": response_id, "reported_model": reported_model,
            "finish_reason": finish_reason, "saw_done": saw_done,
            "content": "".join(content_parts), "reasoning_content": "".join(reasoning_parts),
            "usage": usage_raw,
        })
        raise RuntimeError(f"request_unknown: {message}")

    try:
        with opener(request, timeout=timeout) as response:
            response_headers = getattr(response, "headers", None)
            for event in _iter_sse_events(response, evidence):
                if event is None:
                    saw_done = True
                    break
                if isinstance(event.get("id"), str):
                    response_id = event["id"]
                if isinstance(event.get("model"), str):
                    reported_model = event["model"]
                if isinstance(event.get("usage"), dict):
                    usage_raw = dict(event["usage"])
                choices = event.get("choices")
                if not isinstance(choices, list):
                    raise StreamProtocolError("stream chunk choices was not an array")
                if finish_reason is not None:
                    # Once a choice has declared its finish, the provider may
                    # still send the documented empty usage chunk, followed by
                    # [DONE]. Any further choice/delta would append text after
                    # the finish marker and could turn a partial JSON answer
                    # into executable orders.
                    if choices or not isinstance(event.get("usage"), dict):
                        raise StreamProtocolError(
                            "stream emitted choice data after finish_reason")
                    continue
                if len(choices) > 1:
                    raise StreamProtocolError("stream returned multiple choices")
                if choices:
                    choice = choices[0]
                    if not isinstance(choice, dict):
                        raise StreamProtocolError("stream choice was not an object")
                    if choice.get("finish_reason") is not None:
                        finish_reason = choice["finish_reason"]
                    delta = choice.get("delta")
                    if delta is not None and not isinstance(delta, dict):
                        raise StreamProtocolError("stream delta was not an object")
                    if isinstance(delta, dict):
                        if isinstance(delta.get("content"), str):
                            content_parts.append(delta["content"])
                        if isinstance(delta.get("reasoning_content"), str):
                            reasoning_parts.append(delta["reasoning_content"])
                    elif isinstance(choice.get("message"), dict):
                        message = choice["message"]
                        if isinstance(message.get("content"), str):
                            content_parts.append(message["content"])
                        if isinstance(message.get("reasoning_content"), str):
                            reasoning_parts.append(message["reasoning_content"])
            if not saw_done:
                fail("stream_missing_done", "Fireworks stream ended before [DONE]")
            if finish_reason is None:
                fail("stream_missing_finish", "Fireworks stream ended without finish_reason")
            if response_headers is not None:
                if usage_raw is not None and "prompt_cache_hit_tokens" not in usage_raw:
                    details = usage_raw.get("prompt_tokens_details")
                    if isinstance(details, dict) and "cached_tokens" in details:
                        usage_raw["prompt_cache_hit_tokens"] = details["cached_tokens"]
                header_evidence = {}
                for header, field in (("fireworks-prompt-tokens", "prompt_tokens"),
                                      ("fireworks-cached-prompt-tokens", "prompt_cache_hit_tokens")):
                    value = response_headers.get(header) if hasattr(response_headers, "get") else None
                    if value is not None:
                        header_evidence[header] = value
                        if isinstance(value, str) and value.isdecimal():
                            header_counts[field] = int(value)
                            header_names[field] = header
                            if usage_raw is None:
                                usage_raw = {}
                            usage_raw.setdefault(field, int(value))
                if header_evidence:
                    if usage_raw is None:
                        usage_raw = {}
                    usage_raw["fireworks_response_headers"] = header_evidence
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        evidence.receipt("incomplete.json", {"status": "http_error", "http_status": exc.code,
                                              "body": body[:4000]})
        final = dataclasses.replace(call, status="failed", error_code=f"http_{exc.code}",
                                    ended_at=str(time.time()),
                                    elapsed_ms=int((time.monotonic() - started) * 1000),
                                    raw_usage_json={"http_status": exc.code, "body": body[:4000]})
        _append_sidecar(sidecar_path, final, "final")
        raise RuntimeError(f"request_unknown: Fireworks HTTP {exc.code}") from exc
    except StreamProtocolError as exc:
        fail("stream_incomplete", str(exc))
    except http.client.IncompleteRead as exc:
        if exc.partial:
            evidence.chunk(exc.partial)
        fail("transport_error", f"Fireworks stream interrupted: {exc}")
    except (OSError, http.client.HTTPException) as exc:
        fail("transport_error", f"Fireworks transport error: {exc}")

    if finish_reason not in {"stop", "length"}:
        fail("stream_invalid_finish", f"Fireworks stream returned unsupported finish_reason={finish_reason}")
    if finish_reason != "length" and not "".join(content_parts).strip():
        fail("stream_empty_content", "Fireworks stream returned empty content")

    raw = dict(usage_raw) if usage_raw else None
    if raw is not None and "prompt_tokens_details" in raw and "prompt_cache_hit_tokens" not in raw:
        details = raw.get("prompt_tokens_details")
        if isinstance(details, dict) and "cached_tokens" in details:
            raw["prompt_cache_hit_tokens"] = details["cached_tokens"]
    final = build_call(
        game_id=game_id or "unbound", call_id=call.call_id, request_id=request_id,
        provider="fireworks", transport=TRANSPORT, raw_usage=raw,
        usage_map=FIREWORKS_USAGE_MAP, status="failed" if finish_reason == "length" else "completed",
        requested_model=model, reported_model=reported_model, provider_response_id=response_id,
        retry_of_call_id=call.retry_of_call_id,
        finish_reason=finish_reason, output_limit=max_output_tokens, started_at=call.started_at,
        ended_at=str(time.time()), elapsed_ms=int((time.monotonic() - started) * 1000),
        source_hash=call.source_hash, requested_affinity=session_affinity,
        prompt_layout_version=prompt_layout_version,
        usage_source="provider_response" if raw is not None else None,
        error_code="output_limit" if finish_reason == "length" else None,
        requested_reasoning_effort=reasoning_effort)
    body_usage = raw or {}
    for field, header_value in header_counts.items():
        body_value = body_usage.get(field)
        if field == "prompt_cache_hit_tokens" and body_value is None:
            details = body_usage.get("prompt_tokens_details")
            body_value = details.get("cached_tokens") if isinstance(details, dict) else None
        if body_value is not None and body_value != header_value:
            contract_field = {"prompt_tokens": "input_tokens",
                              "prompt_cache_hit_tokens": "cached_input_tokens"}[field]
            final.normalization_gaps.append(
                f"conflict:{contract_field}:body={body_value}!={header_names[field]}={header_value}")
    final.normalization_gaps = sorted(set(final.normalization_gaps))
    _append_sidecar(sidecar_path, final, "final")
    assembled_content = "".join(content_parts)
    assembled_reasoning = "".join(reasoning_parts)
    evidence.receipt("completed.json", {
        "status": "completed", "response_id": response_id, "reported_model": reported_model,
        "response": {"id": response_id, "model": reported_model,
                      "choices": [{"message": {"content": assembled_content,
                                                   "reasoning_content": assembled_reasoning},
                                   "finish_reason": finish_reason}],
                      "usage": usage_raw},
    })
    return _reply_from_final(assembled_content, call, final,
                         model, reported_model, session_affinity, finish_reason,
                         reasoning_effort=reasoning_effort)


def session_affinity_for(conversation_id: Any, model: Any) -> str | None:
    if not isinstance(conversation_id, str) or not conversation_id:
        return None
    model_text = model if isinstance(model, str) and model else DEFAULT_MODEL
    return "norrust-" + hashlib.sha256(
        f"norrust-session-affinity-v1:{conversation_id}:{model_text}".encode()).hexdigest()[:32]


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
        opener=urllib.request.urlopen, api_key: str | None = _UNSET,
        session_affinity: str | None = None,
        prompt_layout_version: str | None = None,
        retry_of_call_id: str | None = None, timeout: float = 840,
        stream: bool = False, evidence_dir: Path | None = None,
        request_context: dict[str, object] | None = None,
        reasoning_effort: str | None = None) -> dict[str, Any]:
    """Dispatch one Fireworks chat-completions call and return the reply envelope.

    Returns a typed error on output exhaustion. Raises on other failures; the usage
    sidecar has already recorded the dispatch and final outcome by the time
    this raises, so the caller need not catch anything to preserve evidence.

    `reasoning_effort` is rejected before any network call unless it is one
    of `SUPPORTED_REASONING_EFFORTS`. Left as `None` (the default), the
    request payload carries no `reasoning_effort` field at all -- byte
    identical to every payload this adapter sent before this option existed.
    """
    validate_reasoning_effort(reasoning_effort)
    prompt_sha256 = hashlib.sha256(prompt.encode()).hexdigest()
    call_id = _allocate_call_id(game_id, prompt_sha256)
    call = ModelCall(game_id=game_id or "unbound", call_id=call_id, request_id=request_id,
                      provider="fireworks", transport=TRANSPORT, requested_model=model,
                      requested_affinity=session_affinity,
                      retry_of_call_id=retry_of_call_id,
                      prompt_layout_version=prompt_layout_version,
                      requested_reasoning_effort=reasoning_effort,
                      output_limit=max_output_tokens, status="dispatched",
                      started_at=str(time.time()), source_hash=prompt_sha256)
    _append_sidecar(sidecar_path, call, "dispatch")

    if stream:
        payload = _stream_payload(model, prompt, max_output_tokens, reasoning_effort)
    else:
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
                   "stream": False, "max_completion_tokens": max_output_tokens,
                   "context_length_exceeded_behavior": "error"}
        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort
    evidence = _EvidenceRecorder(evidence_dir, call_id, prompt, payload, request_context)
    key = api_key if api_key is not _UNSET else os.environ.get("FIREWORKS_API_KEY")
    if not key:
        final = dataclasses.replace(call, status="failed", error_code="missing_credentials",
                                     ended_at=str(time.time()))
        _append_sidecar(sidecar_path, final, "final")
        evidence.receipt("incomplete.json", {
            "status": "blocked", "error_code": "missing_credentials",
            "message": "FIREWORKS_API_KEY is not set", "physical_call": False,
        })
        # Never dispatched to the provider: this is a locally blocked
        # request, not a physical call. The sidecar line above exists for
        # diagnosis only; game_history's importer must not turn a
        # status="failed"+error_code="missing_credentials" dispatch line
        # lacking any provider evidence into a billed call. See docs note in
        # tools/game_history.py's usage-sidecar import.
        raise RuntimeError("request_unknown: FIREWORKS_API_KEY is not set")

    if stream:
        return _run_stream(
            prompt, model=model, max_output_tokens=max_output_tokens, game_id=game_id,
            request_id=request_id, sidecar_path=sidecar_path, call=call, payload=payload,
            key=key, opener=opener, session_affinity=session_affinity,
            prompt_layout_version=prompt_layout_version, request_context=request_context,
            evidence=evidence, timeout=timeout, reasoning_effort=reasoning_effort)

    started = time.monotonic()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if session_affinity:
        headers["x-session-affinity"] = session_affinity
    request = urllib.request.Request(endpoint_url(), data=json.dumps(payload).encode(), headers=headers)

    def nonstream_transport_failure(exc: BaseException, partial: bytes = b"") -> None:
        partial_text = partial.decode(errors="replace")[:4000]
        final = dataclasses.replace(
            call, status="failed", error_code="transport_error",
            ended_at=str(time.time()),
            elapsed_ms=int((time.monotonic() - started) * 1000),
            raw_usage_json={"partial_body": partial_text, "partial_bytes": len(partial)}
            if partial else None)
        _append_sidecar(sidecar_path, final, "final")
        evidence.receipt("incomplete.json", {
            "status": "incomplete", "error_code": "transport_error",
            "message": str(exc), "partial_bytes": len(partial),
            "partial_body": partial_text,
        })
        raise RuntimeError(f"request_unknown: Fireworks transport error: {exc}") from exc

    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read()
            response_headers = getattr(response, "headers", None)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        final = dataclasses.replace(call, status="failed", error_code=f"http_{exc.code}",
                                     ended_at=str(time.time()),
                                     elapsed_ms=int((time.monotonic() - started) * 1000),
                                     raw_usage_json={"http_status": exc.code, "body": body[:4000]})
        _append_sidecar(sidecar_path, final, "final")
        evidence.receipt("incomplete.json", {"status": "http_error", "http_status": exc.code,
                                              "body": body[:4000]})
        raise RuntimeError(f"request_unknown: Fireworks HTTP {exc.code}") from exc
    except http.client.IncompleteRead as exc:
        nonstream_transport_failure(exc, exc.partial if isinstance(exc.partial, bytes) else b"")
    except http.client.HTTPException as exc:
        nonstream_transport_failure(exc)
    except OSError as exc:
        nonstream_transport_failure(exc)

    elapsed_ms = int((time.monotonic() - started) * 1000)
    try:
        body = json.loads(raw)
        choices = body["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError("Fireworks reply must contain exactly one choice")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise TypeError("Fireworks reply choice was not an object")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        final = dataclasses.replace(call, status="failed", error_code="malformed_response",
                                     ended_at=str(time.time()), elapsed_ms=elapsed_ms,
                                     raw_usage_json={"raw_body": raw.decode(errors="replace")[:4000]})
        _append_sidecar(sidecar_path, final, "final")
        evidence.receipt("incomplete.json", {"status": "incomplete", "error_code": "malformed_response",
                                              "message": "Fireworks reply was not a well-formed chat completion",
                                              "body": raw.decode(errors="replace")[:4000]})
        raise RuntimeError("request_unknown: Fireworks reply was not a well-formed chat completion") from exc

    body_usage = dict(body.get("usage")) if isinstance(body.get("usage"), dict) else {}
    usage_raw = dict(body_usage)
    details = usage_raw.get("prompt_tokens_details")
    if "prompt_cache_hit_tokens" not in usage_raw and isinstance(details, dict):
        if "cached_tokens" in details:
            usage_raw["prompt_cache_hit_tokens"] = details["cached_tokens"]
    header_counts: dict[str, Any] = {}
    header_names: dict[str, str] = {}
    if response_headers is not None:
        header_evidence = {}
        for header, field in (("fireworks-prompt-tokens", "prompt_tokens"),
                              ("fireworks-cached-prompt-tokens", "prompt_cache_hit_tokens")):
            value = response_headers.get(header) if hasattr(response_headers, "get") else None
            if value is None:
                continue
            header_evidence[header] = value
            if isinstance(value, str) and value.isdecimal():
                header_counts[field] = int(value)
                header_names[field] = header
                if field not in usage_raw:
                    usage_raw[field] = int(value)
        if header_evidence:
            usage_raw["fireworks_response_headers"] = header_evidence
    if body_usage:
        usage_raw["fireworks_body_usage"] = body_usage
    if not usage_raw:
        usage_raw = None
    finish_reason = choice.get("finish_reason")
    content = choice.get("message", {}).get("content") if isinstance(choice.get("message"), dict) else None
    limited = finish_reason == "length"
    call_status = "completed" if not limited and isinstance(content, str) and content.strip() else "failed"
    final = build_call(game_id=game_id or "unbound", call_id=call_id, request_id=request_id,
                        provider="fireworks", transport=TRANSPORT, raw_usage=usage_raw,
                        usage_map=FIREWORKS_USAGE_MAP, status=call_status,
                        requested_model=model, reported_model=body.get("model"),
                        provider_response_id=body.get("id"), finish_reason=finish_reason,
                        output_limit=max_output_tokens, started_at=call.started_at,
                        ended_at=str(time.time()), elapsed_ms=elapsed_ms, source_hash=prompt_sha256,
                        requested_affinity=session_affinity,
                        retry_of_call_id=retry_of_call_id,
                        error_code="output_limit" if limited else None,
                        prompt_layout_version=prompt_layout_version,
                        usage_source="provider_response" if usage_raw is not None else None,
                        requested_reasoning_effort=reasoning_effort)
    body_counts = {
        "prompt_tokens": body_usage.get("prompt_tokens"),
        "prompt_cache_hit_tokens": body_usage.get("prompt_cache_hit_tokens"),
    }
    details = body_usage.get("prompt_tokens_details")
    if body_counts["prompt_cache_hit_tokens"] is None and isinstance(details, dict):
        body_counts["prompt_cache_hit_tokens"] = details.get("cached_tokens")
    for field, header_value in header_counts.items():
        body_value = body_counts.get(field)
        if body_value is not None and body_value != header_value:
            contract_field = {"prompt_tokens": "input_tokens",
                              "prompt_cache_hit_tokens": "cached_input_tokens"}[field]
            final.normalization_gaps.append(
                f"conflict:{contract_field}:body={body_value}!={header_names[field]}={header_value}")
    final.normalization_gaps = sorted(set(final.normalization_gaps))
    _append_sidecar(sidecar_path, final, "final")

    if call_status == "failed" and not limited:
        evidence.receipt("incomplete.json", {
            "status": "incomplete", "error_code": "empty_content",
            "response": body,
        })
        raise RuntimeError(f"request_unknown: Fireworks returned no answer content "
                           f"(finish_reason={finish_reason})")

    evidence.receipt("completed.json", {"status": "completed", "response": body})

    # Truncated text is evidence, never executable orders (even if it happens
    # to parse). Only the harness owns escalation and retries.
    return _reply_from_final(content if isinstance(content, str) else "", call, final,
                             model, body.get("model"), session_affinity, finish_reason,
                             reasoning_effort=reasoning_effort)


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
    parser.add_argument("--max-output-tokens", type=int, default=None,
                        help="standalone output limit; under llm_client configure its --max-output-tokens instead")
    parser.add_argument("--game-id", default=os.environ.get("NORRUST_GAME_ID"))
    parser.add_argument("--request-id", default=os.environ.get("NORRUST_REQUEST_ID"))
    parser.add_argument("--request-context", default=os.environ.get("NORRUST_REQUEST_CONTEXT_FILE"),
                        help="context file the client publishes before each dispatch; supplies the "
                             "harness request identity when --request-id is not given")
    parser.add_argument("--usage-sidecar", default=None)
    parser.add_argument("--stream", action="store_true",
                        help="use Fireworks SSE streaming with durable partial evidence")
    parser.add_argument("--evidence-dir", default=os.environ.get("NORRUST_EVIDENCE_DIR"),
                        help="match-owned directory for payload, prompt, chunks, and receipts")
    parser.add_argument("--reasoning-effort", default=None,
                        help="explicit provider reasoning effort; standalone option when no harness "
                             "context is present -- under llm_client, configure its --reasoning-effort "
                             "instead. Omitted, the request payload is byte-identical to today's "
                             "(no reasoning_effort field; provider/model default applies).")
    args = parser.parse_args(argv)
    # The client publishes one context file per match and rewrites it before each
    # dispatch, so an adapter needs no per-call flag to know which harness
    # request it is spending against. An explicit --request-id still wins.
    context = read_request_context(args.request_context)
    if "output_limit" in context and args.max_output_tokens is not None:
        parser.error("configure --max-output-tokens on llm_client, not inside --model-command")
    output_limit = context.get("output_limit", args.max_output_tokens
                               if args.max_output_tokens is not None else INITIAL_OUTPUT_LIMIT)
    if type(output_limit) is not int or not 1 <= output_limit <= MAX_OUTPUT_LIMIT:
        parser.error("output limit must be between 1 and 524288 tokens")
    if "requested_reasoning_effort" in context and args.reasoning_effort is not None:
        parser.error("configure --reasoning-effort on llm_client, not inside --model-command")
    reasoning_effort = (context.get("requested_reasoning_effort")
                        if "requested_reasoning_effort" in context else args.reasoning_effort)
    if reasoning_effort is not None and not isinstance(reasoning_effort, str):
        parser.error("reasoning effort must be a string")
    try:
        validate_reasoning_effort(reasoning_effort)
    except UnsupportedReasoningEffort as exc:
        # Rejected honestly before any network call -- never silently mapped
        # to a nearby supported value.
        parser.error(str(exc))
    if not args.request_id:
        args.request_id = context.get("harness_request_id")
    if not args.game_id:
        args.game_id = context.get("conversation_id")
    affinity = session_affinity_for(context.get("conversation_id"), args.model)
    layout = context.get("prompt_layout_version")
    prompt = sys.stdin.read()
    sidecar = _sidecar_path(args.usage_sidecar)
    if context.get("game_log"):
        expected_sidecar = Path(context["game_log"]).resolve().with_name("usage.ndjson")
        if ((args.usage_sidecar or os.environ.get("NORRUST_USAGE_SIDECAR"))
                and sidecar.resolve() != expected_sidecar):
            parser.error("a harness game's usage sidecar must be usage.ndjson beside its log")
        sidecar = expected_sidecar
    evidence_dir = args.evidence_dir or context.get("evidence_dir")
    try:
        reply = run(prompt, model=args.model, max_output_tokens=output_limit,
                    game_id=args.game_id, request_id=args.request_id, sidecar_path=sidecar,
                    session_affinity=affinity,
                    prompt_layout_version=layout if isinstance(layout, str) else None,
                    retry_of_call_id=context.get("retry_of_call_id"),
                    timeout=max(1, float(context.get("model_timeout_seconds", 845)) - 5),
                    stream=args.stream,
                    evidence_dir=Path(evidence_dir) if isinstance(evidence_dir, str) else None,
                    request_context=context, reasoning_effort=reasoning_effort)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps(reply) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
