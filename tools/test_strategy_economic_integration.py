"""Real-driver acceptance for the economic summary line (GLM decision support, Stack 2).

Every expected number is derived from the driver's own `state` record logged just
before each model request, never hardcoded, and every assertion is unconditional.
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from .test_strategy_routine_stack2 import DRIVER, launch as launch_quiet, prepare as prepare_quiet
from .test_strategy_stack3_integration import (
    choose, launch as launch_contact, policy, prepare as prepare_contact, records,
)

ECONOMIC_LINE = re.compile(
    r"(?P<gold>\d+) gold \((?P<unreserved>\d+) unreserved\); "
    r"units (?P<friendly>\d+) vs (?P<enemy>\d+); "
    r"villages (?P<fv>\d+) vs (?P<ev>\d+)(?: \((?P<neutral>\d+) unowned\))?; "
    r"(?P<rest>[^\n]*)")

SMALL_QUEUE = {"reserve_gold": 0, "recruits": [{"def_id": "Skeleton", "count": 1, "role": "army"}],
               "scouts": [], "villages": [], "rally": None, "holds": []}


def delivered_prompts(prompt_log: Path) -> list[str]:
    return [json.loads(line)["prompt"] for line in prompt_log.read_text().splitlines() if line.strip()]


def economic_line(prompt: str) -> re.Match:
    match = ECONOMIC_LINE.search(prompt)
    if match is None:
        raise AssertionError("delivered prompt carries no economic summary line")
    return match


def states_at_requests(rows: list[dict]) -> list[dict]:
    """The latest driver `state` record in force at each model request, in order."""
    latest, snapshots = None, []
    for row in rows:
        line = row.get("line") if row.get("type") == "driver" else None
        if isinstance(line, dict) and line.get("type") == "state":
            latest = line
        if row.get("type") == "model_request":
            if latest is None:
                raise AssertionError("a model request preceded any logged driver state")
            snapshots.append(latest)
    return snapshots


def expected_facts(state: dict, side: int = 0) -> dict[str, int]:
    """Independent recount from the raw engine state (not via the helper under test)."""
    units = [unit for unit in state["units"] if isinstance(unit, dict)]
    villages = [tile for tile in state["terrain"]
                if isinstance(tile, dict) and tile.get("terrain_id") == "village"]
    owners = [tile.get("owner") for tile in villages]
    return {
        "gold": state["gold"][side],
        "friendly": sum(1 for unit in units if unit.get("faction") == side),
        "enemy": sum(1 for unit in units if unit.get("faction") != side),
        "fv": sum(1 for owner in owners if owner == side),
        "ev": sum(1 for owner in owners if isinstance(owner, int) and owner >= 0 and owner != side),
        "neutral": sum(1 for owner in owners if isinstance(owner, int) and owner < 0),
    }


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before real-driver tests; skipped is not acceptance")
class EconomicSummaryIntegrationTests(unittest.TestCase):

    def test_delivered_lines_match_the_logged_driver_state(self):
        """Opening and later prompts report exactly the engine's gold, units and villages."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, policy_file, backend, prompt_log = prepare_quiet(root, SMALL_QUEUE)
            backend.write_text(
                "import json,sys\nfrom pathlib import Path\n"
                f"p=Path({str(policy_file)!r});log=Path({str(prompt_log)!r})\n"
                "prompt=sys.stdin.read()\n"
                "with log.open('a') as f:f.write(json.dumps({'prompt':prompt})+'\\n')\n"
                "n=sum(1 for l in log.read_text().splitlines() if l.strip())\n"
                "r={'kind':'set_policy','policy':json.loads(p.read_text())} if n==1 else {'kind':'finish_turn'}\n"
                "print(json.dumps({'text':json.dumps(r)}))\n")
            log = root / "match.ndjson"
            result = launch_quiet(root, log, checkpoint, policy_file, backend, fixed=False, turns=4)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            rows = records(log)
            prompts = delivered_prompts(prompt_log)
            snapshots = states_at_requests(rows)
            self.assertGreaterEqual(len(prompts), 2, "need the opening and at least one later prompt")
            self.assertEqual(len(prompts), len(snapshots),
                             "every delivered prompt must pair with the state it was built from")

            for index, (prompt, state) in enumerate(zip(prompts, snapshots)):
                line = economic_line(prompt)
                expected = expected_facts(state)
                for key in ("gold", "friendly", "enemy", "fv", "ev"):
                    self.assertEqual(int(line.group(key)), expected[key],
                                     f"prompt {index}: {key} disagrees with the logged engine state")
                self.assertEqual(int(line.group("neutral") or 0), expected["neutral"],
                                 f"prompt {index}: unowned villages disagree with the engine")
            # The opening has every village unowned: none may be reported as enemy-held.
            opening = economic_line(prompts[0])
            self.assertEqual(int(opening.group("ev")), 0)
            self.assertGreater(int(opening.group("neutral") or 0), 0)
            # A later prompt must reflect the committed recruit: its gold is lower.
            self.assertLess(int(economic_line(prompts[-1]).group("gold")),
                            int(opening.group("gold")),
                            "the recruit's cost must show up in a later summary")

    def test_recruitment_review_reports_the_completed_queue(self):
        """The review brief reports the finished queue as COMPLETE, and costs no extra call.

        The review fires only because the finite queue finished with idle gold, so its summary
        must not describe that queue as still active. This reuses the suite's deterministic
        review scenario, where the third delivered prompt is the review.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            one_skeleton = {"reserve_gold": 0,
                            "recruits": [{"def_id": "Skeleton", "count": 1, "role": "army"}],
                            "villages": [], "rally": None, "holds": [], "scouts": []}
            responses = [
                policy("set_policy", one_skeleton),
                choose("u3-attack-1", finish=True),
                policy("set_policy", one_skeleton),
                choose("u3-attack-1", finish=True),
            ]
            checkpoint, _responses, backend, prompt_log = prepare_contact(root, "contact.json", responses)
            log = root / "review.ndjson"
            result = launch_contact(root, log, checkpoint, backend, turns=4)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            rows = records(log)

            reviews = [row for row in rows if row.get("type") == "decision_packet"
                       and row.get("packet", {}).get("reason") == "recruitment_review"]
            self.assertEqual(len(reviews), 1, "the scenario must issue exactly one recruitment review")
            prompts = delivered_prompts(prompt_log)
            self.assertGreaterEqual(len(prompts), 3)
            review_prompt = prompts[2]
            self.assertIn("ECONOMIC RECONSIDERATION", review_prompt,
                          "the third delivered prompt must be the review")
            clause = economic_line(review_prompt).group("rest")
            self.assertIn("queue complete", clause,
                          f"the review exists because the queue finished: {clause!r}")
            self.assertNotIn("queue active", clause)

            # No model dispatch was added merely to refresh the summary: one call per response.
            model_calls = [row for row in rows if row.get("type") == "model"]
            self.assertEqual(len(model_calls), len(responses),
                             "the summary must not add a model dispatch of its own")


if __name__ == "__main__":
    unittest.main()
