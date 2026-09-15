"""Offline fake-transport checks for recruitment-efficiency Stack 4 fixtures."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .game_history import import_game, open_history
from .test_strategy_routine_stack3 import (
    DRIVER, ROOT, assert_success, events, forwarded, launch, policy, records,
)
from .test_strategy_stack1_integration import prepare


FIXTURES = ROOT / "tools/fixtures/recruitment_efficiency"
STACK3 = ROOT / "tools/fixtures/strategy_routine/stack3"
BOARD_SHA = "26366c43a231ef9f7244b24fb74fe5343792c2c26bc0366941a097ce3c7c4207"
SAFE_TRAVEL_SHA = "251e699ec468c947029961bf25b1a5f33b0ceb1fa079c487e4491e2212a2eca8"
SCOUT_OPENING_SHA = "dd2f46e47df04f5071300b9e495463b587b02695159d9bfe1b8e2dd17f481d70"

CASTLE_IDS = list(range(10, 18))
TRAVEL_POLICY = {
    "reserve_gold": 0,
    "recruits": [{"def_id": "Skeleton", "count": 2, "role": "army"}],
    "scouts": [], "villages": [], "rally": {"col": 12, "row": 7}, "holds": [],
}
NO_RELIEF_POLICY = {
    "reserve_gold": 0,
    "recruits": [{"def_id": "Skeleton", "count": 1, "role": "army"}],
    "scouts": [], "villages": [], "rally": {"col": 12, "row": 7},
    "holds": CASTLE_IDS,
}
SCOUT_POLICY = {
    "reserve_gold": 0,
    "recruits": [
        {"def_id": "Ghost", "count": 1, "role": "scout"},
        {"def_id": "Skeleton", "count": 8, "role": "army"},
    ],
    "scouts": [], "villages": [{"col": 2, "row": 4}], "rally": None, "holds": [],
}


def _checkpoint(root: Path, source: Path) -> Path:
    data = json.loads(source.read_text())
    board = ROOT / "scenarios/big_battle_6/board.toml"
    if hashlib.sha256(board.read_bytes()).hexdigest() != BOARD_SHA:
        raise AssertionError("maintained big_battle_6 board hash changed")
    data["board_path"] = str(board)
    data["save_state"]["board_path"] = str(board)
    encoded = json.dumps(data, separators=(",", ":")).encode()
    checkpoint = root / ("checkpoint-" + hashlib.sha256(encoded).hexdigest() + ".json")
    checkpoint.write_bytes(encoded)
    return checkpoint


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before real-driver tests")
class RecruitmentEfficiencyFixtureTests(unittest.TestCase):
    def test_fixture_hashes(self):
        self.assertEqual(
            hashlib.sha256((FIXTURES / "safe_travel.json").read_bytes()).hexdigest(),
            SAFE_TRAVEL_SHA)
        self.assertEqual(
            hashlib.sha256((STACK3 / "blocked_objective.json").read_bytes()).hexdigest(),
            SCOUT_OPENING_SHA)

    def test_safe_travel_recruits_after_vacancy_and_imports_synthetic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint = _checkpoint(root, FIXTURES / "safe_travel.json")
            _, _, backend, prompt_log = prepare(
                root, "blocked_objective.json",
                [policy(value=TRAVEL_POLICY), {"kind": "finish_turn"}])
            log = root / "travel.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            self.assertTrue(any(
                row.get("source") == "routine"
                and (row.get("orders") or [{}])[0].get("action") == "Move"
                for row in forwarded(rows)))
            self.assertGreaterEqual(sum(
                1 for event in events(rows) if event.get("kind") == "recruit"), 2)
            self.assertEqual(len(prompt_log.read_text().splitlines()), 1)
            db = root / "history.sqlite"
            conn = open_history(db)
            try:
                game_id = import_game(conn, log)
                usage = conn.execute(
                    "SELECT COUNT(*) FROM model_calls WHERE game_id=?", (game_id,)
                ).fetchone()[0]
                # Fake transport does not create paid usage; missing remains unknown.
                self.assertEqual(usage, 0)
            finally:
                conn.close()
            self.assertIn("synthetic", (FIXTURES / "README.md").read_text())

    def test_no_relief_is_not_scored_as_recruitment_success(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint = _checkpoint(root, FIXTURES / "safe_travel.json")
            _, _, backend, _ = prepare(
                root, "blocked_objective.json",
                [policy(value=NO_RELIEF_POLICY), {"kind": "finish_turn"}])
            log = root / "no-relief.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            blocked = [row for row in rows if row.get("type") == "routine_exception"
                       and row.get("reason") == "recruitment_blocked"]
            self.assertTrue(blocked)
            self.assertEqual(
                (blocked[0].get("evidence") or {}).get("capacity_relief", {}).get("status"),
                "no_eligible_unit")
            self.assertFalse(any(event.get("kind") == "recruit" for event in events(rows)))

    def test_scout_replacement_retains_live_id(self):
        drop = {
            "reserve_gold": 0,
            "recruits": [{"def_id": "Skeleton", "count": 1, "role": "army"}],
            "scouts": [], "villages": [{"col": 2, "row": 4}], "rally": None, "holds": [],
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint = _checkpoint(root, STACK3 / "blocked_objective.json")
            _, _, backend, prompt_log = prepare(
                root, "blocked_objective.json",
                [policy(value=SCOUT_POLICY), policy(value=drop), {"kind": "finish_turn"}])
            backend.write_text(
                "import json,re,sys\nfrom pathlib import Path\n"
                f"lp=Path({str(prompt_log)!r})\n"
                f"initial={policy(value=SCOUT_POLICY)!r}\n"
                f"drop={policy(value=drop)!r}\n"
                "p=sys.stdin.read()\n"
                "lp.open('a').write(json.dumps({'prompt':p})+'\\n')\n"
                "n=sum(1 for line in lp.read_text().splitlines() if line.strip())\n"
                "if n==1:\n"
                "    resp=initial\n"
                "elif n==2:\n"
                "    resp=drop\n"
                "else:\n"
                "    m=re.search(r'\"effective_scout_ids\":\\[([0-9, ]*)\\]', p)\n"
                "    ids=[int(x) for x in m.group(1).split(',') if x.strip()] if m else []\n"
                "    if not ids:\n"
                "        resp={'kind':'finish_turn'}\n"
                "    else:\n"
                "        resp={'kind':'set_policy','policy':{"
                "'reserve_gold':0,'recruits':[],"
                "'scouts':ids,'villages':[{'col':2,'row':4}],'rally':None,'holds':[]}}\n"
                "print(json.dumps({'text':json.dumps(resp)}))\n",
                encoding="utf-8")
            log = root / "scout.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            self.assertTrue(any(event.get("kind") == "recruit" for event in events(rows)))
            compact = "\n".join(json.loads(line)["prompt"]
                                for line in prompt_log.read_text().splitlines()
                                if line.strip()).replace(" ", "")
            self.assertRegex(compact, r'"effective_scout_ids":\[[0-9]+')
            repairs = [row for row in rows if row.get("type") == "strategy_response_repair"]
            self.assertTrue(repairs)
            installed = [row for row in rows if row.get("type") == "policy_installed"]
            self.assertTrue(installed[-1]["policy"]["scouts"])

    def test_corrupt_finish_cannot_score_travel_success(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint = _checkpoint(root, FIXTURES / "safe_travel.json")
            _, _, backend, _ = prepare(
                root, "blocked_objective.json",
                [{"kind": "finish_turn"}])
            log = root / "corrupt.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            self.assertFalse(any(event.get("kind") == "recruit" for event in events(rows)))
            self.assertFalse(any(
                row.get("source") == "routine"
                and (row.get("orders") or [{}])[0].get("action") == "Move"
                for row in forwarded(rows)))


if __name__ == "__main__":
    unittest.main()
