"""Shared output-token policy and command-backend exhaustion contract."""
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

INITIAL_OUTPUT_LIMIT = 128 * 1024
MAX_OUTPUT_LIMIT = 512 * 1024
MAX_CEILING_FAILURES = 3


class OutputLimitExceeded(RuntimeError):
    """A provider definitively ended a response at its requested output limit."""

    def __init__(self, envelope: dict[str, Any]):
        error = envelope.get("error")
        if (not isinstance(error, dict) or error.get("code") != "output_limit"
                or type(error.get("output_limit")) is not int
                or error["output_limit"] <= 0
                or not isinstance(error.get("call_id"), str) or not error["call_id"]):
            raise ValueError("invalid output_limit error envelope")
        self.envelope = envelope
        self.output_limit = error["output_limit"]
        self.call_id = error["call_id"]
        super().__init__(f"model_output_limit: {self.output_limit} tokens")


@dataclass
class OutputLimitPolicy:
    output_limit: int = INITIAL_OUTPUT_LIMIT
    ceiling_failures: int = 0

    def __post_init__(self):
        if type(self.output_limit) is not int or not 1 <= self.output_limit <= MAX_OUTPUT_LIMIT:
            raise ValueError("output limit must be between 1 and 524288 tokens")
        if type(self.ceiling_failures) is not int or not 0 <= self.ceiling_failures <= MAX_CEILING_FAILURES:
            raise ValueError("invalid output-limit failure count")

    @property
    def exhausted(self) -> bool:
        return self.ceiling_failures >= MAX_CEILING_FAILURES

    def record_failure(self, error: OutputLimitExceeded) -> None:
        if self.exhausted:
            raise RuntimeError("model_output_limit_exhausted: three failures at 524288 tokens")
        if error.output_limit != self.output_limit:
            raise RuntimeError("model_output_limit_mismatch: backend did not apply requested limit")
        if self.output_limit == MAX_OUTPUT_LIMIT:
            self.ceiling_failures += 1
        self.output_limit = MAX_OUTPUT_LIMIT

    def state(self) -> dict[str, int]:
        return {"output_limit": self.output_limit, "ceiling_failures": self.ceiling_failures}

    @classmethod
    def restore(cls, records: list[dict], conversation_id: str, initial: int,
                sidecar: Path | None = None):
        policy = cls(initial)
        for record in records:
            if (record.get("type") == "model_output_limit"
                    and record.get("conversation_id") == conversation_id):
                policy = cls(**record["policy"])
        # The adapter fsyncs a final usage row before returning. Recover that
        # evidence if the client died before recording its own failure event.
        failed = {}
        if sidecar is not None and sidecar.exists():
            lines = sidecar.read_text().splitlines()
            for index, line in enumerate(lines):
                try:
                    call = json.loads(line)
                except ValueError:
                    if index == len(lines) - 1:
                        continue  # interrupted append is unknown, not a failure
                    raise ValueError("invalid usage sidecar; cannot restore output-limit budget")
                if (call.get("game_id") == conversation_id
                        and call.get("record_kind") == "final"
                        and call.get("status") == "failed"
                        and call.get("finish_reason") == "length"
                        and not (call.get("requested_model") is not None
                                 and call.get("reported_model") is not None
                                 and call["requested_model"] != call["reported_model"])):
                    failed[call["call_id"]] = call
        if failed:
            policy.output_limit = MAX_OUTPUT_LIMIT
            policy.ceiling_failures = max(policy.ceiling_failures, min(MAX_CEILING_FAILURES,
                sum(c.get("output_limit") == MAX_OUTPUT_LIMIT for c in failed.values())))
        return policy


def combined_usage(attempts: list[dict | None]) -> dict | None:
    """Aggregate a request's attempts; a missing count stays unknown."""
    if not attempts or any(not isinstance(item, dict) for item in attempts):
        return None
    fields = set().union(*(item.keys() for item in attempts))
    result = {}
    for field in fields:
        counts = [item.get(field) for item in attempts]
        result[field] = (sum(counts) if all(type(n) is int and n >= 0 for n in counts)
                         else None)
    return result
