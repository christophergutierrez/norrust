"""S2 measurable milestone: the eight ending cases through the real driver,
recorded by tools.llm_client and imported by tools.game_history.

{model victory, Greedy victory, resignation, cap draw} x {llm_side 0, 1}.

Model/Greedy victory use a tiny test-only fixture
(norrust_core/tests/fixtures/s2_deterministic_duel) instead of a real
scenario: two adjacent leaders, one faction ("lethal") whose single strike
(damage=100) always exceeds the other's max_hp (1), paired with a faction
("fragile") whose own strike (damage=1) can never bring a "lethal" leader
(max_hp=20) below 1 hp. The fixture's terrain (data/terrain/keep.toml) sets
default_defense=0, which `Rng::roll_hit` treats as an unconditional hit
(hit_pct >= 100 skips the RNG roll entirely) -- so the kill is deterministic
by construction, not by a favorable seed. Whoever gets to act first with the
"lethal" faction always wins; the tests below simply choose which side that
is by assigning factions and llm_side, and give the loser a legal but
harmless move via the deterministic --orders-file responder.

Resignation and cap draw don't need the duel fixture (no combat), so they
reuse the same tiny board with the harmless "fragile" faction on both sides.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .game_history import import_game, open_history

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))
FIXTURE_ROOT = ROOT / "norrust_core/tests/fixtures/s2_deterministic_duel"
END_TURN = json.dumps({"text": json.dumps([{"action": "EndTurn"}])})
RESIGN = json.dumps({"text": json.dumps([{"action": "Resign"}])})


def _attack(attacker_id: int, defender_id: int) -> str:
    return json.dumps({"text": json.dumps(
        [{"action": "Attack", "attacker_id": attacker_id, "defender_id": defender_id},
         {"action": "EndTurn"}])})


def _run(directory: Path, *, faction0: str, faction1: str, llm_side: int,
         orders_lines: list[str], max_turns: int = 50) -> tuple[Path, subprocess.CompletedProcess]:
    orders_path = directory / "orders.jsonl"
    orders_path.write_text("\n".join(orders_lines) + ("\n" if orders_lines else ""))
    log = directory / "match.ndjson"
    command = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
               "--orders-file", str(orders_path), "--scenario", "duel",
               "--faction0", faction0, "--faction1", faction1, "--gold", "0",
               "--seed", "42", "--llm-side", str(llm_side), "--max-turns", str(max_turns),
               "--log", str(log), "--query-budget-seconds", "10", "--model-timeout", "10",
               "--turn-timeout", "30"]
    env = dict(os.environ, NORRUST_TEST_ROOT_DIR=str(FIXTURE_ROOT))
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    return log, result


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
@unittest.skipUnless(FIXTURE_ROOT.is_dir(), "s2_deterministic_duel fixture is missing")
class DeterministicEndingImportTests(unittest.TestCase):
    """Runs the real driver end to end and imports the resulting archive.

    Every case asserts the plan's exact requirements: a provable opening
    (`opening_present`), a terminal state matching the engine result after
    import (`terminal_present`, `winner_side`, `termination_reason`), and
    zero unresolved required boundaries (`coverage["gaps"] == []` and
    `unresolved_turn_endpoints` absent from those gaps).
    """

    def _import_and_check(self, log: Path, result: subprocess.CompletedProcess, *,
                          expected_status: str, expected_winner, expected_reason: str):
        self.assertEqual(result.returncode, 0, result.stderr[-3000:] + log.read_text()[-3000:])
        with tempfile.TemporaryDirectory() as db_dir:
            conn = open_history(Path(db_dir) / "history.sqlite")
            # import_game (in this process) may spawn dump_checkpoint itself
            # to try rendering a checkpoint-only snapshot; it must resolve
            # "Lethal"/"Fragile" against the same fixture data, not the real
            # data/ directory.
            old_test_root = os.environ.get("NORRUST_TEST_ROOT_DIR")
            os.environ["NORRUST_TEST_ROOT_DIR"] = str(FIXTURE_ROOT)
            try:
                game_id = import_game(conn, log)
            finally:
                if old_test_root is None:
                    os.environ.pop("NORRUST_TEST_ROOT_DIR", None)
                else:
                    os.environ["NORRUST_TEST_ROOT_DIR"] = old_test_root
            row = conn.execute(
                "SELECT status,winner_side,termination_reason,coverage_json FROM games WHERE game_id=?",
                (game_id,)).fetchone()
            self.assertIsNotNone(row, "game must be importable")
            status, winner_side, termination_reason, coverage_json = row
            coverage = json.loads(coverage_json)
            self.assertEqual(status, expected_status)
            self.assertEqual(winner_side, expected_winner)
            self.assertEqual(termination_reason, expected_reason)
            self.assertTrue(coverage["opening_present"], coverage)
            self.assertTrue(coverage["terminal_present"], coverage)
            self.assertEqual(coverage["gaps"], [], coverage)
            self.assertEqual(coverage["unresolved_turn_endpoints"], 0, coverage)
            conn.close()
        return coverage

    # --- model victory: {llm_side 0, llm_side 1} ---

    def test_model_victory_llm_side_0(self):
        with tempfile.TemporaryDirectory() as td:
            log, result = _run(Path(td), faction0="lethal", faction1="fragile", llm_side=0,
                               orders_lines=[_attack(1, 2)])
            self._import_and_check(log, result, expected_status="complete",
                                   expected_winner=0, expected_reason="winner")

    def test_model_victory_llm_side_1(self):
        with tempfile.TemporaryDirectory() as td:
            log, result = _run(Path(td), faction0="fragile", faction1="lethal", llm_side=1,
                               orders_lines=[_attack(2, 1)])
            self._import_and_check(log, result, expected_status="complete",
                                   expected_winner=1, expected_reason="winner")

    # --- Greedy victory: {llm_side 0, llm_side 1} ---
    # The model side plays "fragile" and is given a legal but losing line (an
    # EndTurn that never attacks); Greedy plays "lethal" and kills it.

    def test_greedy_victory_llm_side_0(self):
        # More canned replies than turns: with an adjacent lethal enemy the
        # client may spend one call on a draft review before the final
        # response, so a single EndTurn line exhausts the orders file. Extra
        # lines are harmless - Greedy ends the game on its first turn.
        with tempfile.TemporaryDirectory() as td:
            log, result = _run(Path(td), faction0="fragile", faction1="lethal", llm_side=0,
                               orders_lines=[END_TURN] * 4)
            self._import_and_check(log, result, expected_status="complete",
                                   expected_winner=1, expected_reason="winner")

    def test_greedy_victory_llm_side_1(self):
        # Greedy (side 0, "lethal") kills the model's leader before the model
        # ever gets a turn -- the orders file is never consumed.
        with tempfile.TemporaryDirectory() as td:
            log, result = _run(Path(td), faction0="lethal", faction1="fragile", llm_side=1,
                               orders_lines=[])
            self._import_and_check(log, result, expected_status="complete",
                                   expected_winner=0, expected_reason="winner")

    # --- resignation: {llm_side 0, llm_side 1} ---

    def test_resignation_llm_side_0(self):
        with tempfile.TemporaryDirectory() as td:
            log, result = _run(Path(td), faction0="fragile", faction1="fragile", llm_side=0,
                               orders_lines=[RESIGN])
            self._import_and_check(log, result, expected_status="complete",
                                   expected_winner=1, expected_reason="resignation")

    def test_resignation_llm_side_1(self):
        with tempfile.TemporaryDirectory() as td:
            log, result = _run(Path(td), faction0="fragile", faction1="fragile", llm_side=1,
                               orders_lines=[RESIGN])
            self._import_and_check(log, result, expected_status="complete",
                                   expected_winner=0, expected_reason="resignation")

    # --- cap draw: {llm_side 0, llm_side 1} ---
    # Neither faction attacks (both "fragile", harmless either way), so the
    # match always runs out the clock at --max-turns.

    def test_cap_draw_llm_side_0(self):
        with tempfile.TemporaryDirectory() as td:
            log, result = _run(Path(td), faction0="fragile", faction1="fragile", llm_side=0,
                               orders_lines=[END_TURN] * 5, max_turns=3)
            self._import_and_check(log, result, expected_status="complete",
                                   expected_winner=None, expected_reason="max_turns")

    def test_cap_draw_llm_side_1(self):
        with tempfile.TemporaryDirectory() as td:
            log, result = _run(Path(td), faction0="fragile", faction1="fragile", llm_side=1,
                               orders_lines=[END_TURN] * 5, max_turns=3)
            self._import_and_check(log, result, expected_status="complete",
                                   expected_winner=None, expected_reason="max_turns")


if __name__ == "__main__":
    unittest.main()
