"""Real-driver acceptance tests for strategy consequences (Stack 1).

Drives the real engine (greedy_driver) through client routines and scripted backends,
asserting that validated selections are enriched with preview consequences, neutral
comparative prompts are formatted, and selections commit as expected.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

from .llm_client import (
    preview_validated_selections,
    validated_selections_for_packet,
    query_preview_batch,
    NO_SWEEP_FINISH,
)
from .strategy_consequences import (
    extract_candidate_consequences,
    format_consequences_comparison,
)
from .strategy_decision import DecisionPacket, render_validated_selections
from .test_strategy_stack3_integration import (
    DRIVER, ROOT, choose, launch, policy, prepare, records
)

CHECKPOINT_PATH = (ROOT / "tools/fixtures/choice_recovery" /
                   "checkpoint-469f81c066e604466ec655eaf797bbbc1921eb2bbcc5d88bf72dd9e2096a7c3f.json")


class MockExchange:
    """Exchange wrapper allowing query tracking and injected responses."""

    def __init__(self, real_exchange=None):
        self.real_exchange = real_exchange
        self.queries: list[dict] = []
        self.query_limit_on: set[str] = set()
        self.fail_on: set[str] = set()

    def __call__(self, request: dict) -> dict:
        self.queries.append(request)
        what = request.get("what")
        if what in self.fail_on:
            raise RuntimeError(f"transport error on {what}")
        if what in self.query_limit_on:
            return {"type": "status", "ok": False, "code": "query_limit",
                    "message": "query limit exceeded"}
        if self.real_exchange:
            return self.real_exchange(request)
        return {"type": "status", "ok": True, "state_revision": request.get("state_revision", 0),
                "body": {"phase": request.get("phase", "partial"), "mode": "forecast",
                         "candidates": [{"valid": True, "assumption": "none"}]}}


@unittest.skipUnless(DRIVER.is_file(), "Build greedy_driver before running integration tests")
class StrategyConsequencesIntegrationTests(unittest.TestCase):

    @staticmethod
    def _driver_events(rows: list[dict]) -> list[dict]:
        result = []
        for row in rows:
            line = row.get("line", row)
            if isinstance(line, dict) and line.get("type") == "events":
                result.extend(line.get("events", []))
        return result

    def _start_driver(self, checkpoint: Path) -> tuple[subprocess.Popen, int]:
        proc = subprocess.Popen(
            [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
             "--faction1", "undead", "--gold", "300", "--seed", "4477",
             "--llm-side", "0", "--max-turns", "120", "--incremental-turns",
             "--resume-checkpoint", str(checkpoint)],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        initial_state = None
        for _ in range(100):
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError("driver closed")
            obj = json.loads(line)
            if obj.get("type") == "state":
                initial_state = obj
                break
        if initial_state is None:
            proc.kill()
            raise RuntimeError("could not get state from driver")
        return proc, initial_state["state_revision"]

    def test_real_driver_preview_enriches_two_legal_selections(self):
        """When 2 legal selections exist, exactly one preview query is issued for 2 candidates."""
        if not CHECKPOINT_PATH.exists():
            self.skipTest("checkpoint fixture missing")

        proc, rev = self._start_driver(CHECKPOINT_PATH)
        try:
            def raw_exchange(req):
                proc.stdin.write(json.dumps(req) + "\n")
                proc.stdin.flush()
                return json.loads(proc.stdout.readline())

            exchange = MockExchange(raw_exchange)

            # Define 2 legal, independent move options
            options = [
                {"option_id": "u10-move-1", "actor_id": 10,
                 "actions": [{"action": "Move", "unit_id": 10, "col": 5, "row": 6}]},
                {"option_id": "u11-move-1", "actor_id": 11,
                 "actions": [{"action": "Move", "unit_id": 11, "col": 7, "row": 8}]},
            ]
            packet = DecisionPacket(
                decision_id="dec-test-1",
                state_revision=rev,
                decision_kind="tactical",
                incident_key="inc-test",
                reason="contact",
                evidence={"stage": "current_state"},
                allowed_kinds=["choose", "act", "finish_turn"],
                options=options,
                coverage={"options": "complete"},
                final_only=False,
            )

            # Validate selections
            selections, cov, v_queries = validated_selections_for_packet(
                packet, exchange, rev, no_recruit_macro=False)
            self.assertGreaterEqual(len(selections), 2)

            preview_exchange_count_before = len([q for q in exchange.queries if q.get("what") == "preview_batch"])

            # Enrich with consequences
            enriched, p_queries = preview_validated_selections(
                packet, selections, exchange, rev, no_recruit_macro=False)

            preview_queries = [q for q in exchange.queries if q.get("what") == "preview_batch"]
            self.assertEqual(len(preview_queries) - preview_exchange_count_before, 1)
            self.assertEqual(p_queries, 1)

            # Check that exactly first two selections are enriched
            self.assertIn("consequences", enriched[0])
            self.assertIn("consequences", enriched[1])
            # This quiet contact fixture has no recruiter/friendly threat
            # payload in the forecast envelope.  The absence remains partial
            # and renders as unknown rather than claiming no exposure.
            self.assertEqual(enriched[0]["consequences"]["coverage"], "partial")
            self.assertEqual(enriched[1]["consequences"]["coverage"], "partial")
            self.assertEqual(enriched[0]["consequences"]["field_coverage"]["recruiter_exposure"], "unknown")

            # Verify rendered comparison block
            test_packet = DecisionPacket(
                decision_id=packet.decision_id,
                state_revision=rev,
                decision_kind=packet.decision_kind,
                incident_key=packet.incident_key,
                reason=packet.reason,
                evidence=packet.evidence,
                allowed_kinds=packet.allowed_kinds,
                options=packet.options,
                coverage=packet.coverage,
                validated_selections=enriched,
            )
            rendered = render_validated_selections(test_packet)
            self.assertIn("SIMULATION — NOT EXECUTED", rendered)
            self.assertIn("Selection 1", rendered)
            self.assertIn("Selection 2", rendered)
            self.assertIn(f"Current live state revision is {rev}.", rendered)
            self.assertLess(len(rendered.encode("utf-8")), 3072)
        finally:
            if proc.stdin:
                proc.stdin.close()
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()
            proc.kill()
            proc.wait()

    def test_zero_or_one_valid_selection_no_fabricated_alternative(self):
        """Zero selections issue 0 queries; 1 selection issues 1 query and formats 1 card without fabricating another."""
        exchange = MockExchange()

        packet = DecisionPacket(
            decision_id="dec-test-zero",
            state_revision=10,
            decision_kind="tactical",
            incident_key="inc-test",
            reason="contact",
            evidence={},
            allowed_kinds=["choose"],
            options=[{"option_id": "opt-1", "actions": [{"action": "Move", "unit_id": 1, "col": 2, "row": 3}]}],
            coverage={},
            final_only=False,
        )

        # Zero valid selections: 0 queries, 0 enriched cards
        zero_enriched, z_queries = preview_validated_selections(
            packet, [], exchange, 10, no_recruit_macro=False)
        self.assertEqual(len(zero_enriched), 0)
        self.assertEqual(z_queries, 0)
        self.assertEqual(len(exchange.queries), 0)

        # One valid selection: 1 query, 1 enriched card
        one_selection = [{"option_ids": ["opt-1"], "finish_turn": False, "source_revision": 10}]
        one_enriched, o_queries = preview_validated_selections(
            packet, one_selection, exchange, 10, no_recruit_macro=False)
        self.assertEqual(len(one_enriched), 1)
        self.assertEqual(o_queries, 1)
        self.assertEqual(len(exchange.queries), 1)
        self.assertIn("consequences", one_enriched[0])

        # Renders exactly Selection 1, no Selection 2
        p_one = DecisionPacket(
            decision_id="dec-test-one",
            state_revision=10,
            decision_kind="tactical",
            incident_key="inc-test",
            reason="contact",
            evidence={},
            allowed_kinds=["choose"],
            options=packet.options,
            coverage={},
            validated_selections=one_enriched,
        )
        rendered = render_validated_selections(p_one)
        self.assertIn("Selection 1", rendered)
        self.assertNotIn("Selection 2", rendered)

    def test_preview_budget_exhaustion_preserves_selections_with_unavailable_coverage(self):
        """When preview query budget is exhausted, selections remain but consequences are marked unavailable."""
        exchange = MockExchange()
        exchange.query_limit_on.add("preview_batch")

        packet = DecisionPacket(
            decision_id="dec-test-2",
            state_revision=10,
            decision_kind="tactical",
            incident_key="inc-test",
            reason="contact",
            evidence={},
            allowed_kinds=["choose"],
            options=[{"option_id": "opt-1", "actions": [{"action": "Move", "unit_id": 1, "col": 2, "row": 3}]}],
            coverage={},
            final_only=False,
        )
        selections = [{"option_ids": ["opt-1"], "finish_turn": False, "source_revision": 10}]

        enriched, p_queries = preview_validated_selections(
            packet, selections, exchange, 10, no_recruit_macro=False)

        self.assertEqual(p_queries, 0)
        self.assertEqual(len(enriched), 1)
        self.assertIn("consequences", enriched[0])
        self.assertEqual(enriched[0]["consequences"]["coverage"], "unavailable")
        self.assertEqual(enriched[0]["consequences"]["reason"], "query_budget_exhausted")

    def test_transport_failure_propagates_runtime_error(self):
        """A real transport failure on preview_batch raises RuntimeError."""
        exchange = MockExchange()
        exchange.fail_on.add("preview_batch")

        packet = DecisionPacket(
            decision_id="dec-test-3",
            state_revision=10,
            decision_kind="tactical",
            incident_key="inc-test",
            reason="contact",
            evidence={},
            allowed_kinds=["choose"],
            options=[{"option_id": "opt-1", "actions": [{"action": "Move", "unit_id": 1, "col": 2, "row": 3}]}],
            coverage={},
            final_only=False,
        )
        selections = [{"option_ids": ["opt-1"], "finish_turn": False, "source_revision": 10}]

        with self.assertRaises(RuntimeError):
            preview_validated_selections(packet, selections, exchange, 10, no_recruit_macro=False)

    def test_final_only_appends_no_sweep_and_requests_final_phase(self):
        """When selections have finish_turn=True, phase='final' and NO_SWEEP_FINISH is appended."""
        exchange = MockExchange()

        packet = DecisionPacket(
            decision_id="dec-test-4",
            state_revision=10,
            decision_kind="tactical",
            incident_key="inc-test",
            reason="contact",
            evidence={},
            allowed_kinds=["choose"],
            options=[{"option_id": "opt-1", "actions": [{"action": "Move", "unit_id": 1, "col": 2, "row": 3}]}],
            coverage={},
            final_only=True,
        )
        selections = [{"option_ids": ["opt-1"], "finish_turn": True, "source_revision": 10}]

        enriched, p_queries = preview_validated_selections(
            packet, selections, exchange, 10, no_recruit_macro=False)

        self.assertEqual(len(exchange.queries), 1)
        query = exchange.queries[0]
        self.assertEqual(query["what"], "preview_batch")
        self.assertEqual(query["phase"], "final")
        candidate_actions = query["candidates"][0]
        self.assertEqual(candidate_actions[-1]["action"], "FinishWithGreedy")

    def test_end_to_end_scripted_backend_chooses_selection(self):
        """Card B from the delivered prompt commits its exact option actions."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Two adjacent friendly attackers make the delivered packet expose
            # two independent legal cards.  Card B is then read from the
            # prompt and linked to the exact committed attack identity.
            extra_combatant = {
                "id": 7, "def_id": "Skeleton", "name": "Skeleton", "level": 1,
                "faction": 0, "hp": 34, "max_hp": 34, "movement": 5,
                "col": 10, "row": 8, "moved": False, "attacked": False,
                "can_recruit": False, "advancement_pending": False,
                "slowed": False, "poisoned": False, "xp": 0,
                "xp_needed": 30, "abilities": [],
            }
            initial_policy = {
                "reserve_gold": 0, "recruits": [], "scouts": [],
                "villages": [], "rally": None, "holds": [],
            }
            responses = [
                policy("set_policy", initial_policy),
                choose("unused", finish=True),
            ]
            checkpoint, _, backend, prompt_log = prepare(
                root, "contact.json", responses, extra_units=[extra_combatant])
            # The model reads the actual second card from the prompt.  This
            # catches a forwarded-order test that merely proves some legal
            # order was sent without linking it to the displayed card.
            backend.write_text(textwrap.dedent(f"""
                import json, re, sys
                from pathlib import Path
                log_path = Path({str(prompt_log)!r})
                prompt = sys.stdin.read()
                with log_path.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps({{'prompt': prompt}}) + '\\n')
                calls = len(log_path.read_text(encoding='utf-8').splitlines())
                if calls == 1:
                    response = {json.dumps(json.dumps(policy("set_policy", initial_policy), separators=(',', ':')))}
                elif calls == 2:
                    cards = [json.loads(value) for value in re.findall(
                        r'To choose this selection: ([{{].*?[}}])', prompt)]
                    if len(cards) < 2:
                        raise SystemExit('delivered prompt did not contain Card B')
                    response = json.dumps(cards[1], separators=(',', ':'))
                else:
                    # Card B is deliberately submitted without its boundary so
                    # the next ordinary model request proves the engine starts
                    # a new checkpoint.  End that same side turn explicitly.
                    response = json.dumps({{"kind": "finish_turn"}}, separators=(',', ':'))
                print(json.dumps({{'text': response}}))
            """).lstrip(), encoding="utf-8")
            log = root / "consequence-choose.ndjson"
            result = launch(root, log, checkpoint, backend, turns=1)
            self.assertEqual(result.returncode, 0, f"Launch failed:\n{result.stderr}\n{result.stdout}")

            # Verify simulation comparison block appeared in delivered prompt
            prompts = [json.loads(line)["prompt"] for line in prompt_log.read_text().splitlines() if line.strip()]
            self.assertTrue(any("SIMULATION — NOT EXECUTED" in p for p in prompts),
                            "Expected SIMULATION — NOT EXECUTED in delivered prompt")
            self.assertTrue(any("Selection 1" in p for p in prompts),
                            "Expected Selection 1 in delivered prompt")
            card_lines = re.findall(r"To choose this selection: (\{.*?\})", next(
                p for p in prompts if "SIMULATION — NOT EXECUTED" in p))
            self.assertGreaterEqual(len(card_lines), 2)
            card_b = json.loads(card_lines[1])

            rows = records(log)
            f_rows = [r for r in rows if r.get("type") == "forwarded_orders"]
            llm_row = next(r for r in f_rows if r.get("source") == "llm")
            self.assertEqual(llm_row.get("option_ids"), card_b["option_ids"])
            self.assertTrue(any(
                r.get("source") == "llm"
                and any(order.get("action") == "FinishWithGreedy"
                        for order in r.get("orders", []) if isinstance(order, dict))
                for r in f_rows
            ), "Card B execution must be followed by an explicit finish boundary")
            packet_row = next(r for r in rows if r.get("type") == "decision_packet"
                              and (r.get("decision_id") == card_b["decision_id"]
                                   or r.get("packet", {}).get("decision_id") == card_b["decision_id"]))
            by_id = {o["option_id"]: o for o in packet_row["packet"]["options"]}
            expected_orders = [action for option_id in card_b["option_ids"]
                               for action in by_id[option_id]["actions"]]
            if card_b["finish_turn"]:
                expected_orders.append(copy.deepcopy(NO_SWEEP_FINISH))
            self.assertEqual(llm_row["orders"], expected_orders)
            committed = self._driver_events(rows)
            self.assertTrue(committed, "Card B must produce committed engine events")
            expected_events = []
            for action in expected_orders:
                if action.get("action") == "Move":
                    expected_events.append(("move", action.get("unit_id"),
                                            action.get("col"), action.get("row")))
                elif action.get("action") == "Attack":
                    expected_events.append(("attack", action.get("attacker_id"),
                                            action.get("defender_id")))
            actual_events = []
            for event in committed:
                if event.get("source") != "llm":
                    continue
                if event.get("kind") == "move":
                    actual_events.append(("move", event.get("unit"),
                                          event.get("to", {}).get("col"),
                                          event.get("to", {}).get("row")))
                elif event.get("kind") == "attack":
                    actual_events.append(("attack", event.get("attacker", {}).get("unit"),
                                          event.get("defender", {}).get("unit")))
            self.assertEqual(actual_events, expected_events)

    def test_end_to_end_scripted_backend_authors_legal_custom_action(self):
        """End-to-end launch with greedy_driver: scripted backend authors legal act outside cards and it commits."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Skeleton 3 relocates to (10, 6) directly via custom act
            responses = [
                policy(),
                {
                    "kind": "act",
                    "actions": [{"action": "Move", "unit_id": 3, "col": 10, "row": 6}],
                    "finish_turn": True,
                }
            ]
            checkpoint, _, backend, prompt_log = prepare(root, "contact.json", responses)
            log = root / "consequence-custom-act.ndjson"
            result = launch(root, log, checkpoint, backend, turns=1)
            self.assertEqual(result.returncode, 0, f"Launch failed:\n{result.stderr}\n{result.stdout}")

            rows = records(log)
            f_rows = [r for r in rows if r.get("type") == "forwarded_orders"]
            llm_orders = [r for r in f_rows if r.get("source") == "llm"]
            self.assertTrue(len(llm_orders) > 0, "Custom action must commit with source 'llm'")
            self.assertEqual(llm_orders[0]["orders"][0]["action"], "Move")
            self.assertEqual(llm_orders[0]["orders"][0]["unit_id"], 3)
            move_events = [event for event in self._driver_events(rows)
                           if event.get("kind") == "move" and event.get("unit") == 3]
            self.assertTrue(move_events)
            self.assertEqual((move_events[0]["to"]["col"], move_events[0]["to"]["row"]), (10, 6))

    @staticmethod
    def _run_direct_driver(checkpoint_dir: Path, *, preview: bool,
                           checkpoint: Path | None = None,
                           actions: list[dict] | None = None) -> list[dict]:
        envelope = json.loads(checkpoint.read_text()) if checkpoint else {}
        proc = subprocess.Popen(
            [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
             "--faction1", "undead", "--gold", str(envelope.get("starting_gold", 300)),
             "--seed", str(envelope.get("seed", 9211)),
             "--llm-side", "0", "--max-turns", "1", "--incremental-turns",
             "--checkpoint-dir", str(checkpoint_dir)]
            + (["--resume-checkpoint", str(checkpoint)] if checkpoint else []),
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        rows: list[dict] = []
        actions = actions or [{"action": "RecruitBatch", "def_id": "Skeleton", "count": 1},
                              {"action": "EndTurn"}]

        def read_until(kind: str) -> dict:
            while True:
                line = proc.stdout.readline()
                if not line:
                    raise AssertionError(f"driver EOF while waiting for {kind}: {proc.stderr.read()}")
                value = json.loads(line)
                rows.append(value)
                if value.get("type") == kind:
                    return value

        try:
            initial = read_until("state")
            revision = initial["state_revision"]
            if preview:
                proc.stdin.write(json.dumps({
                    "action": "Query", "what": "preview_batch",
                    "state_revision": revision, "phase": "final", "mode": "forecast",
                    "candidates": [actions],
                }) + "\n")
                proc.stdin.flush()
                response = read_until("status")
                if not response.get("ok"):
                    raise AssertionError(response)
                if any(row.get("type") == "events" for row in rows):
                    raise AssertionError("read-only preview emitted events")
            proc.stdin.write(json.dumps(actions) + "\n")
            proc.stdin.flush()
            read_until("game_end")
            return rows
        finally:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=5)
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                stream.close()

    def test_preview_and_no_preview_checkpoint_execution_are_identical(self):
        """Read-only forecast does not alter combat events, progress, or RNG."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, _, _ = prepare(root, "contact.json", [policy()])
            combat_actions = [
                {"action": "Move", "unit_id": 3, "col": 11, "row": 6},
                {"action": "Attack", "attacker_id": 3, "defender_id": 4},
                copy.deepcopy(NO_SWEEP_FINISH),
            ]
            starting_rng = json.loads(checkpoint.read_text())["save_state"]["rng_state"]
            with_preview_dir = root / "with-preview"
            without_preview_dir = root / "without-preview"
            with_preview_dir.mkdir()
            without_preview_dir.mkdir()
            with_preview = self._run_direct_driver(
                with_preview_dir, preview=True, checkpoint=checkpoint,
                actions=combat_actions)
            without_preview = self._run_direct_driver(
                without_preview_dir, preview=False, checkpoint=checkpoint,
                actions=combat_actions)

            self.assertEqual(self._driver_events(with_preview), self._driver_events(without_preview))
            end_a = next(row for row in with_preview if row.get("type") == "game_end")
            end_b = next(row for row in without_preview if row.get("type") == "game_end")
            for key in ("gold", "active_faction", "turn", "state_revision", "units"):
                self.assertEqual(end_a["state"].get(key), end_b["state"].get(key), key)
            checkpoints_a = [row for row in with_preview if row.get("type") == "checkpoint"]
            checkpoints_b = [row for row in without_preview if row.get("type") == "checkpoint"]
            self.assertTrue(checkpoints_a and checkpoints_b)
            saved_a = json.loads((with_preview_dir / checkpoints_a[-1]["path"]).read_text())
            saved_b = json.loads((without_preview_dir / checkpoints_b[-1]["path"]).read_text())
            self.assertEqual(saved_a["save_state"], saved_b["save_state"])
            self.assertNotEqual(saved_a["save_state"]["rng_state"], starting_rng)


if __name__ == "__main__":
    unittest.main()
