#!/usr/bin/env python3
"""Replay bounded watchdog fixtures through the maintained observer controller."""
from __future__ import annotations

import argparse
import base64
import json
import time
from pathlib import Path
from typing import Any

from .llm_supervisor import _watchdog_validation
from .run_watchdog import RunWatchdog
from .watchdog_observer import (FakeObserverBackend, ObserverController,
                                 OpenAIObserverBackend, REQUEST_TIMEOUT_SECONDS)


class ReplayClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _decision(kind: str = "continue", reason: str = "offline_fixture") -> dict[str, Any]:
    return {"decision": kind, "reason_code": reason, "evidence_ids": [],
            "explanation": "offline scheduling fixture"}


def _append_chunk(root: Path, sequence: int, value: str) -> None:
    directory = root / "fixture-call"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "chunks.ndjson").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"sequence": sequence,
                                 "data_b64": base64.b64encode(value.encode()).decode()}) + "\n")



class RecordingBackend:
    """Persist observer request payloads beside fake or provider receipts."""

    def __init__(self, backend: Any, payload_path: Path):
        self.backend = backend
        self.payload_path = payload_path
        self.provider = backend.provider
        self.transport_name = backend.transport_name

    def prepare(self, packet, evidence=()):
        result = self.backend.prepare(packet, evidence)
        self.payload_path.parent.mkdir(parents=True, exist_ok=True)
        with self.payload_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(result[0], sort_keys=True) + "\n")
        return result

    def make_dispatch_call(self, *args, **kwargs):
        return self.backend.make_dispatch_call(*args, **kwargs)

    def observe(self, *args, **kwargs):
        result = self.backend.observe(*args, **kwargs)
        # Keep provider/fake receipts next to the request payload.  The
        # controller also writes normalized usage rows; this file preserves
        # the response body for offline review and provenance.
        receipt = {
            "call": result.call.to_row(),
            "decision": result.decision.as_dict(),
            "response": result.response,
            "coverage": result.coverage,
        }
        with self.payload_path.with_name("observer_receipts.ndjson").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(receipt, sort_keys=True, default=str) + "\n")
        return result


def _fake_response(payload: dict[str, Any], calls: list[int]) -> dict[str, Any]:
    """Return recommendations from packet alerts only; expected labels stay out."""
    try:
        packet = json.loads(payload.get("input", "{}")).get("watchdog_packet", {})
    except (TypeError, ValueError, json.JSONDecodeError):
        packet = {}
    calls[0] += 1
    evidence_ids = (packet.get("evidence_ids", [])[:1]
                    if isinstance(packet, dict) and isinstance(packet.get("evidence_ids"), list)
                    else [])
    if isinstance(packet, dict) and packet.get("alerts"):
        # A first alert is observed conservatively. The second observation
        # requests bounded inspection; its follow-up can then recommend stop
        # with the recorded evidence reference. This reaches the controller's
        # two-observation policy in three calls total.
        if calls[0] == 2:
            return _decision("inspect", "check_alert").copy() | {"evidence_ids": evidence_ids}
        if calls[0] >= 3:
            return _decision("stop", "repeated_no_progress").copy() | {"evidence_ids": evidence_ids}
    return _decision()


VERDICT_EVENTS = ("verdict", "investigation_verdict")
FAILURE_EVENTS = ("verdict_error", "investigation_error", "preflight_error")


