"""Versioned model-call usage records: validation, normalization, identity, and
aggregation.

Independent of the engine and of SQLite -- pure dataclasses and functions.
`tools/game_history.py` imports rows built here into the `model_calls` table;
`tools/fireworks_backend.py` builds them before writing its usage sidecar.

Accounting contract (frozen in tmp/plan_token_usage.md):
  - One row per actual provider/host inference response or observable
    dispatched attempt. A locally blocked request that never reached a
    provider owns zero calls. A dispatched call with unknown outcome still
    owns a row with unknown usage.
  - Never deduplicate by prompt hash -- two paid retries are two calls.
  - Repeated lifecycle records for one call UPSERT it; conflicting FINAL
    usage for the same response is a reported CONFLICT, not last-writer-wins.
  - Never compute total = input + cached + output + reasoning.
  - Integers are normalized strictly: booleans, negative numbers, and numeric
    strings are rejected as measured counts and reported as gaps, not zeroed.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Iterable

USAGE_SCHEMA_VERSION = "usage_v1"

TOKEN_FIELDS = (
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "output_tokens", "reasoning_tokens", "total_tokens",
)

# Call lifecycle statuses. "dispatched" means an attempt was sent to a
# provider/host and no terminal outcome is known yet or was ever observed
# (a dispatched-but-lost call). "unknown" is for lifecycle evidence that
# names a call without proving it was ever dispatched.
CALL_STATUSES = ("dispatched", "completed", "failed", "unknown")


class UsageValidationError(ValueError):
    """Raised by callers that need a hard failure on structurally invalid input."""


def normalize_int(value: Any) -> tuple[int | None, str | None]:
    """Normalize one measured token count.

    Returns (value, gap). A clean nonnegative int returns (value, None). A
    boolean, negative number, numeric string, float, or other non-int shape
    is rejected as a measured count and returned as (None, gap) -- the
    malformed evidence is retained by the caller (in raw_usage_json), never
    silently coerced or zeroed.
    """
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, f"boolean_not_a_count:{value!r}"
    if isinstance(value, int):
        if value < 0:
            return None, f"negative_count:{value!r}"
        return value, None
    if isinstance(value, str):
        return None, f"numeric_string_not_a_count:{value!r}"
    return None, f"non_integer_count:{value!r}"


def normalize_usage(raw: Any, mapping: dict[str, str]) -> tuple[dict[str, int | None], list[str]]:
    """Normalize a provider's raw usage object using an explicit field mapping.

    `mapping` maps THIS provider's raw field names to contract token field
    names (a subset of TOKEN_FIELDS); unmapped raw fields are left untouched
    here (callers keep the complete raw object separately). Never derives
    `total_tokens` from other fields -- it is used only when the provider
    itself reports a field mapped to it.
    """
    normalized: dict[str, int | None] = {field: None for field in TOKEN_FIELDS}
    gaps: list[str] = []
    if not isinstance(raw, dict):
        if raw is not None:
            gaps.append(f"usage_not_an_object:{raw!r}")
        return normalized, gaps
    for raw_key, field in mapping.items():
        if field not in TOKEN_FIELDS or raw_key not in raw:
            continue
        value, gap = normalize_int(raw.get(raw_key))
        if gap is not None:
            gaps.append(f"{field}:{gap}")
        normalized[field] = value
    return normalized, gaps


# Known per-provider raw -> contract field maps. Each mapping is exercised by
# a small synthetic fixture in tools/test_model_usage.py documenting the
# source semantics (e.g. Fireworks counts cache hits within prompt_tokens).
FIREWORKS_USAGE_MAP = {
    "prompt_tokens": "input_tokens",
    "completion_tokens": "output_tokens",
    "total_tokens": "total_tokens",
    "prompt_cache_hit_tokens": "cached_input_tokens",
}

CODEX_USAGE_MAP = {
    "input_tokens": "input_tokens",
    "cached_input_tokens": "cached_input_tokens",
    "output_tokens": "output_tokens",
    "reasoning_output_tokens": "reasoning_tokens",
    "total_tokens": "total_tokens",
}


def source_identity(provider: str | None, native_thread_id: str | None,
                     provider_response_id: str | None, attempt_id: str) -> str:
    """Compute the unique source-identity key the contract requires.

    Prefers (provider, thread, response_id) once a response id is known.
    Falls back to the caller-allocated attempt id (assigned before dispatch)
    for a call whose outcome -- and therefore whose response id -- is
    unknown, e.g. a dispatched call that never returned.
    """
    if provider_response_id:
        return f"{provider or 'unknown'}:{native_thread_id or ''}:{provider_response_id}"
    return f"{provider or 'unknown'}:{native_thread_id or ''}:attempt:{attempt_id}"


@dataclasses.dataclass
class ModelCall:
    """One normalized `model_calls` row -- the accounting contract's minimal fields."""

    game_id: str
    call_id: str
    request_id: str | None = None
    retry_of_call_id: str | None = None

    provider: str | None = None
    transport: str | None = None
    native_thread_id: str | None = None
    provider_response_id: str | None = None

    requested_model: str | None = None
    reported_model: str | None = None
    requested_affinity: str | None = None
    prompt_layout_version: str | None = None
    prompt_layout_source: str | None = None
    requested_reasoning_effort: str | None = None
    reported_reasoning_effort: str | None = None
    output_limit: int | None = None

    status: str = "unknown"
    finish_reason: str | None = None
    error_code: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    elapsed_ms: int | None = None

    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None

    usage_source: str | None = None
    usage_schema_version: str = USAGE_SCHEMA_VERSION
    raw_usage_json: Any = None
    source_ref: str | None = None
    source_hash: str | None = None
    linkage_evidence: str | None = None
    normalization_gaps: list[str] = dataclasses.field(default_factory=list)

    def identity(self) -> tuple[str, str]:
        return (self.game_id, self.call_id)

    def token_fields(self) -> dict[str, int | None]:
        return {field: getattr(self, field) for field in TOKEN_FIELDS}

    def to_row(self) -> dict[str, Any]:
        """Flatten to a dict matching the `model_calls` table columns."""
        row = dataclasses.asdict(self)
        row["normalization_gaps"] = list(self.normalization_gaps)
        return row


