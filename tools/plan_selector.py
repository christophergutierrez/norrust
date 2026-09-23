"""Canonical, bounded selector prompt and strict response parser.

The Rust planner owns candidate generation and execution. This module only
serializes the versioned selector request into a compact prompt and accepts a
candidate ID in response.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import math
import argparse
import os
from pathlib import Path
import sys
import time
from typing import Any, Protocol, Sequence

from . import fireworks_backend

SCHEMA_VERSION = 1
MAX_PROMPT_BYTES = 12_288
DEFAULT_TIMEOUT_SECONDS = 2.0
DEFAULT_GAME_REQUEST_BUDGET = 64
SELECTOR_OUTPUT_TOKENS = 2_048
SELECTOR_TIMEOUT_SECONDS = 60.0
SELECTOR_PROMPT_LAYOUT = "coordinated_selector_v1"
MODEL_PROFILES = {
    "accounts/fireworks/models/glm-5p3-flash": "low",
    "accounts/fireworks/models/deepseek-v4p1-flash": "low",
}
_REQUEST_KEYS = {"schema_version", "turn", "side", "state_revision", "evaluation_seed", "objective", "candidates"}
_CANDIDATE_KEYS = {"candidate_id", "plan_kind", "label", "score", "material_delta", "gold_delta", "village_delta", "recruiter_alive", "objective_progress", "opponent_response_delta", "legal", "state_revision"}
_ENVELOPE_KEYS = {"schema_version", "game_id", "decision_id", "request_sha256", "request"}


class PromptTooLarge(ValueError):
    """The complete prompt cannot fit the fixed UTF-8 budget."""


class SelectorMode(str, Enum):
    DISABLED = "disabled"
    DETERMINISTIC = "deterministic"
    MODEL = "model"


class FallbackReason(str, Enum):
    DISABLED = "disabled"
    INVALID_REQUEST = "invalid_request"
    MALFORMED_RESPONSE = "malformed_response"
    UNKNOWN_CANDIDATE = "unknown_candidate"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    BUDGET_EXHAUSTED = "budget_exhausted"


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _strict_object(text: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ValueError(f"invalid JSON constant: {value}")

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError("selector value must be a JSON object")
    return value


@dataclass(frozen=True)
class CandidateSummary:
    candidate_id: str
    plan_kind: str
    label: str
    score: float
    material_delta: float
    gold_delta: int
    village_delta: int
    recruiter_alive: bool
    objective_progress: float
    opponent_response_delta: float
    legal: bool
    state_revision: int

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CandidateSummary":
        if not isinstance(value, dict):
            raise ValueError("candidate must be an object")
        if set(value) != _CANDIDATE_KEYS:
            raise ValueError("candidate fields do not match selector schema")
        if any(not isinstance(value[key], str) or not value[key] for key in ("candidate_id", "plan_kind", "label")):
            raise ValueError("candidate text fields are invalid")
        if (not _number(value["score"]) or not _number(value["material_delta"])
                or not _number(value["objective_progress"])
                or not _number(value["opponent_response_delta"])
                or not _integer(value["gold_delta"]) or not _integer(value["village_delta"])
                or not isinstance(value["recruiter_alive"], bool)
                or not isinstance(value["legal"], bool) or not _integer(value["state_revision"])):
            raise ValueError("candidate metric types are invalid")
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in (
            "candidate_id", "plan_kind", "label", "score", "material_delta",
            "gold_delta", "village_delta", "recruiter_alive", "objective_progress",
            "opponent_response_delta", "legal", "state_revision")}


@dataclass(frozen=True)
class SelectorRequest:
    schema_version: int
    turn: int
    side: int
    state_revision: int
    evaluation_seed: int
    objective: str
    candidates: tuple[CandidateSummary, ...]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SelectorRequest":
        if not isinstance(value, dict):
            raise ValueError("selector request must be an object")
        if set(value) != _REQUEST_KEYS or value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported or incomplete selector request schema")
        if (not _integer(value["turn"]) or value["turn"] < 0
                or not _integer(value["side"]) or value["side"] not in (0, 1)
                or not _integer(value["state_revision"]) or value["state_revision"] < 0
                or not _integer(value["evaluation_seed"]) or value["evaluation_seed"] < 0
                or not isinstance(value["objective"], str) or not value["objective"]
                or not isinstance(value["candidates"], list) or not value["candidates"]):
            raise ValueError("selector request fields are invalid")
        request = cls(value["schema_version"], value["turn"], value["side"], value["state_revision"],
                      value["evaluation_seed"], value["objective"],
                      tuple(CandidateSummary.from_dict(item) for item in value["candidates"]))
        request.validate()
        return request

    @classmethod
    def from_json(cls, text: str) -> "SelectorRequest":
        return cls.from_dict(_strict_object(text))

    def validate(self) -> None:
        ids = [candidate.candidate_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate IDs must be unique")
        if any(not candidate.legal or candidate.state_revision != self.state_revision for candidate in self.candidates):
            raise ValueError("candidate is illegal or has a stale revision")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "turn": self.turn, "side": self.side,
                "state_revision": self.state_revision, "evaluation_seed": self.evaluation_seed,
                "objective": self.objective,
                "candidates": [candidate.to_dict() for candidate in sorted(self.candidates, key=lambda item: item.candidate_id)]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


def _baseline_id(request: SelectorRequest) -> str:
    rank = {"objective": 2, "lookahead": 1, "greedy": 0}
    return max(request.candidates, key=lambda candidate: (candidate.score, rank.get(candidate.plan_kind, -1), candidate.candidate_id)).candidate_id


@dataclass(frozen=True)
class SelectorEnvelope:
    """Identity envelope used by the Rust selector command boundary."""

    game_id: str
    decision_id: str
    request_sha256: str
    request: SelectorRequest
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def from_json(cls, text: str) -> "SelectorEnvelope":
        value = _strict_object(text)
        if set(value) != _ENVELOPE_KEYS or value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("invalid selector envelope")
        if (not isinstance(value["game_id"], str) or not value["game_id"]
                or not isinstance(value["decision_id"], str) or not value["decision_id"]
                or not isinstance(value["request_sha256"], str)
                or len(value["request_sha256"]) != 64
                or any(character not in "0123456789abcdef" for character in value["request_sha256"])):
            raise ValueError("invalid selector envelope identity")
        return cls(value["game_id"], value["decision_id"], value["request_sha256"],
                   SelectorRequest.from_dict(value["request"]), value["schema_version"])

    def response_json(self, response: str) -> str:
        parsed = _parse_response_object(response,
                                        [candidate.candidate_id for candidate in self.request.candidates])
        return json.dumps({
            "schema_version": self.schema_version,
            "game_id": self.game_id,
            "decision_id": self.decision_id,
            "request_sha256": self.request_sha256,
            "response": parsed,
        }, separators=(",", ":"), sort_keys=True)


def build_selector_prompt(request: SelectorRequest) -> str:
    """Build the sole canonical prompt sent to a selector backend."""
    request.validate()
    prompt = (
        "Choose one existing complete-turn Coordinated Planner plan for the controlled side's long-term survival and victory. "
        "The engine performs movement, combat, recruitment, arithmetic, and execution. Return only the strict JSON response.\n\n"
        "Perspective and definitions:\n"
        "- side is the controlled side; every delta is from its perspective.\n"
        "- candidate facts cover our completed turn and the modeled opponent response; opponent_response_delta is the utility change caused by that response.\n"
        "- relative forces are summarized by material_delta and recruiter_alive; gold_delta and village_delta summarize economy and control.\n"
        "- material_delta and gold_delta are net changes, not enemy casualties; useful spending is not automatically harmful.\n"
        "- missing threat or consequence evidence is unknown, never safe.\n"
        "- score is deterministic engine utility; do not select by score alone.\n\n"
        f"Current objective: {request.objective}\nTurn: {request.turn}; controlled side: {request.side}; state revision: {request.state_revision}; evaluation seed: {request.evaluation_seed}\n"
        f"Deterministic baseline candidate: {_baseline_id(request)}\n"
        "Candidates (the baseline is used when advice is unavailable):\n"
    )
    for candidate in sorted(request.candidates, key=lambda item: item.candidate_id):
        prompt += json.dumps(candidate.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False) + "\n"
    prompt += ('\nRespond with exactly one JSON object: {"schema_version":1,"candidate_id":"<existing ID>","reason_code":"optional short reason"}. '
               "Do not return commands, actions, scores, markdown, or extra fields.")
    if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise PromptTooLarge("selector prompt exceeds 12288 UTF-8 bytes")
    return prompt


def parse_candidate_response(response: str, candidate_ids: Sequence[str]) -> str:
    value = _parse_response_object(response, candidate_ids)
    return value["candidate_id"]


def _parse_response_object(response: str, candidate_ids: Sequence[str]) -> dict[str, Any]:
    try:
        value = _strict_object(response)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("malformed_response") from exc
    if set(value) not in ({"schema_version", "candidate_id"}, {"schema_version", "candidate_id", "reason_code"}):
        raise ValueError("malformed_response")
    if (value.get("schema_version") != SCHEMA_VERSION or not _integer(value.get("schema_version"))
            or not isinstance(value.get("candidate_id"), str) or not value["candidate_id"]):
        raise ValueError("malformed_response")
    if "reason_code" in value and value["reason_code"] is not None:
        if not isinstance(value["reason_code"], str) or len(value["reason_code"].encode("utf-8")) > 32:
            raise ValueError("malformed_response")
    if value["candidate_id"] not in candidate_ids:
        raise LookupError("unknown_candidate")
    return value


class SelectorBackend(Protocol):
    def select(self, prompt: str, timeout_seconds: float) -> str: ...


@dataclass(frozen=True)
class SelectionResult:
    selected_id: str
    baseline_id: str
    mode: SelectorMode
    fallback_reason: FallbackReason | None
    request_used: bool
    elapsed_seconds: float

    @property
    def used_fallback(self) -> bool:
        return self.fallback_reason is not None and self.fallback_reason is not FallbackReason.DISABLED


@dataclass
class GameRequestBudget:
    maximum: int = DEFAULT_GAME_REQUEST_BUDGET
    used: int = 0

    def __post_init__(self) -> None:
        if self.maximum < 0 or self.used < 0 or self.used > self.maximum:
            raise ValueError("invalid selector request budget")

    def consume(self) -> bool:
        if self.used >= self.maximum:
            return False
        self.used += 1
        return True


def select_candidate(*, request: SelectorRequest, mode: SelectorMode,
                     backend: SelectorBackend | None = None,
                     budget: GameRequestBudget | None = None,
                     timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> SelectionResult:
    started = time.monotonic()
    try:
        request.validate()
        baseline = _baseline_id(request)
    except ValueError:
        return SelectionResult("", "", mode, FallbackReason.INVALID_REQUEST, False, time.monotonic() - started)
    if mode is SelectorMode.DISABLED:
        return SelectionResult(baseline, baseline, mode, FallbackReason.DISABLED, False, time.monotonic() - started)
    if mode is SelectorMode.DETERMINISTIC:
        return SelectionResult(baseline, baseline, mode, None, False, time.monotonic() - started)
    if backend is None:
        return SelectionResult(baseline, baseline, mode, FallbackReason.PROVIDER_ERROR, False, time.monotonic() - started)
    request_budget = budget if budget is not None else GameRequestBudget()
    if not request_budget.consume():
        return SelectionResult(baseline, baseline, mode, FallbackReason.BUDGET_EXHAUSTED, False, time.monotonic() - started)
    try:
        prompt = build_selector_prompt(request)
        if timeout_seconds <= 0:
            raise TimeoutError("selector deadline elapsed")
        response = backend.select(prompt, timeout_seconds)
        if time.monotonic() - started > timeout_seconds:
            raise TimeoutError("selector deadline elapsed")
        selected = parse_candidate_response(response, [candidate.candidate_id for candidate in request.candidates])
    except PromptTooLarge:
        reason = FallbackReason.INVALID_REQUEST
    except TimeoutError:
        reason = FallbackReason.TIMEOUT
    except LookupError:
        reason = FallbackReason.UNKNOWN_CANDIDATE
    except ValueError:
        reason = FallbackReason.MALFORMED_RESPONSE
    except Exception:
        reason = FallbackReason.PROVIDER_ERROR
    else:
        return SelectionResult(selected, baseline, mode, None, True, time.monotonic() - started)
    return SelectionResult(baseline, baseline, mode, reason, True, time.monotonic() - started)


class FakeSelector:
    """Local backend for prompt and parser tests; never performs network I/O."""

    def __init__(self, *, candidate_id: str | None = None, behavior: str = "select", delay_seconds: float = 0.0):
        if behavior not in {"select", "malformed", "unknown", "timeout", "error"}:
            raise ValueError(f"unsupported fake behavior: {behavior}")
        self.candidate_id = candidate_id
        self.behavior = behavior
        self.delay_seconds = delay_seconds
        self.calls = 0
        self.last_prompt: str | None = None

    def select(self, prompt: str, timeout_seconds: float) -> str:
        self.calls += 1
        self.last_prompt = prompt
        if self.behavior == "timeout" or self.delay_seconds > timeout_seconds:
            raise TimeoutError("fake selector timed out")
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.behavior == "malformed":
            return '{"candidate_id":'
        if self.behavior == "unknown":
            return json.dumps({"schema_version": SCHEMA_VERSION, "candidate_id": "not-a-candidate"})
        if self.behavior == "error":
            raise RuntimeError("fake provider failure")
        if self.candidate_id is None:
            raise ValueError("fake selector needs a candidate_id")
        return json.dumps({"schema_version": SCHEMA_VERSION, "candidate_id": self.candidate_id})


@dataclass(frozen=True)
class SelectorDispatchResult:
    envelope: str
    selected_id: str
    fallback_reason: str | None
    dispatched: bool


def resolve_selector_profile(model: str, reasoning_effort: str) -> None:
    """Validate the two frozen Stack 3 profiles before dispatch."""
    if model not in MODEL_PROFILES or MODEL_PROFILES[model] != reasoning_effort:
        raise ValueError("unsupported selector model/reasoning profile")


def _fallback_result(envelope: SelectorEnvelope, reason: str,
                     *, dispatched: bool = False) -> SelectorDispatchResult:
    baseline = _baseline_id(envelope.request)
    response = envelope.response_json(json.dumps({
        "schema_version": SCHEMA_VERSION, "candidate_id": baseline,
    }, separators=(",", ":")))
    return SelectorDispatchResult(response, baseline, reason, dispatched)


def run_selector_envelope(
    envelope: SelectorEnvelope,
    *,
    model: str,
    reasoning_effort: str,
    max_output_tokens: int = SELECTOR_OUTPUT_TOKENS,
    timeout: float = SELECTOR_TIMEOUT_SECONDS,
    game_id: str | None = None,
    request_id: str | None = None,
    sidecar_path: Path | None = None,
    evidence_dir: Path | None = None,
    fireworks_run: Any | None = None,
) -> SelectorDispatchResult:
    """Make exactly one bounded provider attempt and return an envelope.

    Transport failures, output exhaustion, and strict-response failures all
    return the engine baseline. The provider's transport has already recorded
    its dispatch/final lifecycle before reporting those failures.
    """
    try:
        resolve_selector_profile(model, reasoning_effort)
        if max_output_tokens != SELECTOR_OUTPUT_TOKENS or timeout != SELECTOR_TIMEOUT_SECONDS:
            raise ValueError("selector output and timeout profile are fixed at 2048/60s")
        prompt = build_selector_prompt(envelope.request)
    except (PromptTooLarge, ValueError) as exc:
        return _fallback_result(envelope, str(exc))
    game_id = game_id or os.environ.get("NORRUST_GAME_ID") or envelope.game_id
    request_id = request_id or os.environ.get("NORRUST_REQUEST_ID") or envelope.decision_id
    sidecar_path = sidecar_path or Path(os.environ.get("NORRUST_USAGE_SIDECAR", "usage.ndjson"))
    if evidence_dir is None:
        raw_evidence = os.environ.get("NORRUST_EVIDENCE_DIR")
        evidence_dir = Path(raw_evidence) if raw_evidence else None
    context = {
        "selector": True,
        "game_id": game_id,
        "decision_id": envelope.decision_id,
        "request_sha256": envelope.request_sha256,
        "output_limit": SELECTOR_OUTPUT_TOKENS,
        "model_timeout_seconds": SELECTOR_TIMEOUT_SECONDS,
        "requested_reasoning_effort": reasoning_effort,
        "prompt_layout_version": SELECTOR_PROMPT_LAYOUT,
    }
    fireworks_run = fireworks_run or fireworks_backend.run
    try:
        reply = fireworks_run(
            prompt,
            model=model,
            max_output_tokens=SELECTOR_OUTPUT_TOKENS,
            game_id=game_id,
            request_id=request_id,
            sidecar_path=sidecar_path,
            session_affinity=fireworks_backend.session_affinity_for(game_id, model),
            prompt_layout_version=SELECTOR_PROMPT_LAYOUT,
            timeout=SELECTOR_TIMEOUT_SECONDS,
            stream=True,
            evidence_dir=evidence_dir,
            request_context=context,
            reasoning_effort=reasoning_effort,
        )
        if not isinstance(reply, dict):
            raise ValueError("provider reply was not an object")
        error = reply.get("error")
        if isinstance(error, dict) and error.get("code") == "output_limit":
            return _fallback_result(envelope, "output_limit", dispatched=True)
        text = reply.get("text")
        if not isinstance(text, str):
            raise ValueError("provider reply had no text")
        response = envelope.response_json(text)
        selected = json.loads(response)["response"]["candidate_id"]
        return SelectorDispatchResult(response, selected, None, True)
    except Exception as exc:
        return _fallback_result(envelope, str(exc), dispatched=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the local identity-preserving command adapter.

    The adapter is deliberately deterministic until the provider transport
    stack supplies a backend. ``--candidate-id`` is a local test hook; absent
    that option, the engine-ranked baseline is returned.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-id", help="local test candidate ID")
    parser.add_argument("--model", default=os.environ.get(
        "NORRUST_SELECTOR_MODEL", "accounts/fireworks/models/deepseek-v4p1-flash"))
    parser.add_argument("--reasoning-effort", default=os.environ.get(
        "NORRUST_SELECTOR_REASONING_EFFORT", "low"))
    parser.add_argument("--max-output-tokens", type=int, default=int(os.environ.get(
        "NORRUST_SELECTOR_OUTPUT_TOKENS", str(SELECTOR_OUTPUT_TOKENS))))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get(
        "NORRUST_SELECTOR_TIMEOUT_SECONDS", str(SELECTOR_TIMEOUT_SECONDS))))
    args = parser.parse_args(argv)
    line = sys.stdin.readline(MAX_PROMPT_BYTES * 2)
    if not line:
        print("selector envelope is required", file=sys.stderr)
        return 2
    try:
        envelope = SelectorEnvelope.from_json(line)
        if args.candidate_id:
            output = envelope.response_json(json.dumps({
                "schema_version": SCHEMA_VERSION, "candidate_id": args.candidate_id,
            }, separators=(",", ":")))
        else:
            output = run_selector_envelope(
                envelope, model=args.model, reasoning_effort=args.reasoning_effort,
                max_output_tokens=args.max_output_tokens, timeout=args.timeout,
            ).envelope
    except (ValueError, LookupError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    sys.stdout.write(output + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
