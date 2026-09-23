"""Bounded, provider-independent selection among engine-produced plan IDs.

This module deliberately knows nothing about game commands. A selector sees
only the candidate identifiers for the current decision and may return one ID.
The caller remains responsible for executing the corresponding validated plan.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import time
from typing import Protocol, Sequence


SCHEMA_VERSION = 1
DEFAULT_TIMEOUT_SECONDS = 2.0
DEFAULT_GAME_REQUEST_BUDGET = 64


class SelectorMode(str, Enum):
    DISABLED = "disabled"
    DETERMINISTIC = "deterministic"
    MODEL = "model"


class FallbackReason(str, Enum):
    DISABLED = "disabled"
    INVALID_CANDIDATES = "invalid_candidates"
    MALFORMED_RESPONSE = "malformed_response"
    UNKNOWN_CANDIDATE = "unknown_candidate"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass(frozen=True)
class SelectorRequest:
    """Compact selector envelope; it contains no executable game commands."""

    decision_id: str
    state_revision: str
    candidate_ids: tuple[str, ...]
    schema_version: int = SCHEMA_VERSION

    def to_json(self) -> str:
        return json.dumps({
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "state_revision": self.state_revision,
            "candidate_ids": list(self.candidate_ids),
        }, separators=(",", ":"), sort_keys=True)


class SelectorBackend(Protocol):
    """A single backend call. Implementations must enforce the supplied timeout."""

    def select(self, request: SelectorRequest, timeout_seconds: float) -> str: ...


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
    """Mutable per-game request counter, shared across decision calls."""

    maximum: int = DEFAULT_GAME_REQUEST_BUDGET
    used: int = 0

    def __post_init__(self) -> None:
        if self.maximum < 0:
            raise ValueError("maximum request budget cannot be negative")
        if self.used < 0 or self.used > self.maximum:
            raise ValueError("used requests must be within the request budget")

    def consume(self) -> bool:
        if self.used >= self.maximum:
            return False
        self.used += 1
        return True


def parse_candidate_response(response: str, candidate_ids: Sequence[str]) -> str:
    """Parse the strict JSON reply and verify it names a current candidate.

    The accepted response is exactly ``{"schema_version":1,"candidate_id":"..."}``.
    Extra fields (including free-form actions or scores) are rejected.
    """
    try:
        value = json.loads(response)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("malformed_response") from exc
    if (not isinstance(value, dict) or set(value) != {"schema_version", "candidate_id"}
            or value.get("schema_version") != SCHEMA_VERSION
            or isinstance(value.get("schema_version"), bool)
            or not isinstance(value.get("candidate_id"), str)
            or not value["candidate_id"]):
        raise ValueError("malformed_response")
    candidate_id = value["candidate_id"]
    if candidate_id not in candidate_ids:
        raise LookupError("unknown_candidate")
    return candidate_id


def _valid_ids(candidate_ids: Sequence[str], baseline_id: str) -> bool:
    return (bool(candidate_ids)
            and all(isinstance(value, str) and value for value in candidate_ids)
            and len(set(candidate_ids)) == len(candidate_ids)
            and baseline_id in candidate_ids)


def select_candidate(*, mode: SelectorMode, candidate_ids: Sequence[str], baseline_id: str,
                     decision_id: str, state_revision: str,
                     backend: SelectorBackend | None = None,
                     budget: GameRequestBudget | None = None,
                     timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> SelectionResult:
    """Select one current plan ID or return the deterministic baseline.

    A model call is made at most once per invocation. Budget is charged before
    dispatch, so a failed or timed-out request still consumes its game allowance.
    """
    started = time.monotonic()
    if not _valid_ids(candidate_ids, baseline_id):
        return SelectionResult(baseline_id, baseline_id, mode,
                               FallbackReason.INVALID_CANDIDATES, False,
                               time.monotonic() - started)
    if mode is SelectorMode.DISABLED:
        return SelectionResult(baseline_id, baseline_id, mode,
                               FallbackReason.DISABLED, False,
                               time.monotonic() - started)
    if mode is SelectorMode.DETERMINISTIC:
        return SelectionResult(baseline_id, baseline_id, mode, None, False,
                               time.monotonic() - started)
    if backend is None:
        return SelectionResult(baseline_id, baseline_id, mode,
                               FallbackReason.PROVIDER_ERROR, False,
                               time.monotonic() - started)
    request_budget = budget if budget is not None else GameRequestBudget()
    if not request_budget.consume():
        return SelectionResult(baseline_id, baseline_id, mode,
                               FallbackReason.BUDGET_EXHAUSTED, False,
                               time.monotonic() - started)
    request = SelectorRequest(decision_id, state_revision, tuple(candidate_ids))
    try:
        if timeout_seconds <= 0:
            raise TimeoutError("selector deadline elapsed")
        response = backend.select(request, timeout_seconds)
        if time.monotonic() - started > timeout_seconds:
            raise TimeoutError("selector deadline elapsed")
        selected = parse_candidate_response(response, candidate_ids)
    except TimeoutError:
        reason = FallbackReason.TIMEOUT
    except LookupError:
        reason = FallbackReason.UNKNOWN_CANDIDATE
    except ValueError:
        reason = FallbackReason.MALFORMED_RESPONSE
    except Exception:
        reason = FallbackReason.PROVIDER_ERROR
    else:
        return SelectionResult(selected, baseline_id, mode, None, True,
                               time.monotonic() - started)
    return SelectionResult(baseline_id, baseline_id, mode, reason, True,
                           time.monotonic() - started)


class FakeSelector:
    """Configurable, deterministic backend for unit and local acceptance tests."""

    def __init__(self, *, candidate_id: str | None = None, behavior: str = "select",
                 delay_seconds: float = 0.0):
        if behavior not in {"select", "malformed", "unknown", "timeout", "error"}:
            raise ValueError(f"unsupported fake behavior: {behavior}")
        self.candidate_id = candidate_id
        self.behavior = behavior
        self.delay_seconds = delay_seconds
        self.calls = 0
        self.last_request: SelectorRequest | None = None

    def select(self, request: SelectorRequest, timeout_seconds: float) -> str:
        self.calls += 1
        self.last_request = request
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
        candidate_id = self.candidate_id or request.candidate_ids[0]
        return json.dumps({"schema_version": SCHEMA_VERSION, "candidate_id": candidate_id})
