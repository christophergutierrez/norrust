"""Read the existing physical-call sidecar for the client's online token guard."""
from __future__ import annotations

from pathlib import Path

try:
    from .game_history import _read_usage_sidecar
    from .model_usage import dedupe_calls, normalize_int
except ImportError:  # Direct-script entry point, same implementation.
    from game_history import _read_usage_sidecar
    from model_usage import dedupe_calls, normalize_int


def measured_game_budget(sidecar: Path, conversation_id: str,
                         expected_requests: set[str]) -> dict:
    records, malformed = _read_usage_sidecar(sidecar)
    records = [r for r in records if r.game_id == conversation_id
               and r.error_code != "missing_credentials"]
    calls, conflicts = dedupe_calls(records)
    known_total = 0
    unknown = 0
    for call in calls:
        total, gap = normalize_int(call.total_tokens)
        if total is None or gap or call.normalization_gaps:
            unknown += 1
        else:
            known_total += total
    linked_requests = {c.request_id for c in calls}
    # Codex host evidence collected after execution cannot bound its next
    # in-flight host turn. Only a maintained one-call adapter can certify this.
    online = bool(calls) and all(c.transport in {
        "fireworks_chat_completions", "offline_fixture"
    } for c in calls)
    complete = (online and not unknown and not malformed and not conflicts
                and expected_requests.issubset(linked_requests))
    return {"cumulative_game_total_tokens": known_total,
            "game_token_limit_enforced": complete,
            "game_token_usage_unknown_calls": unknown,
            "game_token_usage_gaps": len(malformed) + len(conflicts)
                + len(expected_requests - linked_requests)}
