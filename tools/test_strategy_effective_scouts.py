"""Real-driver coverage for effective scout IDs and coordinate repair."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from .routine_policy import CANONICAL_COORD_JSON
from .test_strategy_routine_stack3 import (
    DRIVER, ROOT, assert_success, events, launch, policy, prepare, prompts, records,
)


SCOUT_POLICY = {
    "reserve_gold": 0,
    "recruits": [{"def_id": "Ghost", "count": 1, "role": "scout"}],
    "scouts": [],
    "villages": [{"col": 2, "row": 4}],
    "rally": None,
    "holds": [],
}


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before real-driver tests")
class EffectiveScoutAndCoordinateTests(unittest.TestCase):
    def test_invalid_village_array_repair_shows_canonical_object(self):
        bad = {
            "kind": "set_policy",
            "policy": {
                **SCOUT_POLICY,
                "villages": [[2, 4]],
            },
        }
        good = policy(value=SCOUT_POLICY)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, prompt_log = prepare(
                root, "contact.json", [bad, good, {"kind": "finish_turn"}])
            log = root / "coord-repair.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            repairs = [row for row in rows if row.get("type") == "strategy_response_repair"]
            self.assertEqual(len(repairs), 1)
            self.assertIn(CANONICAL_COORD_JSON, str(repairs[0]["error"]))
            self.assertIn("policy.villages[0]", str(repairs[0]["error"]))
            call_prompts = prompts(prompt_log)
            self.assertGreaterEqual(len(call_prompts), 2)
            self.assertIn(CANONICAL_COORD_JSON, call_prompts[1])
            self.assertTrue(any(row.get("type") == "policy_installed" for row in rows))

    def test_recruited_scout_ids_shown_and_explicit_retain_installs(self):
        drop = {
            "reserve_gold": 0,
            "recruits": [{"def_id": "Skeleton", "count": 8, "role": "army"}],
            "scouts": [],
            "villages": [{"col": 2, "row": 4}],
            "rally": {"col": 12, "row": 7},
            "holds": [],
        }
        recruit_policy = {
            "reserve_gold": 0,
            "recruits": [
                {"def_id": "Ghost", "count": 1, "role": "scout"},
                {"def_id": "Skeleton", "count": 8, "role": "army"},
            ],
            "scouts": [],
            "villages": [{"col": 2, "row": 4}],
            "rally": None,
            "holds": [],
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            from .test_strategy_routine_stack2 import prepare as prepare_quiet
            checkpoint, _, backend, prompt_log = prepare_quiet(root, recruit_policy)
            backend.write_text(
                "import json,re,sys\nfrom pathlib import Path\n"
                f"lp=Path({str(prompt_log)!r})\n"
                f"initial={policy(value=recruit_policy)!r}\n"
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
                "'reserve_gold':0,'recruits':[{'def_id':'Skeleton','count':1,'role':'army'}],"
                "'scouts':ids,'villages':[{'col':2,'row':4}],'rally':{'col':12,'row':7},'holds':[]}}\n"
                "print(json.dumps({'text':json.dumps(resp)}))\n",
                encoding="utf-8")
            log = root / "effective-scouts.ndjson"
            result = launch(root, log, checkpoint, backend, turns=1, maximum=64)
            assert_success(self, result, log)
            rows = records(log)
            recruits = [event for event in events(rows) if event.get("kind") == "recruit"]
            self.assertTrue(recruits)
            compact = "\n".join(prompts(prompt_log)).replace(" ", "")
            self.assertRegex(compact, r'"effective_scout_ids":\[[0-9]+')
            repairs = [row for row in rows if row.get("type") == "strategy_response_repair"]
            self.assertTrue(any("known live prior scout" in str(row.get("error")) for row in repairs),
                            repairs)
            installed = [row for row in rows if row.get("type") == "policy_installed"]
            self.assertGreaterEqual(len(installed), 2)
            self.assertTrue(installed[-1]["policy"]["scouts"])


if __name__ == "__main__":
    unittest.main()