def _call_outcomes(journal_path: Path) -> dict[str, Any]:
    """Separate observed model judgments from calls that never returned one.

    A dispatched call proves only that a request left the controller. Without
    this split a run whose every call failed is indistinguishable from a model
    that judged every case and declined to stop.
    """
    verdicts = 0
    judgments = 0
    failures = 0
    reasons: dict[str, int] = {}
    if journal_path.exists():
        try:
            lines = journal_path.read_text(encoding="utf-8").splitlines()[:4096]
        except (OSError, UnicodeError):
            lines = []
            failures += 1
            reasons["journal_unavailable"] = 1
        for line in lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # A torn trailing write must not be scored as a judgment.
                failures += 1
                reasons["unreadable_journal_entry"] = reasons.get("unreadable_journal_entry", 0) + 1
                continue
            if not isinstance(event, dict):
                failures += 1
                reasons["journal_record_not_object"] = reasons.get("journal_record_not_object", 0) + 1
                continue
            kind = event.get("type")
            decision = event.get("decision")
            # An inspect is only an intermediate request. It becomes a usable
            # judgment when its required investigation returns a verdict.
            if kind in VERDICT_EVENTS:
                verdicts += 1
            if kind == "investigation_verdict" or (kind == "verdict" and decision != "inspect"):
                judgments += 1
            elif kind in FAILURE_EVENTS:
                failures += 1
                reason = event.get("error") or kind
                reasons[str(reason)] = reasons.get(str(reason), 0) + 1
    return {"observer_verdicts": verdicts, "usable_judgments": judgments,
            "observer_failures": failures,
            "observer_failure_reasons": reasons, "judgment_observed": judgments > 0}


def _merge_reasons(target: dict[str, int], source: Any) -> None:
    if isinstance(source, dict):
        for reason, count in source.items():
            target[str(reason)] = target.get(str(reason), 0) + int(count)


