"""Stack 4 acceptance tests for selector treatment and provenance evaluation."""
from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from . import algorithm_strength as strength
from . import coordinated_selector_evaluation as evaluation


def _profile(treatment="coordinated-fireworks-glm"):
    model = ("accounts/fireworks/models/glm-5p3-flash" if treatment.endswith("glm")
             else "accounts/fireworks/models/deepseek-v4p1-flash")
    effort = "low"
    args = ["-m", "tools.plan_selector", "--model", model,
            "--reasoning-effort", effort, "--max-output-tokens", "2048",
            "--timeout", "60"]
    return {
        "command": {"program": "python3", "args": args},
        "model": model, "reasoning_effort": effort,
        "profile_id": f"{treatment}-profile-1", "prompt_profile": "coordinated_selector_v1",
        "limits": {"max_prompt_bytes": 12288, "max_output_tokens": 2048,
                   "deadline_seconds": 60, "max_requests": 32},
        "pricing": {"date": "2026-09-20", "reasoning_included_in_output": True,
                    "rates": {"input_per_million": 0.15,
                              "cached_input_per_million": 0.03,
                              "output_per_million": 0.5}},
    }


def _engine(cell):
    return {"raw_seed": cell["seed"], "effective_seed": strength._mix_seed(cell["seed"]),
            "scenario": cell["scenario"], "factions": [cell["faction"]] * 2,
            "algorithms": strength._expected_algorithms(cell),
            "recruitment_policies": [cell["recruit1_policy"], cell["recruit2_policy"]],
            "first_side": 0, "second_gold": 0, "side_turn_cap": cell["max_side_turns"],
            "starting_gold": [cell["gold"]] * 2, "completed_side_turns": 1,
            "winner_side": cell["controlled_side"], "termination_reason": "winner"}


def _trace(cell, *, treatment="coordinated-fireworks-glm", state="accepted", game_id="g1",
           decision_id="d1", request_id="r1"):
    telemetry = {"selector_invoked": True,
                 "candidates": [{"candidate_id": "greedy"}, {"candidate_id": "objective"}],
                 "baseline_candidate_id": "greedy", "selected_candidate_id": "objective",
                 "fallback_reason": None, "response_status": "accepted"}
    if state == "fallback":
        telemetry.update({"selected_candidate_id": "greedy", "fallback_reason": "timeout",
                          "response_status": "error"})
    row = {"type": "coordinated_decision", "side": cell["controlled_side"],
           "decision_id": decision_id, "game_id": game_id,
           "backend": "command" if treatment.startswith("coordinated-fireworks") else "test-fake",
           "response_status": telemetry["response_status"],
           "response": {"candidate_id": telemetry["selected_candidate_id"]},
           "request": {"schema_version": 1, "candidates": [
               {"candidate_id": "greedy", "plan_kind": "greedy", "score": 2.0},
               {"candidate_id": "objective", "plan_kind": "objective", "score": 1.0},
           ]},
           "telemetry": telemetry}
    row["request_id"] = request_id
    if treatment == "coordinated-fake-selector":
        row["usage"] = {"input_tokens": None, "cached_input_tokens": None,
                        "output_tokens": None, "reasoning_tokens": None,
                        "cost_microusd": None}
    return [{"type": "metadata", "input_seed": cell["seed"], "game_id": game_id}, row,
            {"type": "terminal", "side_turns_executed": 1}]


def _usage(*, game_id="g1", request_id="r1", call_id="call-1", status="completed",
           input_tokens=1000, cached_input_tokens=400, output_tokens=100):
    return [
        {"record_kind": "dispatch", "game_id": game_id, "request_id": request_id,
         "call_id": call_id, "status": "dispatched"},
        {"record_kind": "final", "game_id": game_id, "request_id": request_id,
         "call_id": call_id, "status": status,
         "requested_model": "accounts/fireworks/models/glm-5p3-flash",
         "requested_reasoning_effort": "low", "output_limit": 2048,
         "prompt_layout_version": "coordinated_selector_v1",
         "input_tokens": input_tokens, "cached_input_tokens": cached_input_tokens,
         "output_tokens": output_tokens},
    ]