def build_call(*, game_id: str, call_id: str, provider: str | None, transport: str | None,
                raw_usage: Any, usage_map: dict[str, str], status: str = "unknown",
                **fields: Any) -> ModelCall:
    """Convenience constructor: normalize raw usage and build one ModelCall.

    `fields` accepts any other ModelCall attribute (request_id, native_thread_id,
    provider_response_id, requested_model, finish_reason, error_code, ...).
    """
    normalized, gaps = normalize_usage(raw_usage, usage_map)
    call = ModelCall(game_id=game_id, call_id=call_id, provider=provider, transport=transport,
                      status=status, raw_usage_json=raw_usage, normalization_gaps=gaps, **fields)
    for field, value in normalized.items():
        setattr(call, field, value)
    return call


def validate_call(call: ModelCall) -> list[str]:
    """Structural validation beyond token normalization. Returns problems (empty = valid)."""
    problems: list[str] = []
    if not call.game_id:
        problems.append("missing_game_id")
    if not call.call_id:
        problems.append("missing_call_id")
    if call.status not in CALL_STATUSES:
        problems.append(f"unknown_status:{call.status!r}")
    if call.request_id is not None and not isinstance(call.request_id, str):
        problems.append("request_id_must_be_string")
    for field in TOKEN_FIELDS:
        value = getattr(call, field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            problems.append(f"invalid_normalized_{field}:{value!r}")
    return problems


def merge_lifecycle(existing: ModelCall, update: ModelCall) -> tuple[ModelCall, list[str]]:
    """UPSERT repeated lifecycle records for one call.

    Token fields: a newly-reported value fills a previously-unknown field.
    Two present values that disagree are a CONFLICT (appended to the
    returned list and recorded in `merged.normalization_gaps`); the
    previously recorded value is retained rather than overwritten, since
    neither report is inherently more authoritative than the other.
    """
    if existing.game_id != update.game_id or existing.call_id != update.call_id:
        raise UsageValidationError("merge_lifecycle requires the same (game_id, call_id) identity")
    conflicts: list[str] = []
    merged = dataclasses.replace(existing)
    for field in TOKEN_FIELDS:
        old = getattr(existing, field)
        new = getattr(update, field)
        if new is None:
            continue
        if old is None:
            setattr(merged, field, new)
        elif old != new:
            conflicts.append(f"{field}:{old}!={new}")
    for field in ("status", "finish_reason", "error_code", "ended_at", "elapsed_ms",
                  "reported_model", "reported_reasoning_effort", "provider_response_id",
                  "native_thread_id", "usage_source", "raw_usage_json", "source_ref",
                  "source_hash", "request_id", "retry_of_call_id", "linkage_evidence",
                  "started_at", "requested_model", "requested_reasoning_effort", "output_limit",
                  "provider", "transport", "requested_affinity", "prompt_layout_version",
                  "prompt_layout_source"):
        new = getattr(update, field)
        if new is not None:
            setattr(merged, field, new)
    gap_conflicts = [f"conflict:{c}" for c in conflicts]
    merged.normalization_gaps = sorted(set(existing.normalization_gaps) | set(update.normalization_gaps)
                                        | set(gap_conflicts))
    return merged, conflicts


def dedupe_calls(records: Iterable[ModelCall]) -> tuple[list[ModelCall], dict[tuple[str, str], list[str]]]:
    """Fold repeated lifecycle records for the same (game_id, call_id) into one row each.

    Returns (deduped_calls, conflicts_by_identity). Input order is preserved
    for first occurrence of each identity; later records for the same
    identity are merged in encounter order via `merge_lifecycle`. This is an
    UPSERT, never a dedup-by-prompt-hash: two calls with different call_ids
    are always kept as two rows, even if their prompts are identical.
    """
    by_identity: dict[tuple[str, str], ModelCall] = {}
    order: list[tuple[str, str]] = []
    conflicts: dict[tuple[str, str], list[str]] = {}
    for record in records:
        key = record.identity()
        if key not in by_identity:
            by_identity[key] = record
            order.append(key)
            continue
        merged, these_conflicts = merge_lifecycle(by_identity[key], record)
        by_identity[key] = merged
        if these_conflicts:
            conflicts.setdefault(key, []).extend(these_conflicts)
    return [by_identity[key] for key in order], conflicts


def aggregate_calls(calls: Iterable[ModelCall]) -> dict[str, Any]:
    """Aggregate a group of ModelCall rows into per-field sums and coverage.

    Never computes total_tokens from parts. A field's `sum` is the sum of
    calls that actually measured it; `fully_measured` is true only when every
    call in the group has that field known, so a caller can distinguish a
    complete measured total from a partial sum with a labeled gap. `sum` is
    None only when NO call in the group has that field measured at all.
    """
    calls = list(calls)
    result: dict[str, Any] = {"call_count": len(calls)}
    for field in TOKEN_FIELDS:
        values = [getattr(c, field) for c in calls]
        known = [v for v in values if v is not None]
        result[field] = {
            "sum": sum(known) if known else None,
            "known_calls": len(known),
            "unknown_calls": len(values) - len(known),
            "fully_measured": len(values) > 0 and len(known) == len(values),
        }
    result["statuses"] = sorted({c.status for c in calls})
    return result


def request_aggregate_from_legacy(usage: dict[str, Any] | None) -> dict[str, Any]:
    """Wrap pre-detail request-level usage as an explicitly labeled aggregate.

    Historical `model_requests` rows recorded only request-level totals with
    no underlying call detail. This never becomes a fabricated ModelCall; it
    stays a `request_aggregate` used solely for reconciliation against any
    genuine detailed calls, never summed into their totals.
    """
    usage = usage or {}
    normalized: dict[str, int | None] = {}
    gaps: list[str] = []
    for field in TOKEN_FIELDS:
        value, gap = normalize_int(usage.get(field))
        normalized[field] = value
        if gap is not None:
            gaps.append(f"{field}:{gap}")
    return {"kind": "request_aggregate", "tokens": normalized, "normalization_gaps": gaps,
            "raw_usage_json": usage}