def _drain(controller: ObserverController,
           timeout: float = REQUEST_TIMEOUT_SECONDS + 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while controller.active:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            controller.wait(remaining)
        except Exception:
            return False
    return True


def replay_case(case: dict[str, Any], output_dir: str | Path, *, fake: bool = True,
                model: str | None = None) -> dict[str, Any]:
    """Replay one case into a persistent per-case directory."""
    root = Path(output_dir).resolve() / str(case["case_id"])
    root.mkdir(parents=True, exist_ok=True)
    log = root / "case.ndjson"
    if log.exists():
        raise FileExistsError(f"refusing to overwrite existing replay evidence: {log}")
    evidence = root / "case.evidence"
    chunks = case.get("stream_chunks")
    if not isinstance(chunks, list) or not all(isinstance(item, str) for item in chunks):
        chunks = [f"data: {json.dumps({'choices': [{'delta': {'content': 'fixture evidence for ' + str(case['case_id'])}}]})}\n\n"]
    clock = ReplayClock()
    # An empty sidecar is an explicit unknown-usage source. Leaving it absent
    # would mark every packet degraded before the first observer receipt and
    # correctly prevent a policy-valid stop.
    usage_path = root / "usage.ndjson"
    usage_path.touch()
    log.touch()
    watchdog = RunWatchdog(log, str(case["case_id"]), evidence_dir=evidence,
                           clock=clock, poll_interval=0)
    metadata = next((item for item in (case.get("timeline") or [])
                     if isinstance(item, dict) and item.get("type") == "metadata"), {})
    conversation_id = metadata.get("conversation_id") if isinstance(metadata, dict) else None
    if not isinstance(conversation_id, str) or not conversation_id:
        conversation_id = None
    # Match attach_observer's run-owned state filename so review can consume
    # the replay archive through its normal read-only path.
    observer_state = watchdog.run_directory / "observer-state.json"
    fake_calls = [0]
    base = (FakeObserverBackend(lambda payload: _fake_response(payload, fake_calls))
            if fake else OpenAIObserverBackend(model=model or "gpt-5.4-nano"))
    payload_path = root / "observer_payloads.ndjson"
    receipt_path = root / "observer_receipts.ndjson"
    payload_path.touch()
    receipt_path.touch()
    backend = RecordingBackend(base, payload_path)
    stopped: list[dict[str, Any]] = []
    validations: list[dict[str, Any]] = []
    def record_stop(run: str, reason: str, ids: Any, sequence: int) -> None:
        intent = {"run_id": run, "reason_code": reason,
                  "evidence_ids": list(ids), "observed_sequence": sequence}
        try:
            valid, validation_reason = _watchdog_validation(log, intent)
        except Exception as exc:
            valid, validation_reason = False, type(exc).__name__
        validations.append({"valid": bool(valid), "reason": validation_reason})
        stopped.append(dict(intent, at=clock.now, controller_allowed=True,
                            validation_reason=validation_reason))
    controller = ObserverController(
        str(case["case_id"]), observer_state, backend=backend, catalog_game_id=conversation_id,
        mode="enforce", progress=lambda _run: watchdog.status(),
        evidence_reader=lambda _run, evidence_id, offset, limit: watchdog.read_evidence(evidence_id, offset, limit),
        stop=record_stop,
        usage_sidecar=usage_path, clock=clock, max_calls=3)
    first_alert_at = None
    stop_verdict_at = None
    try:
        timeline = case.get("timeline") if isinstance(case.get("timeline"), list) else []
        timeline_times = case.get("timeline_times")
        if (not isinstance(timeline_times, list) or len(timeline_times) != len(timeline)
                or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in timeline_times)):
            timeline_times = [index * 300 for index in range(len(timeline))]
        status_path = root / "status.ndjson"
        for index, record in enumerate(timeline):
            clock.now = float(timeline_times[index])
            with log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
            historical_complete = (case.get("provenance", {}).get("kind") == "historical"
                                    and record.get("type") == "model_request"
                                    and record.get("status") == "completed")
            if historical_complete:
                # Historical excerpts are evidence from the completed
                # request. Do not make their bytes visible at startup or
                # during the preceding driver/turn records.
                for chunk_index, chunk in enumerate(chunks):
                    _append_chunk(evidence, chunk_index, chunk)
            elif case.get("provenance", {}).get("kind") != "historical" and index < len(chunks):
                _append_chunk(evidence, index, chunks[index])
            packet = watchdog.poll(force=True)
            if first_alert_at is None and packet.get("alerts"):
                first_alert_at = clock.now
            if int(controller.state.get("dispatched_calls", 0)) < 3:
                controller.poll(packet)
            _drain(controller)
            verdict = controller.state.get("last_verdict")
            if (stop_verdict_at is None and isinstance(verdict, dict)
                    and verdict.get("decision") == "stop"):
                stop_verdict_at = clock.now
            with status_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(packet, sort_keys=True) + "\n")
        _drain(controller)
        # Give one final regular observation a bounded opportunity to run.
        # This is still inside the fixture call ceiling and allows an alert
        # first seen on the final timeline record to reach its inspect
        # investigation before the archive closes.
        clock.now += 300.0
        final_packet = watchdog.poll(force=True)
        if int(controller.state.get("dispatched_calls", 0)) < 3:
            controller.poll(final_packet)
        drained = _drain(controller)
        with status_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(final_packet, sort_keys=True) + "\n")
        verdict = controller.state.get("last_verdict")
        if (stop_verdict_at is None and isinstance(verdict, dict)
                and verdict.get("decision") == "stop"):
            stop_verdict_at = clock.now
        final = watchdog.poll(force=True)
        # The controller's bounded drain has already given completed calls a
        # chance to publish their callback. Never add an unbounded future wait
        # to replay cleanup after a backend deadline.
        controller.close(wait=False)
        dispatched = int(controller.state.get("dispatched_calls", 0))
        last_verdict = controller.state.get("last_verdict")
        raw_stop = isinstance(last_verdict, dict) and last_verdict.get("decision") == "stop"
        observed_stop = bool(stopped)
        expected = case.get("expected")
        outcomes = _call_outcomes(observer_state.with_suffix(".journal.ndjson"))
        validated = any(item["valid"] for item in validations)
        # A case the model never actually judged is unscored, not passed. Only
        # a validated stop is self-evidencing: it cannot occur without a verdict.
        scored = outcomes["judgment_observed"] or validated
        metric = {
            "case_id": case.get("case_id"), "expected": expected,
            "observed_stop": observed_stop,
            "controller_stop_recommendation": observed_stop,
            "raw_stop_recommendation": raw_stop,
            "validated_would_stop": validated,
            "stop_validation": validations[-1] if validations else None,
            "scored": scored,
            "false_stop": (validated and expected in {"continue", "inspect"}) if scored else None,
            "missed_loop": (expected == "stop" and not validated) if scored else None,
            **outcomes,
            "first_alert_at_seconds": first_alert_at,
            "stop_verdict_at_seconds": stop_verdict_at,
            "detection_delay_seconds": (None if first_alert_at is None or stop_verdict_at is None
                                         else max(0.0, stop_verdict_at - first_alert_at)),
            "observer_calls": dispatched, "drain_timed_out": not drained,
            "usage_coverage": final.get("usage_coverage"),
            "alerts": len(final.get("alerts", [])),
        }
        if fake:
            case_evaluation = {"status": "not_run", "network_calls": 0}
        elif not scored:
            case_evaluation = {"status": "failed", "network_calls": dispatched,
                               "verdicts": outcomes["observer_verdicts"],
                               "failures": outcomes["observer_failures"],
                               "failure_reasons": outcomes["observer_failure_reasons"]}
        elif outcomes["observer_failures"]:
            case_evaluation = {"status": "partial", "network_calls": dispatched,
                               "verdicts": outcomes["observer_verdicts"],
                               "failures": outcomes["observer_failures"],
                               "failure_reasons": outcomes["observer_failure_reasons"]}
        else:
            case_evaluation = {"status": "completed", "network_calls": dispatched,
                               "verdicts": outcomes["observer_verdicts"], "failures": 0}
        report = {"case": case.get("case_id"), "status": final,
                  "metrics": metric, "observer_state": controller.state,
                  "model_evaluation": case_evaluation}
        (root / "report.json").write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
        return report
    finally:
        if controller.active:
            controller.close(wait=False)


