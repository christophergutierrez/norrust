import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from .watchdog_observer import (
    MAX_CALLS,
    MAX_INPUT_TOKENS,
    FakeObserverBackend,
    ObserverController,
    ObserverDecision,
    ObserverInputError,
    ObserverResponseError,
    ObserverSchemaError,
    ObserverTimeout,
    FireworksObserverBackend,
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    OBSERVER_PROFILE,
    _post_chat_completions,
    build_observer_request,
    conservative_token_count,
)


def decision(kind="continue", reason="ok", ids=None):
    return {"decision": kind, "reason_code": reason,
            "evidence_ids": ids or [], "explanation": "fixture"}


class DecisionValidationTests(unittest.TestCase):
    def test_response_is_strict_and_bounded(self):
        parsed = ObserverDecision.parse(decision("inspect", "check", ["e1"]))
        self.assertEqual(parsed.evidence_ids, ("e1",))
        with self.assertRaises(ObserverSchemaError):
            ObserverDecision.parse(dict(decision(), extra="injected"))
        with self.assertRaises(ObserverSchemaError):
            ObserverDecision.parse(decision("stop", "bad", [str(i) for i in range(9)]))

    def test_selected_profile_is_sent_exactly_to_fake_http_transport(self):
        seen = []
        backend = FireworksObserverBackend(
            api_key="test", transport=lambda payload, _timeout: (
                seen.append(payload) or {"id": "profile-1", "model": DEFAULT_MODEL,
                "choices": [{"finish_reason": "stop", "message": {
                    "content": json.dumps(decision())}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11}}))
        result = backend.observe({"stage": "active", "observation_sequence": 1, "alerts": []},
                                 call_id="profile-call", game_id="g")
        self.assertEqual(seen[0]["model"], DEFAULT_MODEL)
        self.assertEqual(seen[0]["reasoning_effort"], DEFAULT_EFFORT)
        self.assertEqual(result.call.requested_model, DEFAULT_MODEL)
        self.assertEqual(result.call.requested_reasoning_effort, DEFAULT_EFFORT)

    def test_request_has_no_tools_and_counts_full_framing(self):
        payload, clipped, coverage = build_observer_request(
            {"stage": "active", "observation_sequence": 1, "alerts": []})
        self.assertNotIn("tools", payload)
        self.assertEqual(payload["max_tokens"], 512)
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][1]["role"], "user")
        self.assertIn("json_schema", payload["response_format"])
        self.assertNotIn("text", payload)
        self.assertEqual(set(payload), {"model", "messages", "max_tokens", "response_format", "reasoning_effort"})
        self.assertEqual(payload["model"], DEFAULT_MODEL)
        self.assertEqual(payload["reasoning_effort"], DEFAULT_EFFORT)
        self.assertNotIn("reasoning", payload)
        self.assertLessEqual(conservative_token_count(json.dumps(payload)), MAX_INPUT_TOKENS)
        self.assertFalse(clipped)
        self.assertEqual(coverage, "complete")

    def test_response_schema_is_constrained_by_trusted_phase_and_budget(self):
        def choices(packet):
            payload, _clipped, _coverage = build_observer_request(packet)
            schema = payload["response_format"]["json_schema"]["schema"]
            return schema["properties"]["decision"]["enum"]

        # Preflight and an unconfirmed initial observation are continue-only.
        self.assertEqual(choices({"stage": "active"}), ["continue"])
        self.assertEqual(choices({
            "stage": "active", "controller_context": {
                "phase": "initial", "incident_identity": "incident",
                "distinct_observation_count": 1,
                "required_distinct_observations": 2,
                "available_evidence_ids": ["e1"], "remaining_calls": 2,
            }}), ["continue"])
        # An initial inspection is available only when a follow-up slot exists.
        self.assertEqual(choices({
            "stage": "active", "controller_context": {
                "phase": "initial", "incident_identity": "incident",
                "distinct_observation_count": 2,
                "required_distinct_observations": 2,
                "available_evidence_ids": ["e1"], "remaining_calls": 1,
            }}), ["continue", "inspect"])
        self.assertEqual(choices({
            "stage": "active", "controller_context": {
                "phase": "initial", "incident_identity": "incident",
                "distinct_observation_count": 2,
                "required_distinct_observations": 2,
                "available_evidence_ids": ["e1"], "remaining_calls": 0,
            }}), ["continue"])
        self.assertEqual(choices({
            "stage": "active", "controller_context": {
                "phase": "investigation", "remaining_calls": 0,
            }}), ["continue", "stop"])

    def test_phase_invalid_provider_choice_is_failed_with_receipt_and_usage(self):
        packet = {"stage": "active", "observation_sequence": 2,
                  "controller_context": {"phase": "investigation"}}
        backend = FireworksObserverBackend(api_key="test", transport=lambda _payload, _timeout: {
            "id": "phase-invalid", "model": DEFAULT_MODEL,
            "choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps(decision("inspect", "recursive", ["e1"]))}}],
            "usage": {"prompt_tokens": 21, "completion_tokens": 4, "total_tokens": 25}})
        with self.assertRaises(ObserverResponseError) as caught:
            backend.observe(packet, call_id="phase-invalid-call", game_id="g")
        self.assertEqual(caught.exception.call.error_code, "schema_error")
        self.assertEqual(caught.exception.call.input_tokens, 21)
        self.assertEqual(caught.exception.call.output_tokens, 4)
        self.assertEqual(caught.exception.call.provider_response_id, "phase-invalid")

    def test_oversized_packet_is_clipped_with_incomplete_coverage(self):
        packet = {"stage": "active", "observation_sequence": 1, "alerts": [],
                  "recent_excerpt": "x" * 100000}
        payload, clipped, coverage = build_observer_request(packet)
        self.assertTrue(clipped)
        self.assertEqual(coverage, "bounded")
        self.assertLessEqual(conservative_token_count(json.dumps(payload)), MAX_INPUT_TOKENS)

    def test_large_required_evidence_is_clipped_and_marked(self):
        packet = {"stage": "active", "observation_sequence": 1,
                  "alerts": [], "required": "x" * 1000000}
        payload, clipped, coverage = build_observer_request(packet)
        self.assertTrue(clipped)
        self.assertEqual(coverage, "bounded")
        self.assertLessEqual(conservative_token_count(json.dumps(payload)), MAX_INPUT_TOKENS)

    def test_controller_context_clipping_is_incomplete_critical_coverage(self):
        packet = {"stage": "active", "observation_sequence": 1, "alerts": [],
                  "controller_context": {"detail": "x" * 100000}}
        payload, clipped, coverage = build_observer_request(packet)
        self.assertTrue(clipped)
        self.assertEqual(coverage, "incomplete")

    def test_two_bounded_evidence_slices_remain_usable(self):
        packet = {"stage": "request", "observation_sequence": 8,
                  "alerts": [{"identity": "incident"}], "coverage_events": [],
                  "degraded": False}
        evidence = [{"evidence_id": "e1", "data": "a" * 2048},
                    {"evidence_id": "e2", "data": "b" * 2048}]
        payload, clipped, coverage = build_observer_request(packet, evidence=evidence)
        self.assertTrue(clipped)
        self.assertEqual(coverage, "bounded")
        self.assertLessEqual(conservative_token_count(json.dumps(payload)), MAX_INPUT_TOKENS)

    def test_projection_deduplicates_transport_bytes_and_types_choices(self):
        packet = {"run_id": "r", "stage": "request", "observation_sequence": 8,
                  "revision": 2, "alerts": [], "evidence_ids": ["e1"],
                  "unbounded_internal_dump": "x" * 100000}
        evidence = [{"evidence_id": "e1", "kind": "chunks", "data": "text",
                     "data_b64": "cmVkdW5kYW50"}]
        payload, clipped, coverage = build_observer_request(packet, evidence=evidence)
        user = json.loads(payload["messages"][1]["content"])
        self.assertTrue(clipped)
        self.assertEqual(coverage, "bounded")
        self.assertEqual(user["evidence"][0]["type"], "chunks")
        self.assertNotIn("data_b64", user["evidence"][0])
        self.assertEqual(user["permitted_evidence_choices"][0]["evidence_id"], "e1")
        self.assertNotIn("unbounded_internal_dump", json.dumps(user["watchdog_packet"]))

    def test_fireworks_response_receipt_is_retained_when_decision_is_malformed(self):
        backend = FireworksObserverBackend(api_key="test", transport=lambda _payload, _timeout: {
            "id": "resp-1", "model": "accounts/fireworks/models/nemotron-lightning-3p5-30b-a3b",
            "choices": [{"message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}})
        with self.assertRaises(ObserverResponseError) as caught:
            backend.observe({"stage": "active", "observation_sequence": 1, "alerts": []},
                            call_id="c1", game_id="g")
        self.assertEqual(caught.exception.call.provider_response_id, "resp-1")
        self.assertEqual(caught.exception.call.input_tokens, 12)
        self.assertEqual(caught.exception.call.call_role, "observer")

    def test_truncated_json_is_rejected_even_when_content_is_parseable(self):
        backend = FireworksObserverBackend(api_key="test", transport=lambda _payload, _timeout: {
            "id": "resp-truncated", "model": DEFAULT_MODEL,
            "choices": [{"finish_reason": "length", "message": {
                "content": json.dumps(decision())}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 512, "total_tokens": 524}})
        with self.assertRaises(ObserverResponseError) as caught:
            backend.observe({"stage": "active", "observation_sequence": 1, "alerts": []},
                            call_id="c-truncated", game_id="g")
        self.assertEqual(caught.exception.call.error_code, "output_limit")
        self.assertEqual(caught.exception.call.requested_reasoning_effort, DEFAULT_EFFORT)

    def test_only_documented_profile_is_constructible(self):
        with self.assertRaisesRegex(ValueError, OBSERVER_PROFILE):
            FireworksObserverBackend(api_key="test", model="accounts/fireworks/models/nemotron-lightning-3p5-30b-a3b",
                                     reasoning_effort="none")

    def test_fireworks_does_not_accept_responses_api_output_fallback(self):
        backend = FireworksObserverBackend(api_key="test", transport=lambda _payload, _timeout: {
            "id": "resp-legacy", "output_text": json.dumps(decision()),
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}})
        with self.assertRaises(ObserverResponseError):
            backend.observe({"stage": "active", "observation_sequence": 1, "alerts": []},
                            call_id="c-legacy", game_id="g")

    def test_http_receipt_keeps_request_id_and_redacts_echoed_credential(self):
        class Response:
            headers = {"x-request-id": "provider-request-1"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"id": "resp-1", "choices": [],
                                   "echo": "secret"}).encode()

        with mock.patch("urllib.request.urlopen", return_value=Response()):
            result = _post_chat_completions({}, "secret", 1.0)
        self.assertEqual(result["_request_id"], "provider-request-1")
        self.assertEqual(result["echo"], "[redacted]")

    def test_fireworks_transport_has_wall_deadline_for_trickling_or_hung_call(self):
        def hang(_payload, _timeout):
            time.sleep(.2)
            return {}
        backend = FireworksObserverBackend(api_key="test", timeout_seconds=.03, transport=hang)
        started = time.monotonic()
        with self.assertRaises(ObserverTimeout):
            backend.observe({"stage": "active", "observation_sequence": 1, "alerts": []},
                            call_id="c1", game_id="g")
        self.assertLess(time.monotonic() - started, .15)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.clock_value = [0.0]
        self.current = [{"stage": "active", "observation_sequence": 1,
                         "alerts": [{"identity": "same"}], "evidence_ids": ["e1"],
                         "freshness": {"state": "fresh"}, "degraded": False,
                         "run_id": "run-uuid"}]
        self.stops = []

    def make(self, backend, *, mode="enforce", max_calls=MAX_CALLS, evidence_reader=None,
             progress=None, stop=None):
        self.temp = tempfile.TemporaryDirectory()
        controller = ObserverController(
            "run-uuid", Path(self.temp.name) / "watchdog.json", backend=backend,
            catalog_game_id="catalog-game", mode=mode,
            progress=progress or (lambda _run: self.current[0]),
            evidence_reader=evidence_reader or (lambda *_args: {"run_id": "run-uuid", "evidence_id": "e1", "data": "recorded"}),
            stop=stop or (lambda *args: self.stops.append(args)), clock=lambda: self.clock_value[0],
            usage_sidecar=Path(self.temp.name) / "usage.ndjson", max_calls=max_calls)
        return controller

    def confirm(self, controller, packet=None):
        """Record the first observation; return the confirmed second snapshot."""
        source = dict(packet or self.current[0])
        first = dict(source, observation_sequence=1)
        self.assertFalse(controller.poll(first))
        return dict(source, observation_sequence=2)

    def test_typed_unconfirmed_alert_is_deterministic_continue_without_paid_call(self):
        backend = FakeObserverBackend([decision()])
        controller = self.make(backend, mode="observe", max_calls=3)
        controller.state["non_progress"] = {}
        controller._persist()
        packet = {"stage": "active", "observation_sequence": 1, "revision": 1,
                  "alerts": [{"kind": "repeated_stream_passage", "identity": "raw-a"}],
                  "evidence_ids": ["e1"], "degraded": False, "run_id": "run-uuid"}
        self.assertFalse(controller.poll(packet))
        self.assertEqual(controller.state["dispatched_calls"], 0)
        journal = (Path(self.temp.name) / "watchdog.journal.ndjson").read_text()
        self.assertIn('"type":"deterministic_skip"', journal)
        self.assertIn('"paid_call":false', journal)

    def test_final_available_slot_is_continue_only_without_dispatch(self):
        controller = self.make(FakeObserverBackend([decision()]), mode="observe", max_calls=1)
        first = {"stage": "active", "observation_sequence": 1,
                 "alerts": [{"identity": "slot"}], "evidence_ids": ["e1"],
                 "run_id": "run-uuid"}
        self.assertFalse(controller.poll(first))
        self.assertFalse(controller.poll(dict(first, observation_sequence=2)))
        self.assertEqual(controller.state["dispatched_calls"], 0)
        self.assertEqual(controller.state["reserved_calls"], 0)
        self.assertEqual(controller.state["disabled_reason"], None)

    def test_no_alert_regular_window_is_recorded_as_controller_skip(self):
        controller = self.make(FakeObserverBackend([decision()]), mode="observe")
        self.clock_value[0] = 300
        packet = {"stage": "active", "observation_sequence": 1,
                  "alerts": [], "run_id": "run-uuid"}
        self.assertFalse(controller.poll(packet))
        self.assertEqual(controller.state["dispatched_calls"], 0)
        journal = (Path(self.temp.name) / "watchdog.journal.ndjson").read_text()
        self.assertIn('"reason_code":"no_current_incident"', journal)

    def test_preflight_failure_is_retained_without_physical_dispatch(self):
        class FailingPrepare(FakeObserverBackend):
            def prepare(self, packet, evidence=()):
                raise ObserverInputError("follow-up packet exceeds bound")
        controller = self.make(FailingPrepare([decision()]), mode="observe")
        packet = {"stage": "active", "observation_sequence": 3,
                  "alerts": [{"identity": "same"}], "evidence_ids": ["e1"],
                  "run_id": "run-uuid"}
        self.confirm(controller, packet)
        self.assertFalse(controller.poll(packet))
        self.assertEqual(controller.state["dispatched_calls"], 0)
        journal = (Path(self.temp.name) / "watchdog.journal.ndjson").read_text()
        self.assertIn('"type":"preparation_failed"', journal)
        self.assertIn('"paid_call":false', journal)

    def test_overlapping_typed_passages_share_request_scoped_incident(self):
        first = {"revision": 3, "current_request": {"harness_request_id": "req-1"},
                 "alerts": [{"kind": "repeated_stream_passage", "identity": "a",
                              "incident_id": "stream"}]}
        second = {"revision": 3, "current_request": {"harness_request_id": "req-1"},
                  "alerts": [{"kind": "repeated_stream_passage", "identity": "b",
                               "incident_id": "stream"}]}
        other = dict(second, current_request={"harness_request_id": "req-2"})
        self.assertEqual(ObserverController._packet_alert_id(first),
                         ObserverController._packet_alert_id(second))
        self.assertNotEqual(ObserverController._packet_alert_id(first),
                            ObserverController._packet_alert_id(other))
        generic_first = {"revision": 3, "current_request": {"request_id": "repair-1"},
                         "alerts": [{"identity": "same"}]}
        generic_second = dict(generic_first, current_request={"request_id": "repair-2"})
        self.assertNotEqual(ObserverController._packet_alert_id(generic_first),
                            ObserverController._packet_alert_id(generic_second))

    def tearDown(self):
        if hasattr(self, "controller"):
            self.controller.close(wait=True)
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def test_initial_empty_packet_waits_for_interval_but_alert_dispatches(self):
        self.controller = self.make(FakeObserverBackend([decision()]))
        self.assertFalse(self.controller.poll({"stage": "active", "observation_sequence": 1, "alerts": []}))
        self.assertFalse(self.controller.poll(self.current[0]))
        self.current[0] = dict(self.current[0], observation_sequence=2)
        self.assertTrue(self.controller.poll(self.current[0]))
        self.controller.wait(2)
        self.assertEqual(self.controller.state["dispatched_calls"], 1)

    def test_inspect_then_stop_requires_two_observations_and_recovery_check(self):
        backend = FakeObserverBackend([
            decision("inspect", "check", ["e1"]), decision("stop", "repeated_no_progress", ["e1"]),
        ])
        self.controller = self.make(backend)
        self.current[0] = self.confirm(self.controller)
        self.assertTrue(self.controller.poll(self.current[0]))
        self.controller.wait(2)
        self.clock_value[0] = 300
        self.current[0] = {"stage": "active", "observation_sequence": 4,
                           "alerts": [{"identity": "same"}], "evidence_ids": ["e1"],
                           "freshness": {"state": "fresh"}, "degraded": False,
                           "run_id": "run-uuid"}
        self.assertEqual(len(self.stops), 1)
        self.assertEqual(self.stops[0][0], "run-uuid")
        self.assertEqual(self.stops[0][1], "repeated_no_progress")
        rows = (Path(self.temp.name) / "usage.ndjson").read_text().splitlines()
        self.assertEqual(sum(json.loads(row)["call_role"] == "observer" for row in rows), 4)

    def test_cap_survives_restart_and_corrupt_state_disables(self):
        self.controller = self.make(FakeObserverBackend([decision()]))
        self.controller.state["dispatched_calls"] = MAX_CALLS
        self.controller._persist()
        self.controller.close(wait=True)
        self.controller = ObserverController("run-uuid", Path(self.temp.name) / "watchdog.json",
                                             backend=FakeObserverBackend([decision()]), mode="observe")
        self.assertFalse(self.controller.poll(self.current[0]))
        path = Path(self.temp.name) / "broken.json"
        path.write_text("not json")
        broken = ObserverController("run-uuid", path, backend=FakeObserverBackend([decision()]), mode="observe")
        self.assertFalse(broken.poll(self.current[0]))
        broken.close()

    def test_malformed_budget_state_fails_closed(self):
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / "broken-budget.json"
        path.write_text(json.dumps({"version": 1, "run_id": "run-uuid",
                                    "dispatched_calls": "not-a-count"}))
        controller = ObserverController("run-uuid", path,
                                        backend=FakeObserverBackend([decision()]), mode="observe")
        self.controller = controller
        self.assertEqual(controller.state["disabled_reason"], "corrupt_or_mismatched_state")
        self.assertFalse(controller.poll(self.current[0]))

    def test_close_does_not_allow_late_stop(self):
        self.controller = self.make(FakeObserverBackend([decision("inspect", "check", ["e1"])], delay=.1))
        self.current[0] = self.confirm(self.controller)
        self.assertTrue(self.controller.poll(self.current[0]))
        self.controller.close()
        time.sleep(.2)
        self.assertEqual(self.stops, [])

    def test_inspection_keeps_single_call_slot_during_blocking_evidence_read(self):
        entered = threading.Event()
        release = threading.Event()
        backend = FakeObserverBackend([
            decision("inspect", "check", ["e1"]), decision("stop", "repeated_no_progress", ["e1"]),
        ])
        self.temp = tempfile.TemporaryDirectory()
        controller = ObserverController(
            "run-uuid", Path(self.temp.name) / "watchdog.json", backend=backend,
            catalog_game_id="catalog-game", mode="enforce",
            progress=lambda _run: self.current[0],
            evidence_reader=lambda *_args: (entered.set(), release.wait(2),
                                             {"run_id": "run-uuid", "evidence_id": "e1", "data": "recorded"})[-1],
            stop=lambda *args: self.stops.append(args), clock=lambda: self.clock_value[0])
        self.controller = controller
        first = self.confirm(controller)
        self.current[0] = first
        self.assertTrue(controller.poll(first))
        self.assertTrue(entered.wait(1))
        self.clock_value[0] = 300
        self.current[0] = {"stage": "active", "observation_sequence": 4,
                           "alerts": [{"identity": "same"}], "evidence_ids": ["e1"],
                           "freshness": {"state": "fresh"}, "degraded": False,
                           "run_id": "run-uuid"}
        self.assertFalse(controller.poll(self.current[0]))
        release.set()
        controller.wait(2)
        self.assertEqual(controller.state["dispatched_calls"], 2)

    def test_new_alert_is_not_consumed_by_cooldown(self):
        self.controller = self.make(FakeObserverBackend([decision(), decision()]))
        first = {"stage": "active", "observation_sequence": 1,
                 "alerts": [{"identity": "first"}], "evidence_ids": ["e1"]}
        self.assertFalse(self.controller.poll(first))
        self.assertTrue(self.controller.poll(dict(first, observation_sequence=2)))
        self.controller.wait(2)
        # A distinct incident inside the cooldown is recorded but must remain
        # eligible after the cooldown expires.
        self.clock_value[0] = 30
        self.current[0] = {"stage": "active", "observation_sequence": 4,
                           "alerts": [{"identity": "second"}], "evidence_ids": ["e1"]}
        self.assertFalse(self.controller.poll(self.current[0]))
        self.clock_value[0] = 61
        self.current[0] = dict(self.current[0], observation_sequence=5)
        self.assertTrue(self.controller.poll(self.current[0]))
        self.controller.wait(2)
        self.assertEqual(self.controller.state["dispatched_calls"], 2)

    def test_progress_revision_resets_historical_alert_count(self):
        backend = FakeObserverBackend([decision()])
        self.controller = self.make(backend)
        packet = {"stage": "active", "observation_sequence": 1, "revision": 4,
                  "alerts": [{"identity": "same", "revision": 4}], "evidence_ids": ["e1"],
                  "freshness": {"state": "fresh"}, "degraded": False, "run_id": "run-uuid"}
        self.assertFalse(self.controller.poll(packet))
        packet = dict(packet, observation_sequence=2)
        self.assertTrue(self.controller.poll(packet)); self.controller.wait(2)
        self.clock_value[0] = 30
        recovered = {"stage": "active", "observation_sequence": 2, "revision": 5,
                     "committed_action": {"batch_id": "b5", "revision": 5},
                     # The recorder keeps this old alert in its packet.
                     "alerts": [{"identity": "same", "revision": 4}], "evidence_ids": ["e1"],
                     "freshness": {"state": "fresh"}, "degraded": False, "run_id": "run-uuid"}
        self.current[0] = recovered
        self.assertFalse(self.controller.poll(recovered))
        self.assertEqual(self.controller.state["non_progress"], {})
        self.assertEqual(self.stops, [])

    def test_request_contains_trusted_phase_confirmation_and_bounded_references(self):
        backend = FakeObserverBackend([decision(), decision()])
        self.controller = self.make(backend)
        source = dict(self.current[0], controller_context={"phase": "investigation",
                                                            "distinct_observation_count": 999},
                      evidence_ids=["e1", "e2", "e3"])
        self.confirm(self.controller, source)
        source = dict(source, observation_sequence=3)
        self.assertTrue(self.controller.poll(source))
        self.controller.wait(2)
        first = json.loads(backend.payloads[0]["messages"][-1]["content"])
        context = first["watchdog_packet"]["controller_context"]
        self.assertEqual(context["phase"], "initial")
        self.assertEqual(context["distinct_observation_count"], 2)
        self.assertEqual(context["available_evidence_ids"], ["e1", "e2", "e3"])
        self.assertNotIn("confirmation", context["prerequisites_missing"])
        self.assertIn("inspection", context["prerequisites_missing"])
        self.assertNotEqual(context["distinct_observation_count"], 999)
        self.clock_value[0] = 300
        second = dict(source, observation_sequence=4)
        self.current[0] = second
        self.assertTrue(self.controller.poll(second))
        self.controller.wait(2)
        payload = json.loads(backend.payloads[1]["messages"][-1]["content"])
        self.assertEqual(payload["watchdog_packet"]["controller_context"]["distinct_observation_count"], 3)

    def test_duplicate_sequence_cannot_confirm_or_stop(self):
        backend = FakeObserverBackend([decision()])
        self.controller = self.make(backend)
        packet = self.current[0]
        self.assertFalse(self.controller.poll(packet))
        packet = dict(packet, observation_sequence=2)
        self.assertTrue(self.controller.poll(packet))
        self.controller.wait(2)
        self.clock_value[0] = 300
        self.assertFalse(self.controller.poll(packet))
        self.assertEqual(self.stops, [])
        self.assertEqual(self.controller.state["dispatched_calls"], 1)

    def test_contract_following_observer_stops_in_three_calls_with_stale_progress(self):
        def follow_contract(payload):
            packet = json.loads(payload["messages"][-1]["content"])["watchdog_packet"]
            context = packet["controller_context"]
            if context["phase"] == "investigation":
                return decision("stop", "repeated_no_progress", ["e1"])
            if context["distinct_observation_count"] >= 2:
                return decision("inspect", "check", ["e1"])
            return decision("continue", "confirmation_missing")

        backend = FakeObserverBackend(follow_contract)
        self.controller = self.make(backend, max_calls=3)
        first = dict(self.current[0], freshness={"state": "stale"})
        self.assertFalse(self.controller.poll(dict(first, observation_sequence=1)))
        first = dict(first, observation_sequence=2)
        self.current[0] = first
        self.assertTrue(self.controller.poll(first))
        self.controller.wait(2)
        self.assertLessEqual(self.controller.state["dispatched_calls"], 3)
        self.assertEqual(len(self.stops), 1)
        journal = (Path(self.temp.name) / "watchdog.journal.ndjson").read_text()
        self.assertIn('"eligible":true', journal)
        self.assertIn('"stop_requested":true', journal)

    def test_observe_mode_records_eligible_without_submitting_stop(self):
        backend = FakeObserverBackend([
            decision("continue", "confirmation_missing"),
            decision("inspect", "check", ["e1"]),
            decision("stop", "repeated_no_progress", ["e1"]),
        ])
        self.controller = self.make(backend, mode="observe", max_calls=3)
        self.assertFalse(self.controller.poll(self.current[0]))
        self.current[0] = dict(self.current[0], observation_sequence=2)
        self.assertTrue(self.controller.poll(self.current[0]))
        self.controller.wait(2)
        self.clock_value[0] = 300
        self.current[0] = dict(self.current[0], observation_sequence=3)
        self.assertTrue(self.controller.poll(self.current[0]))
        self.controller.wait(2)
        self.assertEqual(self.stops, [])
        outcomes = json.loads("[" + ",".join(
            line for line in (Path(self.temp.name) / "watchdog.journal.ndjson").read_text().splitlines()
            if '"type":"stop_evaluation"' in line) + "]")
        self.assertEqual(outcomes[0]["eligible"], True)
        self.assertEqual(outcomes[0]["stop_requested"], False)

    def test_unknown_foreign_and_uninspected_evidence_reject_stop(self):
        def run_case(inspect_id, stop_id, reader, evidence_ids):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                clock = [0.0]
                current = [dict(self.current[0], observation_sequence=1,
                                evidence_ids=evidence_ids)]
                stops = []
                controller = ObserverController(
                    "run-uuid", root / "watchdog.json",
                    backend=FakeObserverBackend([
                        decision("continue", "confirmation_missing"),
                        decision("inspect", "check", [inspect_id]),
                        decision("stop", "repeated_no_progress", [stop_id]),
                    ]), catalog_game_id="catalog-game", mode="enforce",
                    progress=lambda _run: current[0], evidence_reader=reader,
                    stop=lambda *args: stops.append(args), clock=lambda: clock[0], max_calls=3)
                controller.poll(current[0]); controller.wait(2)
                current[0] = dict(current[0], observation_sequence=2)
                controller.poll(current[0]); controller.wait(2)
                current[0] = dict(current[0], observation_sequence=3)
                controller.poll(current[0]); controller.wait(2)
                clock[0] = 300.0
                current[0] = dict(current[0], observation_sequence=4)
                controller.poll(current[0]); controller.wait(2)
                journal = (root / "watchdog.journal.ndjson").read_text()
                controller.close(wait=True)
                return journal, stops

        unknown_journal, unknown_stops = run_case(
            "unknown", "e1",
            lambda *_args: {"run_id": "run-uuid", "evidence_id": "unknown", "data": "x"}, ["e1"])
        self.assertIn('"failed_prerequisite":"evidence"', unknown_journal)
        self.assertEqual(unknown_stops, [])
        foreign_journal, foreign_stops = run_case(
            "e1", "e1",
            lambda *_args: {"run_id": "foreign-run", "evidence_id": "e1", "data": "x"}, ["e1"])
        self.assertIn('"failed_prerequisite":"evidence"', foreign_journal)
        self.assertEqual(foreign_stops, [])
        uninspected_journal, uninspected_stops = run_case(
            "e1", "e2",
            lambda *_args: {"run_id": "run-uuid", "evidence_id": "e1", "data": "x"}, ["e1", "e2"])
        self.assertIn('"failed_prerequisite":"evidence"', uninspected_journal)
        self.assertEqual(uninspected_stops, [])

    def test_missing_current_progress_or_sequence_rejects_stop_as_stale(self):
        backend = FakeObserverBackend([
            decision("continue", "confirmation_missing"),
            decision("inspect", "check", ["e1"]),
            decision("stop", "repeated_no_progress", ["e1"]),
        ])
        self.controller = self.make(backend, max_calls=3, progress=lambda _run: None)
        self.assertFalse(self.controller.poll(self.current[0]))
        self.current[0] = dict(self.current[0], observation_sequence=2)
        self.assertTrue(self.controller.poll(self.current[0]))
        self.controller.wait(2)
        self.clock_value[0] = 600
        self.current[0] = dict(self.current[0], observation_sequence=3)
        self.assertTrue(self.controller.poll(self.current[0]))
        self.controller.wait(2)
        journal = (Path(self.temp.name) / "watchdog.journal.ndjson").read_text()
        self.assertIn('"failed_prerequisite":"freshness"', journal)
        self.assertEqual(self.stops, [])

        self.controller.close(wait=True)
        self.temp.cleanup()
        self.temp = tempfile.TemporaryDirectory()
        backend = FakeObserverBackend([
            decision("continue", "confirmation_missing"),
            decision("inspect", "check", ["e1"]),
            decision("stop", "repeated_no_progress", ["e1"]),
        ])
        missing_sequence = dict(self.current[0])
        missing_sequence.pop("observation_sequence")
        self.controller = self.make(backend, max_calls=3,
                                    progress=lambda _run: missing_sequence)
        first = dict(self.current[0], observation_sequence=1)
        self.assertFalse(self.controller.poll(first))
        self.assertTrue(self.controller.poll(dict(first, observation_sequence=2)))
        self.controller.wait(2)
        self.clock_value[0] = 900
        self.current[0] = dict(first, observation_sequence=3)
        self.assertTrue(self.controller.poll(self.current[0]))
        self.controller.wait(2)
        journal = (Path(self.temp.name) / "watchdog.journal.ndjson").read_text()
        self.assertIn('"failed_prerequisite":"freshness"', journal)
        self.assertEqual(self.stops, [])



if __name__ == "__main__":
    unittest.main()
