"""Focused Stack 4 proofs for coordinated tactical candidate recipes."""
from __future__ import annotations

import unittest
import copy
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from . import strategy_decision as sd
from .llm_client import validated_selections_for_packet


ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get(
    "NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver",
)).resolve()
FIXTURE = ROOT / "tools/fixtures/recruiter_survival/fixture_1_seed_4477_defensive"


def _materialize_fixture(destination: Path) -> Path:
    data = json.loads((FIXTURE / "checkpoint.json").read_text())
    board = ROOT / "scenarios/big_battle_6/board.toml"
    if not board.is_file():
        raise AssertionError("maintained big_battle_6 board is missing")
    data["board_path"] = str(board)
    data["save_state"]["board_path"] = str(board)
    encoded = json.dumps(data, separators=(",", ":")).encode()
    path = destination.with_name(f"0-231-{hashlib.sha256(encoded).hexdigest()}.json")
    path.write_bytes(encoded)
    return path


def _start_driver(checkpoint: Path, checkpoint_dir: Path):
    return subprocess.Popen(
        [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
         "--faction1", "undead", "--gold", "300", "--seed", "4477",
         "--llm-side", "0", "--max-turns", "14", "--incremental-turns",
         "--checkpoint-dir", str(checkpoint_dir),
         "--resume-checkpoint", str(checkpoint)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )


def _stop_driver(proc):
    if proc.stdin:
        proc.stdin.close()
    if proc.stdout:
        proc.stdout.close()
    if proc.stderr:
        proc.stderr.close()
    proc.kill()
    proc.wait()


def _read_state(proc):
    while True:
        line = proc.stdout.readline()
        if not line:
            raise AssertionError("driver closed before state")
        record = json.loads(line)
        if record.get("type") == "state":
            return record


def _query(proc, payload):
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if not line:
            raise AssertionError("driver closed before query reply")
        record = json.loads(line)
        if record.get("type") == "status":
            return record


def _submit(proc, orders):
    proc.stdin.write(json.dumps(orders) + "\n")
    proc.stdin.flush()
    status = None
    while True:
        line = proc.stdout.readline()
        if not line:
            raise AssertionError("driver closed before submitted batch completed")
        record = json.loads(line)
        if record.get("type") == "status":
            status = record
        elif record.get("type") == "state":
            return status, record


def _write_choice_backend(path: Path, recipe_index: int) -> None:
    path.write_text(textwrap.dedent(f"""
        import hashlib, json, pathlib, re, sys
        prompt = sys.stdin.read()
        marker = pathlib.Path(__file__).with_name("choice-used")
        evidence_path = pathlib.Path(__file__).with_name("prompt-evidence.ndjson")
        fixed_end = "\\nSTRATEGY_FIXED_PREFIX_END"
        fixed_prefix, volatile = prompt.split(fixed_end, 1)
        card_marker = "To choose this selection:"
        with evidence_path.open("a", encoding="utf-8") as evidence_stream:
            evidence_stream.write(json.dumps({{
                "fixed_prefix_bytes": len(fixed_prefix.encode("utf-8")),
                "fixed_prefix_sha256": hashlib.sha256(fixed_prefix.encode("utf-8")).hexdigest(),
                "cards_before_end": card_marker in fixed_prefix,
                "cards_after_end": card_marker in volatile,
            }}) + "\\n")
        assert prompt.startswith("STRATEGY_FIXED_PREFIX_BEGIN")
        if '"contact_actionability":"actionable"' not in prompt:
            response = {{"kind": "set_policy", "policy": {{
                "reserve_gold": 0, "recruits": [
                    {{"def_id": "Skeleton", "count": 6, "role": "army"}},
                    {{"def_id": "Skeleton Archer", "count": 4, "role": "army"}},
                    {{"def_id": "Ghoul", "count": 2, "role": "army"}}
                ], "scouts": [11, 12],
                "villages": [{{"col": 2, "row": 4}}, {{"col": 5, "row": 3}}],
                "rally": {{"col": 3, "row": 6}}, "holds": []
            }}}}
        else:
            decision_ids = re.findall(r'"decision_id":"([^"]+)"', prompt)
            if marker.exists():
                response = {{"kind": "finish_turn"}}
            else:
                cards = [json.loads(blob) for blob in re.findall(
                    r'To choose this selection: (\\{{.*?\\}})', prompt)]
                response = cards[{recipe_index}]
                marker.write_text(decision_ids[-1], encoding="utf-8")
        print(json.dumps({{"text": json.dumps(response, separators=(',', ':'))}}))
    """).lstrip(), encoding="utf-8")


def _launch_client(checkpoint: Path, backend: Path, log: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([
        sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
        "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
        "--gold", "300", "--seed", "4477", "--llm-side", "0", "--max-turns", "14",
        "--decision-mode", "strategy", "--log", str(log),
        "--model-command", shlex.join([sys.executable, str(backend)]),
        "--query-budget-seconds", "60", "--model-timeout", "10", "--turn-timeout", "90",
        "--max-model-calls-per-turn", "4", "--resume-checkpoint", str(checkpoint),
    ], cwd=ROOT, capture_output=True, text=True, timeout=180)


def _log_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _options_from_fixture(proc):
    state = _read_state(proc)
    revision = state["state_revision"]
    policy = json.loads((FIXTURE / "metadata.json").read_text())["policy"]
    progress = json.loads((FIXTURE / "metadata.json").read_text())["progress"]
    reply = _query(proc, {
        "action": "Query", "what": "routine_next", "state_revision": revision,
        "policy": policy, "progress": progress,
    })
    body = reply["body"]
    evidence = body["evidence"]
    return revision, reply["body"].get("reason"), evidence


def option(option_id, actor_id, category, *, expected=None, direct=None,
           movement_cost=1, target_id=None):
    row = {
        "option_id": option_id,
        "actor_id": actor_id,
        "category": category,
        "movement_cost": movement_cost,
        "actions": [{"action": "Move", "unit_id": actor_id, "col": 2, "row": 4}]
        if category == "relocation"
        else [{"action": "Attack", "attacker_id": actor_id, "defender_id": target_id}],
    }
    if category == "relocation":
        row["exposure"] = {}
        if direct is not None:
            row["exposure"]["distinct_attacker_count"] = direct
    else:
        row["forecast"] = {"expected_damage_dealt_tenths": expected} if expected is not None else {}
    return row


def packet(options, *, recruiter_id=1, final_only=False):
    return sd.build_decision_packet(
        "contact",
        {
            "stage": "current_state",
            "contact_actionability": "actionable",
            "threatened_recruiter": {"recruiter_id": recruiter_id},
            "options": options,
        },
        revision=231,
        final_only=final_only,
    )


class CoordinatedTacticalCandidateTests(unittest.TestCase):
    def test_relocation_and_pressure_are_distinct_and_damage_ordered(self):
        options = [
            option("u1-relocate-2", 1, "relocation", direct=0, movement_cost=3),
            option("u1-relocate-1", 1, "relocation", direct=0, movement_cost=1),
            option("u1-relocate-3", 1, "relocation", direct=1, movement_cost=1),
            option("u1-attack-1", 1, "attack", expected=200, target_id=20),
            option("u3-attack-1", 3, "attack", expected=120, target_id=28),
            option("u3-attack-2", 3, "attack", expected=100, target_id=20),
            option("u6-attack-1", 6, "attack", expected=130, target_id=28),
        ]
        candidates = sd.candidate_selections(packet(options))
        self.assertEqual(candidates[0], ["u1-relocate-1", "u6-attack-1", "u3-attack-2"])
        self.assertEqual(candidates[1], ["u1-attack-1", "u6-attack-1", "u3-attack-1"])
        self.assertEqual(len(candidates), 4)
        self.assertTrue(all(1 <= len(candidate) <= 3 for candidate in candidates))
        self.assertEqual(len(candidates), len({tuple(candidate) for candidate in candidates}))

    def test_shared_target_is_preserved_for_engine_validation(self):
        options = [
            option("u1-relocate-1", 1, "relocation", direct=0),
            option("u3-attack-1", 3, "attack", expected=120, target_id=28),
            option("u6-attack-1", 6, "attack", expected=110, target_id=28),
        ]
        candidates = sd.candidate_selections(packet(options))
        self.assertEqual(candidates[0], ["u1-relocate-1", "u3-attack-1", "u6-attack-1"])
        self.assertEqual(candidates[1], ["u3-attack-1", "u6-attack-1"])

    def test_missing_metrics_are_unknown_and_use_legacy_candidates(self):
        options = [
            option("u1-relocate-1", 1, "relocation"),
            option("u3-attack-1", 3, "attack", target_id=28),
        ]
        tactical = packet(options)
        legacy = sd._legacy_candidate_selections(tactical)
        self.assertEqual(sd.coordinated_tactical_candidate_selections(tactical), legacy)

    def test_relocation_singleton_preserved_when_no_support_attacks(self):
        options = [
            option("u1-relocate-1", 1, "relocation", direct=0, movement_cost=1),
            option("u1-relocate-2", 1, "relocation", direct=1, movement_cost=2),
        ]
        candidates = sd.candidate_selections(packet(options))
        self.assertEqual(candidates[0], ["u1-relocate-1"])

    def test_relocation_singleton_preserved_when_only_recruiter_can_attack(self):
        options = [
            option("u1-relocate-1", 1, "relocation", direct=0, movement_cost=1),
            option("u1-attack-1", 1, "attack", expected=150, target_id=20),
        ]
        candidates = sd.candidate_selections(packet(options))
        # Recipe 1 has relocation singleton; Recipe 2 has pressure attack
        self.assertEqual(candidates[0], ["u1-relocate-1"])
        self.assertEqual(candidates[1], ["u1-attack-1"])

    def test_invalid_assignment_threatened_recruiter_uses_coordinated_candidates(self):
        options = [
            option("u1-relocate-1", 1, "relocation", direct=0, movement_cost=1),
            option("u3-attack-1", 3, "attack", expected=120, target_id=28),
        ]
        pkt = sd.build_decision_packet(
            "invalid_assignment",
            {
                "cause": "dead_or_foreign_unit",
                "unit_id": 40,
                "threatened_recruiter": {"recruiter_id": 1},
                "options": options,
            },
            revision=231,
        )
        candidates = sd.candidate_selections(pkt)
        self.assertEqual(candidates[0], ["u1-relocate-1", "u3-attack-1"])
        self.assertEqual(candidates[1], ["u3-attack-1"])

    def test_quiet_control_and_empty_or_exhausted_contacts_do_not_invent_recipes(self):
        quiet = sd.build_decision_packet(
            "contact",
            {"stage": "current_state", "options": [option("u3-attack-1", 3, "attack", expected=100, target_id=28)]},
            revision=231,
        )
        self.assertEqual(sd.candidate_selections(quiet), sd._legacy_candidate_selections(quiet))
        empty = packet([])
        self.assertEqual(sd.candidate_selections(empty), [])

        exhausted = sd.build_decision_packet(
            "contact",
            {"stage": "current_state", "options": [],
             "options_empty_reason": "exhausted_contact_no_automatic_rescue_menu"},
            revision=231,
            final_only=True,
        )
        self.assertEqual(exhausted.allowed_kinds, ["act", "finish_turn", "resign"])
        self.assertEqual(sd.candidate_selections(exhausted), [])

    def test_final_only_keeps_finish_flag_and_validation_budget(self):
        packet_value = packet([
            option("u1-relocate-1", 1, "relocation", direct=0),
            option("u3-attack-1", 3, "attack", expected=100, target_id=28),
        ], final_only=True)
        calls = []

        def exchange(request):
            calls.append(request)
            return {"ok": True, "body": {"valid": True}}

        validated, coverage, queries = validated_selections_for_packet(
            packet_value, exchange, 231, no_recruit_macro=False)
        self.assertEqual(coverage, "validated")
        self.assertEqual(queries, len(validated))
        self.assertLessEqual(queries, 4)
        self.assertLessEqual(len(validated), 4)
        self.assertTrue(all(item["finish_turn"] for item in validated))
        self.assertTrue(all(len(item["option_ids"]) <= 3 for item in validated))
        self.assertTrue(all(request["orders"][-1]["action"] == "FinishWithGreedy" for request in calls))

    def test_fixture_one_current_packet_freezes_two_real_committing_alternatives(self):
        self.assertTrue(DRIVER.is_file(), "build source-matched greedy_driver before focused tests")
        reference = json.loads((FIXTURE / "stack4_reference.json").read_text())
        with tempfile.TemporaryDirectory() as td:
            checkpoint = _materialize_fixture(Path(td) / "checkpoint.json")
            checkpoint_dir = Path(td) / "checkpoints"
            checkpoint_dir.mkdir()
            proc = _start_driver(checkpoint, checkpoint_dir)
            try:
                revision, reason, evidence = _options_from_fixture(proc)
                self.assertEqual(revision, reference["state_revision"])
                self.assertEqual(reason, reference["reason"])
                self.assertEqual(evidence["stage"], reference["stage"])
                self.assertEqual(evidence["actor_ids"], reference["actor_ids"])
                self.assertEqual(
                    [option["option_id"] for option in evidence["options"]],
                    reference["option_ids"],
                )
                packet_evidence = copy.deepcopy(evidence)
                packet_evidence["threatened_recruiter"] = {
                    "recruiter_id": reference["threatened_recruiter_id"]
                }
                packet_value = sd.build_decision_packet(
                    "contact", packet_evidence, revision=revision,
                )
                candidates = sd.candidate_selections(packet_value)
                self.assertEqual(
                    candidates[:2],
                    [reference["alternatives"]["relocation_pressure"]["option_ids"],
                     reference["alternatives"]["pressure"]["option_ids"]],
                )
                by_id = {option["option_id"]: option for option in evidence["options"]}
                for candidate in candidates[:2]:
                    orders = [action for option_id in candidate for action in by_id[option_id]["actions"]]
                    validation = _query(proc, {
                        "action": "Query", "what": "validate_batch",
                        "state_revision": revision, "orders": orders,
                    })
                    self.assertTrue(validation["body"]["valid"], validation)
                    status, after = _submit(proc, orders)
                    self.assertIsNotNone(status)
                    self.assertTrue(status.get("ok"), status)
                    self.assertTrue(status.get("committed"), status)
                    self.assertEqual(len(status.get("results", [])), len(orders), status)
                    unit = next(unit for unit in after["units"] if unit["id"] == 1)
                    expected_destination = by_id[candidate[0]]["actions"][0]
                    self.assertEqual((unit["col"], unit["row"]),
                                     (expected_destination["col"], expected_destination["row"]))
                    # Restore an isolated copy before committing the second
                    # alternative; both records therefore share revision 231.
                    _stop_driver(proc)
                    checkpoint = _materialize_fixture(Path(td) / "checkpoint.json")
                    proc = _start_driver(checkpoint, checkpoint_dir)
                    _read_state(proc)
                    _query(proc, {
                        "action": "Query", "what": "routine_next",
                        "state_revision": revision,
                        "policy": json.loads((FIXTURE / "metadata.json").read_text())["policy"],
                        "progress": json.loads((FIXTURE / "metadata.json").read_text())["progress"],
                    })
            finally:
                _stop_driver(proc)

    def test_llm_client_delivers_grounded_cards_and_commits_each_recipe(self):
        """Exercise enrichment and card execution through the normal client."""
        self.assertTrue(DRIVER.is_file(), "build source-matched greedy_driver before focused tests")
        reference = json.loads((FIXTURE / "stack4_reference.json").read_text())
        for recipe_index, name in enumerate(("relocation_pressure", "pressure")):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                checkpoint = _materialize_fixture(root / "checkpoint.json")
                backend = root / "backend.py"
                selected = reference["alternatives"][name]["option_ids"]
                _write_choice_backend(backend, recipe_index)
                log = root / "client.ndjson"
                result = _launch_client(checkpoint, backend, log)
                self.assertEqual(result.returncode, 0, result.stderr +
                                 (log.read_text() if log.exists() else ""))
                prompt_evidence = [json.loads(line) for line in
                                   (root / "prompt-evidence.ndjson").read_text().splitlines()]
                self.assertTrue(prompt_evidence)
                self.assertEqual(
                    {(row["fixed_prefix_bytes"], row["fixed_prefix_sha256"])
                     for row in prompt_evidence},
                    {(prompt_evidence[0]["fixed_prefix_bytes"],
                      prompt_evidence[0]["fixed_prefix_sha256"])},
                )
                card_rows = [row for row in prompt_evidence if row["cards_before_end"]
                             or row["cards_after_end"]]
                self.assertTrue(card_rows)
                self.assertTrue(all(row["cards_after_end"] and not row["cards_before_end"]
                                    for row in card_rows))
                rows = _log_records(log)
                packets = [row["packet"] for row in rows
                           if row.get("type") == "decision_packet"
                           and row.get("packet", {}).get("evidence", {}).get("stage") == "current_state"]
                self.assertTrue(packets)
                packet = packets[0]
                self.assertEqual(packet["reason"], "contact")
                self.assertEqual(packet["evidence"].get("threatened_recruiter"),
                                 {"recruiter_id": reference["threatened_recruiter_id"]})
                self.assertEqual(
                    [entry["option_ids"] for entry in packet["validated_selections"][:2]],
                    [reference["alternatives"]["relocation_pressure"]["option_ids"],
                     reference["alternatives"]["pressure"]["option_ids"]],
                )
                by_id = {option["option_id"]: option for option in packet["options"]}
                expected_orders = [action for option_id in selected
                                   for action in by_id[option_id]["actions"]]
                batches = [row for row in rows if row.get("type") == "forwarded_orders"
                           and row.get("source") == "llm"
                           and any(order.get("action") in {"Move", "Attack"}
                                   for order in row.get("orders", []))]
                self.assertEqual(len(batches), 1)
                self.assertEqual(batches[0]["orders"], expected_orders)
                self.assertTrue(any(
                    row["orders"][-1].get("action") == "FinishWithGreedy"
                    for row in rows if row.get("type") == "forwarded_orders"
                    and row.get("source") == "llm" and row.get("orders")))
                action_events = [event for row in rows
                                 if row.get("type") == "driver"
                                 and row.get("line", {}).get("type") == "events"
                                 for event in row["line"].get("events", [])
                                 if event.get("source") == "llm"
                                 and event.get("kind") in {"move", "attack"}]
                expected_event_tuples = [
                    ("move", action.get("unit_id"), action.get("col"), action.get("row"))
                    if action.get("action") == "Move"
                    else ("attack", action.get("attacker_id"), action.get("defender_id"))
                    for action in expected_orders
                ]
                actual_event_tuples = []
                for event in action_events:
                    if event.get("kind") == "move":
                        actual_event_tuples.append(("move", event.get("unit"),
                                                    event.get("to", {}).get("col"),
                                                    event.get("to", {}).get("row")))
                    else:
                        actual_event_tuples.append(("attack",
                                                    event.get("attacker", {}).get("unit"),
                                                    event.get("defender", {}).get("unit")))
                self.assertEqual(actual_event_tuples, expected_event_tuples)

    def test_offline_comparison_reports_four_bounded_cases_and_provenance(self):
        from . import tactical_comparison as comparison

        report = comparison.run_comparison()
        self.assertEqual(report["source_checkpoint_sha256"],
                         json.loads((FIXTURE / "stack4_reference.json").read_text())[
                             "source_checkpoint_sha256"])
        self.assertTrue(report["driver_sha256"])
        self.assertEqual([case["case"] for case in report["cases"]], [
            "relocation_pressure", "pressure", "no_sweep", "always_first",
        ])
        self.assertTrue(all(case["validity"] and case["committed"]
                            and case["submit_status"]["committed"]
                            and case["horizon"]["greedy_event_count"] > 0
                            for case in report["cases"]))
        self.assertTrue(all(case["evidence_coverage"]["final_state_after_opponent"]
                            for case in report["cases"]))
        complete = {case["case"]: case for case in report["cases"]
                    if case["evidence_coverage"]["final_state_after_opponent"]}
        self.assertIn("relocation_pressure", complete)
        self.assertIn("no_sweep", complete)
        self.assertIn("always_first", complete)
        self.assertEqual(complete["relocation_pressure"]["recruiter"]["hp"], 48)
        self.assertEqual(complete["always_first"]["recruiter"]["hp"], 38)
        pressure = next(case for case in report["cases"] if case["case"] == "pressure")
        if pressure["evidence_coverage"]["terminal"]:
            self.assertEqual(pressure["evidence_coverage"]["terminal"]["reason"], "winner")

    def test_offline_comparison_rejects_known_shared_target_batch(self):
        from . import tactical_comparison as comparison

        reference = json.loads((FIXTURE / "stack4_reference.json").read_text())
        with self.assertRaisesRegex(RuntimeError, "invalid"):
            comparison._case_result(
                "known-invalid-shared-target",
                ["u1-relocate-1", "u3-attack-1", "u6-attack-1"],
                reference,
            )


if __name__ == "__main__":
    unittest.main()