def replay_cases(cases: list[dict[str, Any]], output_dir: str | Path, *, fake: bool = True,
                 model: str | None = None) -> dict[str, Any]:
    results = [replay_case(case, output_dir, fake=fake, model=model) for case in cases]
    metrics = [result["metrics"] for result in results]
    scored = [item for item in metrics if item["scored"]]
    verdicts = sum(item["observer_verdicts"] for item in metrics)
    failures = sum(item["observer_failures"] for item in metrics)
    reasons: dict[str, int] = {}
    for item in metrics:
        _merge_reasons(reasons, item["observer_failure_reasons"])
    if fake:
        # No provider was contacted, so there is no model judgment to report.
        evaluation: dict[str, Any] = {"status": "not_run", "network_calls": 0}
    else:
        if not scored:
            status = "failed"
        elif failures or len(scored) != len(metrics):
            status = "partial"
        else:
            status = "completed"
        evaluation = {"status": status,
                      "network_calls": sum(item["observer_calls"] for item in metrics),
                      "verdicts": verdicts, "failures": failures,
                      "failure_reasons": reasons,
                      "cases_scored": len(scored),
                      "cases_without_judgment": len(metrics) - len(scored)}
    aggregate = {"schema_version": 1, "mode": "fake" if fake else "model",
            "model_evaluation": evaluation,
            # Detection rates are reported over scored cases only; with nothing
            # scored they are unknown rather than a clean zero.
            "metrics": {"cases": len(metrics), "cases_scored": len(scored),
                        "cases_without_judgment": len(metrics) - len(scored),
                        "false_stops": sum(item["false_stop"] for item in scored) if scored else None,
                        "missed_loops": sum(item["missed_loop"] for item in scored) if scored else None,
                        "detection_delays_seconds": [item["detection_delay_seconds"] for item in metrics if item["detection_delay_seconds"] is not None],
                        "observer_calls": sum(item["observer_calls"] for item in metrics),
                        "observer_verdicts": verdicts, "observer_failures": failures,
                        "observer_failure_reasons": reasons,
                        "usage_coverage": [item["usage_coverage"] for item in metrics]},
            "cases": results}
    # Keep a durable aggregate beside the case directories. It is the same
    # object emitted by the CLI and gives review tooling one bounded artifact.
    aggregate_path = Path(output_dir).resolve() / "report.json"
    aggregate_path.write_text(json.dumps(aggregate, sort_keys=True) + "\n", encoding="utf-8")
    return aggregate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fake", action="store_true", help="use FakeObserverBackend; no network calls")
    parser.add_argument("--model", help="use OpenAI observer backend with this model")
    args = parser.parse_args(argv)
    if not args.fake and not args.model:
        parser.error("select --fake or --model")
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    cases_path = args.manifest.with_name(payload["cases_file"])
    cases = json.loads(cases_path.read_text(encoding="utf-8")).get("cases", [])
    print(json.dumps(replay_cases(cases, args.output_dir, fake=args.fake, model=args.model), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
