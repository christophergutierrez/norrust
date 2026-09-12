"""Bounded Fireworks observer preflight and labelled evaluation runner."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .model_usage import ModelCall, aggregate_calls, dedupe_calls
from .watchdog_observer import (DEFAULT_MODEL, FireworksObserverBackend,
                                ObserverTransportError)
from .watchdog_replay import replay_case

MAX_EVALUATION_CALLS = 37
MAX_CASE_CALLS = 3


def _is_quota_failure(error: BaseException) -> bool:
    code = str(getattr(error, "provider_code", "") or "").lower()
    message = str(error).lower()
    if code in {"insufficient_credit", "insufficient_credits", "account_quota_exceeded",
                "spending_limit_exceeded", "billing_hard_limit", "payment_required"}:
        return True
    # Billing language is authoritative even when the provider uses HTTP 429.
    return any(phrase in message for phrase in
               ("insufficient credit", "credit balance is exhausted",
                "exhausted credits", "credits exhausted", "out of credits",
                "spending limit exceeded", "billing hard limit"))


def _error_record(error: BaseException) -> dict[str, Any]:
    status = getattr(error, "status", None)
    code = str(getattr(error, "provider_code", "") or "").lower()
    config_code = code in {"invalid_api_key", "model_not_found", "invalid_request",
                          "invalid_request_error", "unsupported_model", "unsupported_parameter"}
    return {"provider": "fireworks", "status": getattr(error, "status", None),
            "code": getattr(error, "provider_code", None),
            "message": str(error)[:512],
            "quota_exhausted": _is_quota_failure(error),
            "authorization_or_config": status in {400, 401, 403, 404, 422} or config_code}


class EvaluationBackend:
    """Share one provider backend and physical-call ceiling across all cases."""

    def __init__(self, backend: Any, *, max_calls: int = MAX_EVALUATION_CALLS) -> None:
        self.backend = backend
        self.provider = backend.provider
        self.transport_name = backend.transport_name
        self.max_calls = max_calls
        self.calls = 0
        self.quota_exhausted = False
        self.last_error: dict[str, Any] | None = None

    @property
    def halted(self) -> bool:
        return self.quota_exhausted or bool(
            self.last_error and self.last_error.get("authorization_or_config"))

    def prepare(self, *args, **kwargs):
        return self.backend.prepare(*args, **kwargs)

    def make_dispatch_call(self, *args, **kwargs):
        if self.quota_exhausted:
            raise ObserverTransportError("evaluation stopped after confirmed exhausted credit")
        if self.calls >= self.max_calls:
            raise ObserverTransportError("evaluation physical call cap exhausted")
        self.calls += 1
        return self.backend.make_dispatch_call(*args, **kwargs)

    def observe(self, *args, **kwargs):
        try:
            return self.backend.observe(*args, **kwargs)
        except Exception as error:
            self.last_error = _error_record(error)
            self.quota_exhausted = _is_quota_failure(error)
            raise


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _preflight(backend: EvaluationBackend, root: Path) -> dict[str, Any]:
    packet = {"stage": "active", "observation_sequence": 0, "alerts": [],
              "degraded": False, "coverage_events": []}
    call: ModelCall | None = None
    request: dict[str, Any] | None = None
    response: Any = None
    try:
        prepared = backend.prepare(packet)
        request = prepared[0] if isinstance(prepared, tuple) else prepared
        call = backend.make_dispatch_call("preflight", "observer-preflight-1")
        result = backend.observe(packet, call_id=call.call_id, game_id="preflight")
        final = result.call
        response = result.response
        report = {"status": "passed", "dispatches": 1,
                  "settings": {"model": getattr(backend.backend, "model", None),
                               "estimated_input_tokens": 4096, "max_output_tokens": 512,
                               "reasoning_effort": None},
                  "decision": result.decision.as_dict(), "request": request,
                  "receipt": response, "call": final.to_row()}
    except Exception as error:
        final = getattr(error, "call", None) or call
        response = getattr(error, "response", None)
        # A schema/configuration failure can happen after dispatch without
        # attaching a terminal call. Preserve that physical attempt explicitly.
        if isinstance(final, ModelCall) and final.status != "failed":
            final = dataclasses.replace(final, status="failed",
                                        error_code=type(error).__name__)
        if isinstance(final, ModelCall) and final.raw_usage_json is None and response is not None:
            final.raw_usage_json = response
        report = {"status": "failed", "dispatches": 1 if call else 0,
                  "settings": {"model": getattr(backend.backend, "model", None),
                               "estimated_input_tokens": 4096, "max_output_tokens": 512,
                               "reasoning_effort": None},
                  "error": _error_record(error),
                  "request": request, "receipt": response,
                  "call": final.to_row() if isinstance(final, ModelCall) else None}
    _write_json(root / "preflight.json", report)
    return report


def _unattempted(case: dict[str, Any], root: Path, *, reason: str) -> dict[str, Any]:
    case_id = str(case["case_id"])
    case_root = root / case_id
    report = {"case": case_id, "status": {"stage": "not_attempted"},
              "metrics": {"case_id": case_id, "expected": case.get("expected"),
                          "scored": False, "false_stop": None, "missed_loop": None,
                          "observer_calls": 0, "observer_verdicts": 0,
                          "observer_failures": 0, "unattempted_reason": reason},
              "model_evaluation": {"status": "not_attempted", "network_calls": 0}}
    _write_json(case_root / "report.json", report)
    return report


def _calls_from_row(row: Any) -> ModelCall | None:
    if not isinstance(row, dict):
        return None
    fields = {name: row[name] for name in ModelCall.__dataclass_fields__ if name in row}
    fields.pop("normalization_gaps", None)
    try:
        call = ModelCall(**fields)
    except TypeError:
        return None
    gaps = row.get("normalization_gaps")
    call.normalization_gaps = list(gaps) if isinstance(gaps, list) else []
    return call


def _evaluation_usage(results: list[dict[str, Any]], root: Path,
                      preflight: dict[str, Any]) -> list[ModelCall]:
    """Collect and lifecycle-dedupe measured calls, including preflight."""
    calls: list[ModelCall] = []
    preflight_call = _calls_from_row(preflight.get("call"))
    if preflight_call is not None:
        calls.append(preflight_call)
    for result in results:
        case_id = result.get("case")
        if isinstance(case_id, str):
            sidecar = root / case_id / "usage.ndjson"
            try:
                from .game_history import _read_usage_sidecar
                case_calls, _malformed = _read_usage_sidecar(sidecar)
            except OSError:
                case_calls = []
            calls.extend(case_calls)
    deduped, _conflicts = dedupe_calls(calls)
    return deduped


def _source_identity(model: str, rates_path: Path) -> dict[str, Any]:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                text=True, check=False).stdout.strip() or None
    except OSError:
        commit = None
    try:
        rate_sha256 = hashlib.sha256(rates_path.read_bytes()).hexdigest()
    except OSError:
        rate_sha256 = None
    return {"commit": commit, "model": model,
            "settings": {"estimated_input_tokens": 4096, "max_output_tokens": 512,
                          "reasoning_effort": None},
            "rates": {"file": str(rates_path.resolve()), "sha256": rate_sha256,
                      "source": "https://docs.fireworks.ai/serverless/pricing"}}


def evaluate(cases: list[dict[str, Any]], output_dir: str | Path, *, fake: bool = False,
             model: str = DEFAULT_MODEL) -> dict[str, Any]:
    root = Path(output_dir).resolve()
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"refusing to reuse evaluation output directory: {root}")
    root.mkdir(parents=True, exist_ok=True)
    if fake:
        from .watchdog_replay import replay_cases
        aggregate = replay_cases(cases, root, fake=True)
        aggregate["preflight"] = {"status": "skipped_fake", "dispatches": 0}
        aggregate["evaluation"] = {"attempted_cases": len(cases), "unattempted_cases": 0,
                                    "physical_calls": aggregate["metrics"]["observer_calls"],
                                    "maximum_calls": MAX_EVALUATION_CALLS}
        _write_json(root / "report.json", aggregate)
        return aggregate

    shared = EvaluationBackend(FireworksObserverBackend(model=model))
    preflight = _preflight(shared, root)
    results: list[dict[str, Any]] = []
    if preflight["status"] != "passed":
        error = preflight.get("error", {})
        reason = ("confirmed_exhausted_credit" if error.get("quota_exhausted") else
                  "authorization_or_config_failure" if error.get("authorization_or_config") else
                  "preflight_failed")
        results = [_unattempted(case, root, reason=reason) for case in cases]
    else:
        for index, case in enumerate(cases):
            if shared.quota_exhausted or shared.calls >= MAX_EVALUATION_CALLS:
                results.extend(_unattempted(item, root, reason=(
                    "confirmed_exhausted_credit" if shared.quota_exhausted else "physical_call_cap")
                    ) for item in cases[index:])
                break
            results.append(replay_case(case, root, fake=False, model=model, backend=shared))
            if shared.quota_exhausted or (shared.last_error or {}).get("authorization_or_config"):
                reason = ("confirmed_exhausted_credit" if shared.quota_exhausted
                          else "authorization_or_config_failure")
                results.extend(_unattempted(item, root, reason=reason)
                               for item in cases[index + 1:])
                break
    metrics = [item["metrics"] for item in results]
    scored = [item for item in metrics if item.get("scored")]
    preflight_failed = int(preflight.get("status") == "failed")
    failures = preflight_failed + sum(int(item.get("observer_failures", 0)) for item in metrics)
    case_verdicts = sum(int(item.get("observer_verdicts", 0)) for item in metrics)
    preflight_verdicts = int(preflight.get("status") == "passed")
    verdicts = preflight_verdicts + case_verdicts
    failure_reasons: dict[str, int] = {}
    evidence_gaps: dict[str, int] = {}
    if preflight_failed:
        reason = str(preflight.get("error", {}).get("code") or
                     preflight.get("error", {}).get("message") or "preflight_failed")
        failure_reasons[reason] = 1
    for item in metrics:
        for reason, count in (item.get("observer_failure_reasons") or {}).items():
            failure_reasons[str(reason)] = failure_reasons.get(str(reason), 0) + int(count)
        for reason, count in (item.get("evidence_gaps") or {}).items():
            evidence_gaps[str(reason)] = evidence_gaps.get(str(reason), 0) + int(count)
    attempted_partial = any(item.get("model_evaluation", {}).get("status") in {"partial", "failed"}
                            for item in results if item.get("status", {}).get("stage") != "not_attempted")
    status = ("failed" if not scored else
              "partial" if failures or len(scored) != len(cases) or attempted_partial else
              "completed")
    calls = _evaluation_usage(results, root, preflight)
    usage_aggregate = aggregate_calls(calls)
    rates_path = Path(__file__).with_name("fixtures") / "watchdog_stack4" / "fireworks-rates.json"
    from .usage_cost import role_cost_report
    costs = role_cost_report(calls, rates_path)
    observer_cost = dict(costs["observer"])
    observer_cost.update({"currency": "USD", "source": "https://docs.fireworks.ai/serverless/pricing",
                          "rate_file": costs.get("rate_file"),
                          "rate_sha256": costs.get("rate_sha256"),
                          "rates_used": costs.get("rates_used", [])})
    aggregate = {"schema_version": 1, "mode": "model", "preflight": preflight,
                 "source": _source_identity(model, rates_path),
                 "model_evaluation": {"status": status, "network_calls": shared.calls,
                                      "verdicts": verdicts, "failures": failures,
                                      "failure_reasons": failure_reasons,
                                      "evidence_gaps": evidence_gaps,
                                      "cases_scored": len(scored),
                                      "cases_without_judgment": len(cases) - len(scored),
                                      "usage": {"status": ("unknown" if not calls else
                                                             "measured" if usage_aggregate["total_tokens"]["fully_measured"]
                                                             else "partial_unknown"),
                                                 "calls": len(calls),
                                                 **{field: usage_aggregate[field] for field in
                                                    ("input_tokens", "cached_input_tokens",
                                                     "cache_write_input_tokens", "output_tokens",
                                                     "reasoning_tokens", "total_tokens")}},
                                      "cost": observer_cost},
                 "evaluation": {"attempted_cases": sum(item["status"].get("stage") != "not_attempted"
                                                          for item in results),
                                "unattempted_cases": sum(item["status"].get("stage") == "not_attempted"
                                                          for item in results),
                                "physical_calls": shared.calls,
                                "maximum_calls": MAX_EVALUATION_CALLS},
                 "metrics": {"cases": len(cases), "cases_scored": len(scored),
                             "cases_without_judgment": len(cases) - len(scored),
                             "false_stops": sum(item["false_stop"] for item in scored) if scored else None,
                             "missed_loops": (sum(item["missed_loop"] for item in scored
                                                  if item.get("missed_loop") is not None)
                                              if any(item.get("missed_loop") is not None for item in scored)
                                              else None),
                             "observer_calls": sum(item.get("observer_calls", 0) for item in metrics),
                             "observer_verdicts": case_verdicts,
                             "observer_failures": sum(int(item.get("observer_failures", 0)) for item in metrics),
                             "evidence_gaps": evidence_gaps,
                             "preflight_verdicts": preflight_verdicts,
                             "preflight_failures": preflight_failed},
                 "cases": results}
    _write_json(root / "report.json", aggregate)
    return aggregate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    cases_path = args.manifest.with_name(manifest["cases_file"])
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    print(json.dumps(evaluate(cases, args.output_dir, fake=args.fake, model=args.model), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
