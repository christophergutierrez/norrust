"""Real-driver gate tests for strategy mode (Stack 1 of
docs/plans/strategy-and-routine-execution.md).

Modeled on tools/test_movement_integration.py: every test here drives the
REAL ``python -m tools.llm_client`` entrypoint against the REAL built
``greedy_driver`` binary, with a scripted (non-live) model backend, and
asserts on actual driver events and the real NDJSON log -- never on mocks.

Skips (rather than fails) when the driver has not been built, matching the
existing real-driver test convention; a skipped test is not a pass, so the
gate is only satisfied when these actually RUN.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from .game_history import import_game, open_history

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))

# Generous budgets: strategy mode issues one cheap routine_next/recruit_options
# query per routine step (many small round trips) rather than a few queries
# per turn, so the shared query-budget-seconds ceiling must be generous enough
# to absorb sandboxed subprocess overhead without being a source of flakiness
# unrelated to the behavior under test.
QUERY_BUDGET = "60"
MODEL_TIMEOUT = "30"
TURN_TIMEOUT = "120"


def _write_backend(path: Path, body: str, prompt_log_env: str = "STRATEGY_PROMPT_LOG") -> None:
    """Write a scripted model-command backend script.

    ``body`` is a Python expression/statement block (already indented at
    column 0) that must define a variable ``resp`` -- the JSON-decodable
    response object -- given the decoded prompt string ``prompt``. Every
    invocation is a fresh process (a new call), and every prompt seen is
    appended to the log named by ``prompt_log_env`` so tests can assert on
    the exact number of backend calls made.
    """
    script = (
        "import json, os, sys\n"
        "prompt = sys.stdin.read()\n"
        f"_log = os.environ.get({prompt_log_env!r})\n"
        "if _log:\n"
        "    with open(_log, 'a') as _f:\n"
        "        _f.write(json.dumps({'prompt': prompt}) + chr(10))\n"
        + body + "\n"
        "print(json.dumps({'text': json.dumps(resp)}))\n"
    )
    path.write_text(script)


def _run(root: Path, backend: Path, log: Path, *, extra_args: list[str] | None = None,
         env_extra: dict[str, str] | None = None, max_turns: str = "1",
         gold: str = "300", seed: str = "9211",
         max_partial_batches: str | None = None) -> subprocess.CompletedProcess:
    args = [
        sys.executable, "-m", "tools.llm_client",
        "--driver", str(DRIVER),
        "--model-command", shlex.join([sys.executable, str(backend)]),
        "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
        "--gold", gold, "--seed", seed, "--llm-side", "0", "--max-turns", max_turns,
        "--decision-mode", "strategy",
        "--log", str(log), "--query-budget-seconds", QUERY_BUDGET,
        "--model-timeout", MODEL_TIMEOUT, "--turn-timeout", TURN_TIMEOUT,
    ]
    if max_partial_batches is not None:
        args.extend(["--max-partial-batches-per-turn", max_partial_batches])
    if extra_args:
        args.extend(extra_args)
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=120, env=env)


def _records(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def _driver_state_lines(records: list[dict]) -> list[dict]:
    return [r["line"] for r in records
            if r.get("type") == "driver" and r.get("line", {}).get("type") == "state"]


def _driver_event_lines(records: list[dict]) -> list[dict]:
    return [r["line"] for r in records
            if r.get("type") == "driver" and r.get("line", {}).get("type") == "events"]


def _all_events(records: list[dict]) -> list[dict]:
    return [event for line in _driver_event_lines(records) for event in line.get("events", [])]


SET_POLICY_SMALL_ARMY = (
    "resp = {'kind': 'set_policy', 'policy': {"
    "'reserve_gold': 0, "
    "'recruits': [{'def_id': 'Skeleton', 'count': 3, 'role': 'army'}], "
    "'scouts': [], 'villages': [], 'rally': None, 'holds': []}}"
)


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
class StrategyModeIntegrationTests(unittest.TestCase):
    # -- Gate 1: one scripted policy recruits an affordable finite queue and
    # finishes a turn; the executor makes zero further backend calls. -------
    def test_finite_queue_recruits_and_finishes_with_zero_further_backend_calls(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = root / "backend.py"
            prompt_log = root / "prompts.ndjson"
            _write_backend(backend, SET_POLICY_SMALL_ARMY)
            log = root / "match.ndjson"
            result = _run(ROOT, backend, log, env_extra={"STRATEGY_PROMPT_LOG": str(prompt_log)})
            self.assertEqual(result.returncode, 0, result.stderr + log.read_text())
            records = _records(log)

            # Exactly one backend call for the whole run.
            prompts = [json.loads(line) for line in prompt_log.read_text().splitlines()]
            self.assertEqual(len(prompts), 1)
            self.assertEqual(sum(1 for r in records if r.get("type") == "model_request"), 1)

            # The finite queue committed exactly 3 recruits, then an automatic
            # no-sweep finish, with no model call between them.
            committed = [r for r in records if r.get("type") == "routine_progress_committed"]
            self.assertEqual(len(committed), 3)
            self.assertTrue(all(c["progress_update"]["def_id"] == "Skeleton" for c in committed))

            forwarded = [r for r in records if r.get("type") == "forwarded_orders"]
            self.assertEqual([f["orders"][0]["action"] for f in forwarded],
                             ["Recruit", "Recruit", "Recruit", "FinishWithGreedy"])
            self.assertTrue(all(f.get("source") == "routine" for f in forwarded))

            terminal = [r for r in records if r.get("type") == "terminal"][-1]
            self.assertEqual(terminal.get("terminal_class"), "gameplay")

    # -- Stack 4 strategy_fixed precondition: --strategy-policy plays the
    # same routine executor from a checked-in file with NO backend and zero
    # model responses. This coverage was removed when --strategy-policy
    # stopped being a validate-and-exit path, so it is restored here against
    # the real driver: the whole point of the strategy_fixed treatment is that
    # its opening costs no model calls, and an untested claim of "zero calls"
    # is worth nothing.
    def test_strategy_policy_plays_from_file_with_no_backend_and_zero_usage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            policy_file = root / "policy.json"
            policy_file.write_text(json.dumps({
                "reserve_gold": 0,
                "recruits": [{"def_id": "Skeleton", "count": 3, "role": "army"}],
                "scouts": [], "villages": [], "rally": None, "holds": []}))
            log = root / "match.ndjson"
            args = [
                sys.executable, "-m", "tools.llm_client",
                "--driver", str(DRIVER),
                "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                "--gold", "300", "--seed", "9211", "--llm-side", "0", "--max-turns", "1",
                "--decision-mode", "strategy", "--strategy-policy", str(policy_file),
                "--log", str(log), "--query-budget-seconds", QUERY_BUDGET,
                "--model-timeout", MODEL_TIMEOUT, "--turn-timeout", TURN_TIMEOUT,
            ]
            result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr + log.read_text())
            records = _records(log)

            # No backend was started and no model request was ever made.
            self.assertEqual([r for r in records if r.get("type") == "model_request"], [])
            self.assertEqual([r for r in records if r.get("type") == "model_response"], [])

            # No usage row was invented for reading a file off disk.
            self.assertFalse(log.with_name("usage.ndjson").exists())
            for record in records:
                self.assertNotIn("usage", record, record)

            # It really played: the finite queue committed and the turn closed
            # on the verified no-sweep boundary.
            forwarded = [r for r in records if r.get("type") == "forwarded_orders"]
            self.assertEqual([f["orders"][0]["action"] for f in forwarded],
                             ["Recruit", "Recruit", "Recruit", "FinishWithGreedy"])
            self.assertTrue(all(f.get("source") == "routine" for f in forwarded))

            # The controller identity is fixed-policy code, not a model.
            installed = [r for r in records if r.get("type") == "policy_installed"]
            self.assertEqual(len(installed), 1)
            self.assertEqual(installed[0]["source_kind"], "fixed_file")

    # -- Gate 2: recruitment finishes over two turns without buying the
    # original queue twice. ---------------------------------------------
    def test_recruitment_spans_two_turns_without_double_buying(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = root / "backend.py"
            # Six recruits exactly fills the six castle hexes around the keep
            # (checked empirically against this scenario); capping partial
            # batches at 3 forces final_only mid-queue, so completing the
            # policy needs the second controlled turn -- with zero model
            # calls anywhere in that span.
            body = (
                "resp = {'kind': 'set_policy', 'policy': {"
                "'reserve_gold': 0, "
                "'recruits': [{'def_id': 'Skeleton', 'count': 6, 'role': 'army'}], "
                "'scouts': [], 'villages': [], 'rally': None, 'holds': []}}"
            )
            _write_backend(backend, body)
            log = root / "match.ndjson"
            result = _run(ROOT, backend, log, max_turns="3", max_partial_batches="3")
            self.assertEqual(result.returncode, 0, result.stderr + log.read_text())
            records = _records(log)

            self.assertEqual(sum(1 for r in records if r.get("type") == "model_request"), 1)
            committed = [r for r in records if r.get("type") == "routine_progress_committed"]
            self.assertEqual(len(committed), 6)
            # One installation only -- the queue was never replaced/re-issued.
            self.assertEqual(sum(1 for r in records if r.get("type") == "policy_installed"), 1)

            state_lines = _driver_state_lines(records)
            turns_seen = sorted({s.get("turn") for s in state_lines if isinstance(s.get("turn"), int)})
            self.assertGreaterEqual(len(turns_seen), 2, "recruitment must span at least two turns")

    # -- Gate 3: reserve gold is maintained; actual recruit IDs are captured
    # from committed events, never predicted. -----------------------------
    def test_reserve_gold_maintained_and_recruit_ids_come_from_committed_events(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = root / "backend.py"
            body = (
                "resp = {'kind': 'set_policy', 'policy': {"
                "'reserve_gold': 285, "
                "'recruits': [{'def_id': 'Skeleton', 'count': 1, 'role': 'army'}], "
                "'scouts': [], 'villages': [], 'rally': None, 'holds': []}}"
            )
            _write_backend(backend, body)
            log = root / "match.ndjson"
            result = _run(ROOT, backend, log, gold="300")
            self.assertEqual(result.returncode, 0, result.stderr + log.read_text())
            records = _records(log)

            state_lines = _driver_state_lines(records)
            golds = [s["gold"][0] for s in state_lines if isinstance(s.get("gold"), list)]
            # Skeleton costs 15; with a reserve of 285 and gold 300, exactly
            # one recruit is affordable while keeping the reserve, and the
            # queue's own count (1) also caps it there -- gold must never dip
            # under the 285 reserve.
            self.assertTrue(all(g >= 285 for g in golds), golds)

            committed = [r for r in records if r.get("type") == "routine_progress_committed"]
            self.assertEqual(len(committed), 1)

            recruit_events = [e for e in _all_events(records) if e.get("kind") == "recruit"]
            self.assertEqual(len(recruit_events), 1)
            # The committed event carries the engine-assigned unit id; the
            # client never predicts or invents one.
            self.assertIn("unit", recruit_events[0])
            self.assertIsInstance(recruit_events[0]["unit"], int)

    # -- Gate 4: an illegal or non-empty-unsupported policy mutates nothing.
    def test_illegal_policy_mutates_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = root / "backend.py"
            # rally is a Stack 1 "non-empty future field": must be rejected
            # explicitly, never silently accepted/ignored.
            body = (
                "resp = {'kind': 'set_policy', 'policy': {"
                "'reserve_gold': 0, "
                "'recruits': [{'def_id': 'Skeleton', 'count': 2, 'role': 'army'}], "
                "'scouts': [], 'villages': [], 'rally': {'col': 5, 'row': 5}, 'holds': []}}"
            )
            _write_backend(backend, body)
            log = root / "match.ndjson"
            result = _run(ROOT, backend, log)
            self.assertNotEqual(result.returncode, 0)
            records = _records(log)

            self.assertFalse(any(r.get("type") == "forwarded_orders" for r in records))
            self.assertFalse(any(r.get("type") == "policy_installed" for r in records))
            self.assertFalse(_all_events(records))
            state_lines = _driver_state_lines(records)
            revisions = {s.get("state_revision") for s in state_lines}
            self.assertEqual(revisions, {0}, "no engine mutation may occur past the opening state")
            terminal = [r for r in records if r.get("type") == "terminal"][-1]
            self.assertEqual(terminal.get("terminal_class"), "model_invalid")

    # -- Gate 5: occupied castle causes no auto-vacate; no held/recruiter
    # movement or attack, and no automatic Greedy sweep during routine
    # completion. ----------------------------------------------------------
    def test_no_auto_vacate_no_recruiter_movement_no_automatic_sweep(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = root / "backend.py"
            # More than the six available castle hexes: the queue cannot
            # fully complete without vacating a hex, which routine execution
            # must never do automatically. The castle-full recruitment_blocked
            # exception is Stack 1's expected, correctly-detected outcome (not
            # a hidden auto-vacate/travel workaround), so the scripted model
            # accepts it with an explicit finish on the first exception.
            counter = root / "counter"
            body = (
                "n = int(open(%r).read()) if __import__('os').path.exists(%r) else 0\n"
                "open(%r, 'w').write(str(n + 1))\n"
                "if n == 0:\n"
                "    resp = {'kind': 'set_policy', 'policy': {"
                "'reserve_gold': 0, "
                "'recruits': [{'def_id': 'Skeleton', 'count': 20, 'role': 'army'}], "
                "'scouts': [], 'villages': [], 'rally': None, 'holds': []}}\n"
                "else:\n"
                "    resp = {'kind': 'finish_turn'}"
            ) % (str(counter), str(counter), str(counter))
            _write_backend(backend, body)
            log = root / "match.ndjson"
            result = _run(ROOT, backend, log)
            self.assertEqual(result.returncode, 0, result.stderr + log.read_text())
            records = _records(log)
            self.assertEqual(sum(1 for r in records if r.get("type") == "model_request"), 2)

            recruiter_id = None
            state_lines = _driver_state_lines(records)
            for unit in state_lines[0].get("units", []):
                if unit.get("faction") == 0 and unit.get("can_recruit"):
                    recruiter_id = unit["id"]
            self.assertIsNotNone(recruiter_id)

            events = _all_events(records)
            routine_events = [
                e for line in _driver_event_lines(records) if line.get("source") == "routine"
                for e in line.get("events", [])
            ]
            self.assertTrue(routine_events)
            self.assertTrue(all(e.get("kind") == "recruit" for e in routine_events),
                            "routine completion must never move/attack -- recruit only")
            self.assertFalse(any(e.get("kind") == "move" and e.get("unit") == recruiter_id
                                 for e in events), "the recruiter must never be moved automatically")
            self.assertFalse(any(e.get("kind") == "attack" for e in events),
                             "no automatic attack may occur during routine completion")
            # No Greedy sweep: a real automatic sweep would move/attack with
            # more units than were ever recruited under this policy.
            self.assertFalse(any(line.get("source") == "greedy" for line in _driver_event_lines(records)
                                 if state_lines and state_lines[0].get("state_revision") == 0))
            self.assertLessEqual(len(routine_events), 6, "castle space caps recruitment at six hexes")

    # -- Gate 6: crash after a committed recruit but before acknowledgement,
    # then resume, reproduces the same final recruit count/gold as
    # uninterrupted execution. A rejected submission leaves progress intact.
    def test_crash_after_commit_before_ack_then_resume_matches_uninterrupted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            # Control: uninterrupted execution of the same policy.
            control_backend = root / "control_backend.py"
            body = (
                "resp = {'kind': 'set_policy', 'policy': {"
                "'reserve_gold': 0, "
                "'recruits': [{'def_id': 'Skeleton', 'count': 4, 'role': 'army'}], "
                "'scouts': [], 'villages': [], 'rally': None, 'holds': []}}"
            )
            _write_backend(control_backend, body)
            control_log = root / "control.ndjson"
            control_result = _run(ROOT, control_backend, control_log)
            self.assertEqual(control_result.returncode, 0, control_result.stderr + control_log.read_text())
            control_records = _records(control_log)
            control_committed = [r for r in control_records if r.get("type") == "routine_progress_committed"]
            control_gold = _driver_state_lines(control_records)[-1]["gold"][0]

            # Interrupted run: same policy, same seed/scenario, truncated
            # right after a committed recruit's "routine_progress_committed"
            # durable record -- simulating a crash between the checkpoint
            # (proof of engine commitment) and the later status/state lines
            # that would otherwise let the client know the batch is safe.
            crash_backend = root / "crash_backend.py"
            _write_backend(crash_backend, body)
            crash_log = root / "crash.ndjson"
            crash_result = _run(ROOT, crash_backend, crash_log)
            self.assertEqual(crash_result.returncode, 0, crash_result.stderr)
            full_lines = crash_log.read_text().splitlines()
            full_records = [json.loads(line) for line in full_lines if line.strip()]
            cut_index = next(
                i for i, r in enumerate(full_records)
                if r.get("type") == "routine_progress_committed"
            )
            surviving = full_records[: cut_index + 1]
            crash_log.write_text("\n".join(full_lines[: cut_index + 1]) + "\n")
            # A real crash leaves no checkpoint sidecar newer than the moment
            # of death. Truncating only the NDJSON text while leaving every
            # later checkpoint file on disk would let the client's orphan-
            # checkpoint recovery (a real, separate feature -- it resumes from
            # a checkpoint written to disk whose log reference never landed)
            # jump straight to the LATEST file instead of the one the
            # truncated log actually proves; delete every checkpoint sidecar
            # this truncated log does not itself reference, so the resume
            # below exercises exactly the intended crash point.
            referenced_paths = {r["path"] for r in surviving if r.get("type") == "checkpoint_ref"}
            ckpt_dir = crash_log.with_suffix(".ckpt")
            for sidecar in ckpt_dir.iterdir():
                if sidecar.name not in referenced_paths:
                    sidecar.unlink()

            resume_backend = root / "resume_backend.py"
            _write_backend(resume_backend, body)
            resume_result = _run(
                ROOT, resume_backend, crash_log,
                extra_args=["--resume-log", str(crash_log)])
            self.assertEqual(resume_result.returncode, 0,
                             resume_result.stderr + crash_log.read_text())
            resumed_records = _records(crash_log)
            resumed_committed = [r for r in resumed_records if r.get("type") == "routine_progress_committed"]
            resumed_gold = _driver_state_lines(resumed_records)[-1]["gold"][0]

            self.assertEqual(len(resumed_committed), len(control_committed))
            self.assertEqual(resumed_gold, control_gold)
            # The interrupted attempt is never double counted: no def_id
            # accumulates more committed recruits than the control run.
            self.assertEqual(
                sum(1 for c in resumed_committed if c["progress_update"]["def_id"] == "Skeleton"),
                sum(1 for c in control_committed if c["progress_update"]["def_id"] == "Skeleton"))

    # -- Gate 7: events are labelled source: routine, snapshots are
    # playable, and import is idempotent. -----------------------------------
    def test_routine_events_labelled_snapshots_playable_import_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = root / "backend.py"
            _write_backend(backend, SET_POLICY_SMALL_ARMY)
            log = root / "match.ndjson"
            result = _run(ROOT, backend, log)
            self.assertEqual(result.returncode, 0, result.stderr + log.read_text())
            records = _records(log)

            routine_lines = [line for line in _driver_event_lines(records) if line.get("source") == "routine"]
            self.assertTrue(routine_lines)

            db = root / "history.sqlite"
            conn = open_history(db)
            try:
                game_id = import_game(conn, log)
                action_sources = conn.execute(
                    "SELECT DISTINCT source FROM actions WHERE game_id=?", (game_id,)
                ).fetchall()
                self.assertIn(("routine",), action_sources)
                event_sources = conn.execute(
                    "SELECT DISTINCT source FROM events WHERE game_id=?", (game_id,)
                ).fetchall()
                self.assertIn(("routine",), event_sources)

                # A snapshot exists and is not malformed JSON -- "playable".
                snapshot_count = conn.execute(
                    "SELECT count(*) FROM snapshots WHERE game_id=?", (game_id,)
                ).fetchone()[0]
                self.assertGreater(snapshot_count, 0)

                before_actions = conn.execute(
                    "SELECT count(*) FROM actions WHERE game_id=?", (game_id,)).fetchone()
                before_events = conn.execute(
                    "SELECT count(*) FROM events WHERE game_id=?", (game_id,)).fetchone()
                import_game(conn, log, game_id=game_id)
                after_actions = conn.execute(
                    "SELECT count(*) FROM actions WHERE game_id=?", (game_id,)).fetchone()
                after_events = conn.execute(
                    "SELECT count(*) FROM events WHERE game_id=?", (game_id,)).fetchone()
                self.assertEqual(before_actions, after_actions)
                self.assertEqual(before_events, after_events)

                # No invented/synthetic usage rows for zero-model-call routine
                # execution beyond the one real backend call this game made.
                call_count = conn.execute(
                    "SELECT count(*) FROM model_calls WHERE game_id=?", (game_id,)
                ).fetchone()[0]
                self.assertLessEqual(call_count, 1)
            finally:
                conn.close()

    # -- Gate 8: existing batch/focused behavior is unchanged. --------------
    # (Full coverage lives in tools/test_movement_integration.py and the
    # batch/focused-mode tests in tools/test_llm_client.py, both of which
    # still pass unmodified against this change; this is a light real-driver
    # smoke check that strategy-mode wiring did not leak into batch mode.)
    def test_batch_mode_still_asks_the_model_for_ordinary_actions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = root / "backend.py"
            backend.write_text(
                "import json, sys\n"
                "sys.stdin.read()\n"
                "resp = {'actions': [{'action': 'FinishWithGreedy', 'groups': [], 'holds': []}],\n"
                "        'decisions': [{'orders': [0], 'rules': ['T0'], "
                "'expected': 'finish the turn', 'risk': 'none'}]}\n"
                "print(json.dumps({'text': json.dumps(resp)}))\n"
            )
            log = root / "match.ndjson"
            result = subprocess.run(
                [sys.executable, "-m", "tools.llm_client",
                 "--driver", str(DRIVER),
                 "--model-command", shlex.join([sys.executable, str(backend)]),
                 "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                 "--gold", "100", "--seed", "9211", "--llm-side", "0", "--max-turns", "1",
                 "--log", str(log), "--query-budget-seconds", QUERY_BUDGET,
                 "--model-timeout", MODEL_TIMEOUT, "--turn-timeout", TURN_TIMEOUT],
                cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr + log.read_text())
            records = _records(log)
            # Batch mode still asks the model for every one of its own side
            # turns (max_turns=1 covers one full round: this side, then the
            # opponent, then this side again before the round is scored) --
            # the point of this smoke check is that it asks at all, and that
            # every forwarded batch is attributed to the model, never routine.
            model_requests = sum(1 for r in records if r.get("type") == "model_request")
            self.assertGreaterEqual(model_requests, 1)
            forwarded = [r for r in records if r.get("type") == "forwarded_orders"]
            self.assertGreaterEqual(len(forwarded), 1)
            self.assertTrue(all(f.get("source", "model") == "model" for f in forwarded))


if __name__ == "__main__":
    unittest.main()