def _write_evidence(root: Path, *, call_id="call-1", request_id="r1"):
    safe = "".join(char if char.isalnum() or char in "_.-" else "_" for char in call_id)
    call = root / safe
    call.mkdir(parents=True, exist_ok=True)
    prompt = b"canonical selector prompt"
    (call / "prompt.txt").write_bytes(prompt)
    (call / "prompt.sha256").write_text(hashlib.sha256(prompt).hexdigest())
    (call / "request_context.json").write_text(json.dumps({"harness_request_id": request_id}))
    (call / "payload.json").write_text(json.dumps({
        "model": "accounts/fireworks/models/glm-5p3-flash",
        "max_tokens": 2048, "reasoning_effort": "low"}))
    return root


class CoordinatedSelectorEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.cell = evaluation.build_schedule()[0]
        self.engine = _engine(self.cell)
        self.tempdir = TemporaryDirectory()
        self.evidence_dir = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_schedule_and_four_treatments_are_explicit(self):
        schedule = evaluation.build_schedule()
        self.assertEqual(len(schedule), 32)
        self.assertEqual(evaluation.TREATMENTS, (
            "coordinated-baseline", "coordinated-fake-selector",
            "coordinated-fireworks-glm", "coordinated-fireworks-deepseek"))
        self.assertTrue(all(c["controlled_algorithm"] == "coordinated" for c in schedule))

    def test_pilot_schedule_is_bounded_to_the_explicit_paired_seeds(self):
        pilot = evaluation.build_pilot_schedule([2038, 4477, 7731])
        self.assertEqual([cell["seed"] for cell in pilot], [2038, 4477, 7731])
        self.assertEqual(len(pilot), 3)
        self.assertEqual([cell["controlled_side"] for cell in pilot], [0, 1, 0])
        self.assertEqual([cell["first"] for cell in pilot], ["team1", "team1", "team2"])
        self.assertTrue(all(cell["opponent"] == "greedy" and cell["faction"] == "undead"
                            for cell in pilot))
        self.assertEqual(len(pilot) * 3, 9)  # baseline + the two requested model treatments

    def test_pilot_runs_all_local_baselines_before_paid_models(self):
        treatments = ("coordinated-baseline", "coordinated-fireworks-glm",
                      "coordinated-fireworks-deepseek")
        profiles = {t: _profile(t) for t in treatments if t != "coordinated-baseline"}
        with TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "self-play"
            binary.write_bytes(b"frozen test binary")
            calls = []

            def fake_game(cell, treatment, *args, **kwargs):
                calls.append((cell["seed"], treatment))
                return {"status": "unrun", "outcome": None}

            with patch.object(evaluation, "_run_one", side_effect=fake_game), \
                    patch.object(evaluation, "build_report", return_value={"status": "complete"}):
                evaluation.run_screen(root / "pilot", binary, treatments=treatments,
                                      selector_profiles=profiles, pilot_seeds=[2038, 4477, 7731])
            self.assertEqual([t for _, t in calls],
                             ["coordinated-baseline"] * 3
                             + ["coordinated-fireworks-glm"] * 3
                             + ["coordinated-fireworks-deepseek"] * 3)
            self.assertEqual(calls[:3], [(seed, "coordinated-baseline")
                                         for seed in (2038, 4477, 7731)])

    def test_commands_use_coordinated_ai_selector_side_and_fireworks_bridge(self):
        binary, record_dir = Path("self-play"), Path("cell1/trace")
        baseline = evaluation.command_for(self.cell, "coordinated-baseline", binary, record_dir)
        fake = evaluation.command_for(self.cell, "coordinated-fake-selector", binary, record_dir)
        profile = _profile()
        remote = evaluation.command_for(self.cell, "coordinated-fireworks-glm", binary,
                                        record_dir, profile=profile)
        self.assertEqual(baseline[baseline.index("--ai1") + 1], "coordinated")
        self.assertEqual(fake[fake.index("--ai1") + 1], "coordinated")
        self.assertEqual(fake[-2:], ["--selector-side", "1"])
        self.assertEqual(remote[remote.index("--ai1") + 1], "coordinated")
        self.assertEqual(remote[-2:], ["--selector-side", "1"])
        self.assertEqual(remote[remote.index("--selector-command") + 1], "python3")
        self.assertEqual(remote.count("--selector-arg"), len(profile["command"]["args"]))
        usage_path = remote[remote.index("--selector-usage-sidecar") + 1]
        evidence_path = remote[remote.index("--selector-evidence-dir") + 1]
        self.assertIn("cell1", usage_path)
        self.assertIn("selector-usage.ndjson", usage_path)
        self.assertIn("selector-evidence", evidence_path)
        other = evaluation.command_for(dict(self.cell, pair_id="another-cell"),
                                       "coordinated-fireworks-glm", binary,
                                       Path("other-cell/trace"), profile=profile)
        self.assertNotEqual(usage_path, other[other.index("--selector-usage-sidecar") + 1])
        self.assertNotIn("--llm-side", remote)
        second_side = dict(self.cell, controlled_side=1)
        command = evaluation.command_for(second_side, "coordinated-fireworks-glm", binary,
                                         record_dir, profile=profile)
        self.assertEqual(command[command.index("--ai2") + 1], "coordinated")
        self.assertEqual(command[-2:], ["--selector-side", "2"])

    def test_remote_profile_is_frozen_and_requires_all_identity_and_limits(self):
        for missing in ("command", "model", "reasoning_effort", "profile_id", "prompt_profile", "limits", "pricing"):
            profile = _profile()
            del profile[missing]
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, "missing"):
                evaluation._validate_profile("coordinated-fireworks-glm", profile)
        with self.assertRaisesRegex(ValueError, "requires model identity"):
            evaluation._validate_profile("coordinated-fireworks-glm", dict(_profile(), model="wrong"))
        with self.assertRaisesRegex(ValueError, "positive max_output_tokens"):
            profile = _profile(); profile["limits"]["max_output_tokens"] = 0
            evaluation._validate_profile("coordinated-fireworks-glm", profile)
        with self.assertRaisesRegex(ValueError, "dated pricing"):
            profile = _profile(); profile["pricing"]["reasoning_included_in_output"] = False
            evaluation._validate_profile("coordinated-fireworks-glm", profile)
        deepseek = _profile("coordinated-fireworks-deepseek")
        evaluation._validate_profile("coordinated-fireworks-deepseek", deepseek)
        self.assertIn("--reasoning-effort", deepseek["command"]["args"])
        self.assertIn("low", deepseek["command"]["args"])
        self.assertIn("tools.plan_selector", deepseek["command"]["args"])
        with self.assertRaisesRegex(ValueError, "frozen selector limits"):
            profile = _profile(); profile["limits"]["max_output_tokens"] = 4096
            evaluation._validate_profile("coordinated-fireworks-glm", profile)

    def test_remote_run_preflight_requires_explicit_profile_before_creating_artifacts(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            with self.assertRaisesRegex(ValueError, "requires a frozen selector profile"):
                evaluation.run_screen(out, Path("missing-self-play"),
                                      treatments=("coordinated-baseline", "coordinated-fireworks-glm"))
            self.assertFalse(out.exists())

    def test_direct_action_path_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "direct-action"):
            evaluation.command_for(self.cell, "coordinated-baseline", Path("greedy_driver"), Path("trace"))

    def test_real_choice_requires_exact_identity_usage_join_and_is_counted(self):
        profile = _profile()
        result = evaluation.validate_trace(self.cell, "coordinated-fireworks-glm", self.engine,
                                           _trace(self.cell), usage_rows=_usage(),
                                           selector_profile=profile, expected_game_id="g1",
                                           evidence_dir=_write_evidence(self.evidence_dir))
        self.assertEqual(result["decisions"][0]["decision_state"], "model_accepted")
        self.assertEqual(result["provider_call_count"], 1)
        self.assertIsInstance(result["decisions"][0]["cost_microusd"], int)

    def test_real_choice_fails_closed_without_identity_or_usage_receipt(self):
        profile = _profile()
        with self.assertRaisesRegex(ValueError, "request_id"):
            trace = _trace(self.cell); trace[1].pop("request_id")
            evaluation.validate_trace(self.cell, "coordinated-fireworks-glm", self.engine,
                                      trace, usage_rows=_usage(), selector_profile=profile,
                                      expected_game_id="g1")
        with self.assertRaisesRegex(ValueError, "exactly one dispatch and one final"):
            evaluation.validate_trace(self.cell, "coordinated-fireworks-glm", self.engine,
                                      _trace(self.cell), usage_rows=[], selector_profile=profile,
                                      expected_game_id="g1")
        with self.assertRaisesRegex(ValueError, "incomplete provider token usage"):
            rows = _usage(); rows[1]["cached_input_tokens"] = None
            evaluation.validate_trace(self.cell, "coordinated-fireworks-glm", self.engine,
                                      _trace(self.cell), usage_rows=rows, selector_profile=profile,
                                      expected_game_id="g1", evidence_dir=_write_evidence(self.evidence_dir))

    def test_real_choice_checks_game_model_effort_and_prompt_profile_identity(self):
        profile = _profile()
        wrong_game = _trace(self.cell); wrong_game[1]["game_id"] = "foreign"
        with self.assertRaisesRegex(ValueError, "game_id mismatch"):
            evaluation.validate_trace(self.cell, "coordinated-fireworks-glm", self.engine,
                                      wrong_game, usage_rows=_usage(), selector_profile=profile,
                                      expected_game_id="g1")
        wrong_profile = _usage(); wrong_profile[1]["prompt_layout_version"] = "changed"
        with self.assertRaisesRegex(ValueError, "prompt profile"):
            evaluation.validate_trace(self.cell, "coordinated-fireworks-glm", self.engine,
                                      _trace(self.cell), usage_rows=wrong_profile, selector_profile=profile,
                                      expected_game_id="g1", evidence_dir=_write_evidence(self.evidence_dir))
        wrong_receipt = _usage(); wrong_receipt[1]["requested_model"] = "other-model"
        with self.assertRaisesRegex(ValueError, "model differs"):
            evaluation.validate_trace(self.cell, "coordinated-fireworks-glm", self.engine,
                                      _trace(self.cell), usage_rows=wrong_receipt,
                                      selector_profile=profile, expected_game_id="g1",
                                      evidence_dir=_write_evidence(self.evidence_dir))

    def test_real_choice_requires_call_id_linked_prompt_payload_and_request_context(self):
        profile = _profile()
        with TemporaryDirectory() as empty:
            with self.assertRaisesRegex(ValueError, "missing prompt"):
                evaluation.validate_trace(self.cell, "coordinated-fireworks-glm", self.engine,
                                          _trace(self.cell), usage_rows=_usage(), selector_profile=profile,
                                          expected_game_id="g1", evidence_dir=Path(empty))
        evidence = _write_evidence(self.evidence_dir)
        call_context = evidence / "call-1" / "request_context.json"
        call_context.write_text(json.dumps({"harness_request_id": "wrong-request"}))
        with self.assertRaisesRegex(ValueError, "request identity mismatch"):
            evaluation.validate_trace(self.cell, "coordinated-fireworks-glm", self.engine,
                                      _trace(self.cell), usage_rows=_usage(), selector_profile=profile,
                                      expected_game_id="g1", evidence_dir=evidence)
        _write_evidence(self.evidence_dir)
        payload = self.evidence_dir / "call-1" / "payload.json"
        payload.write_text(json.dumps({"model": profile["model"], "max_tokens": 4096,
                                       "reasoning_effort": "low"}))
        with self.assertRaisesRegex(ValueError, "output limit differs"):
            evaluation.validate_trace(self.cell, "coordinated-fireworks-glm", self.engine,
                                      _trace(self.cell), usage_rows=_usage(), selector_profile=profile,
                                      expected_game_id="g1", evidence_dir=evidence)

    def test_reused_request_or_orphan_receipt_is_invalid(self):
        profile = _profile()
        trace = _trace(self.cell)
        trace.insert(2, dict(trace[1], decision_id="d2"))
        with self.assertRaisesRegex(ValueError, "reused selector request_id"):
            evaluation.validate_trace(self.cell, "coordinated-fireworks-glm", self.engine,
                                      trace, usage_rows=_usage(), selector_profile=profile,
                                      expected_game_id="g1", evidence_dir=_write_evidence(self.evidence_dir))
        with self.assertRaisesRegex(ValueError, "orphan provider usage"):
            rows = _usage() + _usage(request_id="orphan", call_id="call-2")
            evaluation.validate_trace(self.cell, "coordinated-fireworks-glm", self.engine,
                                      _trace(self.cell), usage_rows=rows, selector_profile=profile,
                                      expected_game_id="g1", evidence_dir=_write_evidence(self.evidence_dir))

    def test_fallback_is_distinct_and_must_use_baseline_choice(self):
        profile = _profile()
        trace = _trace(self.cell, state="fallback")
        trace[1]["telemetry"]["selected_candidate_id"] = "objective"
        with self.assertRaisesRegex(ValueError, "deterministic baseline"):
            evaluation.validate_trace(self.cell, "coordinated-fireworks-glm", self.engine,
                                      trace, usage_rows=_usage(status="failed", input_tokens=None,
                                                               cached_input_tokens=None, output_tokens=None),
                                      selector_profile=profile, expected_game_id="g1",
                                      evidence_dir=_write_evidence(self.evidence_dir))
        trace = _trace(self.cell, state="fallback")
        result = evaluation.validate_trace(self.cell, "coordinated-fireworks-glm", self.engine,
                                           trace, usage_rows=_usage(status="failed", input_tokens=None,
                                                                    cached_input_tokens=None, output_tokens=None),
                                           selector_profile=profile, expected_game_id="g1",
                                           evidence_dir=_write_evidence(self.evidence_dir))
        self.assertEqual(result["decisions"][0]["decision_state"], "fallback")
        self.assertEqual(result["provider_call_costs_microusd"], [None])

    def test_model_skips_require_a_reason_and_are_not_counted_as_calls(self):
        trace = _trace(self.cell)
        trace[1]["telemetry"]["selector_invoked"] = False
        trace[1]["telemetry"]["response_status"] = "skipped_clear_lead"
        profile = _profile()
        result = evaluation.validate_trace(self.cell, "coordinated-fireworks-glm", self.engine,
                                           trace, selector_profile=profile, expected_game_id="g1")
        self.assertEqual(result["decisions"][0]["decision_state"], "skipped")
        self.assertEqual(result["provider_call_count"], 0)
        trace[1]["telemetry"]["response_status"] = ""
        with self.assertRaisesRegex(ValueError, "explicit skip status"):
            evaluation.validate_trace(self.cell, "coordinated-fireworks-glm", self.engine,
                                       trace, selector_profile=profile, expected_game_id="g1")

    def test_fake_has_no_provider_receipt_and_only_fake_cost_is_zero(self):
        trace = _trace(self.cell, treatment="coordinated-fake-selector")
        result = evaluation.validate_trace(self.cell, "coordinated-fake-selector", self.engine, trace)
        self.assertEqual(result["decisions"][0]["decision_state"], "fake_accepted")
        self.assertEqual(result["provider_call_count"], 0)
        schedule = [self.cell]
        rows = [{"pair_id": self.cell["pair_id"], "treatment": "coordinated-baseline",
                 "status": "completed", "outcome": "win", "decisions": [], "decision_count": 0},
                {"pair_id": self.cell["pair_id"], "treatment": "coordinated-fake-selector",
                 "status": "completed", "outcome": "loss", "decisions": result["decisions"],
                 "decision_count": 1, "provider_call_count": 0}]
        report = evaluation.build_report(schedule, rows, treatments=evaluation.LOCAL_TREATMENTS)
        fake = report["summary"]["coordinated-fake-selector"]
        self.assertEqual(fake["cost_microusd_total"], 0)
        self.assertEqual(fake["cost_basis"], "fake_selector_zero_provider_cost")

    def test_remote_incomplete_usage_is_unknown_not_zero_and_unrun_stays_distinct(self):
        rows = [{"pair_id": self.cell["pair_id"], "treatment": "coordinated-baseline",
                 "status": "completed", "outcome": "win", "decisions": [], "decision_count": 0},
                {"pair_id": self.cell["pair_id"], "treatment": "coordinated-fireworks-glm",
                 "status": "completed", "outcome": "loss", "decisions": [], "decision_count": 0,
                 "provider_call_count": 1, "provider_call_costs_microusd": [None]}]
        report = evaluation.build_report([self.cell], rows,
                                         treatments=("coordinated-baseline", "coordinated-fireworks-glm"))
        summary = report["summary"]["coordinated-fireworks-glm"]
        self.assertEqual(summary["cost_microusd_total"], None)
        self.assertEqual(summary["usage_coverage"], "incomplete")
        self.assertEqual(report["summary"]["coordinated-fireworks-glm"]["unrun"], 0)
        unrun = evaluation.build_report([self.cell], rows[:1],
                                        treatments=("coordinated-baseline", "coordinated-fireworks-glm"))
        self.assertEqual(unrun["summary"]["coordinated-fireworks-glm"]["unrun"], 1)


if __name__ == "__main__":
    unittest.main()
