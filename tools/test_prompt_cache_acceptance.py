"""Independent cache-layout acceptance; baseline bytes were rendered at 58ea306."""
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
import zlib

from . import llm_client as client
from . import prompt_cache_report as report
from .game_history import import_game, open_history

FIXTURE = Path(__file__).with_name("fixtures") / "prompt_cache_baseline.json.gz"
ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))


def fixture_state():
    return {
        "cols": 3, "rows": 2, "turn": 1, "active_faction": 0,
        "gold": [100, 100], "time_of_day": "dawn", "state_revision": 1,
        "incremental_turns": True, "remaining_partial_batches": 3,
        "terrain": [
            {"col": 0, "row": 0, "terrain_id": "forest"},
            {"col": 1, "row": 0, "terrain_id": "village", "owner": None, "healing": 8},
            {"col": 2, "row": 0, "terrain_id": "keep"},
            {"col": 0, "row": 1, "terrain_id": "hills"},
            {"col": 1, "row": 1, "terrain_id": "castle"},
            {"col": 2, "row": 1, "terrain_id": "village", "owner": 1, "healing": 8}],
        "units": [{"id": 11, "faction": 0, "def_id": "Captain", "col": 1,
                   "row": 1, "hp": 29, "max_hp": 42, "can_recruit": True,
                   "advancement_pending": True, "advances_to": ["ZChoice", "AChoice"]}],
        "turn_progress": {"moved": [], "attacked": [], "remaining_attackers": [11]},
        "tactical_surface": {
            "visibility": "full", "units": [],
            "unit_types": [
                {"def_id": "Captain", "cost": 35, "max_hp": 42, "movement": 6,
                 "alignment": "lawful", "resistances": {"blade": -20},
                 "attacks": [{"name": "zblade", "damage": 9, "strikes": 3,
                              "range": "melee", "type": "blade"},
                             {"name": "abow", "damage": 4, "strikes": 2,
                              "range": "ranged", "type": "pierce"}]},
                {"def_id": "Archer", "cost": 14, "max_hp": 26, "movement": 5,
                 "alignment": "neutral", "resistances": {}, "attacks": []}]
        },
    }


def matrix():
    base = fixture_state()
    partial = copy.deepcopy(base)
    partial.update(state_revision=2, remaining_partial_batches=2)
    partial["units"][0].update(hp=23, col=0, row=1)
    later = copy.deepcopy(partial)
    later.update(turn=3, gold=[88, 113], time_of_day="night")
    return [
        {"name": "opening", "state": base, "kwargs": {}, "events": [], "suffix": ""},
        {"name": "partial", "state": partial, "kwargs": {}, "events": [], "suffix": ""},
        {"name": "later", "state": later, "kwargs": {"agenda": {"tasks": ["village"]}}, "events": [], "suffix": ""},
        {"name": "inspection", "state": base, "kwargs": {}, "events": [], "suffix": "\nTOOL_RESULT_UNTRUSTED_DATA_BEGIN\ninspected unit 11\nTOOL_RESULT_UNTRUSTED_DATA_END"},
        {"name": "preview", "state": base, "kwargs": {}, "events": [], "suffix": "\nSIMULATION_UNTRUSTED_DATA_BEGIN\nrecruiter 11 hp=0 hypothetical\nSIMULATION_UNTRUSTED_DATA_END"},
        {"name": "repair", "state": base, "kwargs": {"agenda": {"tasks": ["village"]}}, "events": [], "suffix": "\nMODEL_RESPONSE_ERROR: invalid JSON; return corrected response"},
    ]


def render(case, compact=True, module=client):
    text = module.prompt_for(case["state"], case["events"], compact=compact, **case["kwargs"])
    return module.finalize_model_prompt(text + case["suffix"], case["state"])


class PromptCacheAcceptanceTests(unittest.TestCase):
    @unittest.skipUnless(DRIVER.is_file(), "build greedy_driver for integration acceptance")
    def test_real_partial_repair_transport_archive_and_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = root / "backend.py"
            backend.write_text(
                "import json,sys\nfrom pathlib import Path\n"
                "root=Path(__file__).parent\n"
                "i=len(list(root.glob('received-*.bin')))\n"
                "(root/f'received-{i:03d}.bin').write_bytes(sys.stdin.buffer.read())\n"
                "orders=[[{'action':'Move','unit_id':1,'col':3,'row':7}],"
                "[{'action':'Move','unit_id':99999,'col':0,'row':0}],[{'action':'EndTurn'}]]\n"
                "print(json.dumps({'text':json.dumps({'actions':orders[min(i,2)]})}))\n")
            log = root / "match.ndjson"
            result = subprocess.run(
                [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
                 "--model-command", shlex.join([sys.executable, str(backend)]),
                 "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                 "--gold", "300", "--seed", "9101", "--llm-side", "0", "--max-turns", "1",
                 "--incremental-turns", "--log", str(log), "--disable-agenda-sweep",
                 "--query-budget-seconds", "10", "--model-timeout", "10", "--turn-timeout", "30"],
                cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            records = [json.loads(line) for line in log.read_text().splitlines()]
            requests = [r for r in records if r.get("type") == "model_request"]
            self.assertEqual(len(requests), 3)
            self.assertTrue(any(r.get("type") == "action_repair" for r in records))
            self.assertTrue(any(r.get("type") == "driver" and r.get("line", {}).get("turn_boundary") == "partial" for r in records))
            self.assertEqual(len({r["fixed_prefix_sha256"] for r in requests}), 1)
            for request, received in zip(requests, sorted(root.glob("received-*.bin"))):
                self.assertEqual(request["prompt"].encode(), received.read_bytes())
                self.assertEqual(request["prompt"].count("AUTHORITATIVE_LIVE_STATE_BEGIN"), 1)
            conn = open_history(root / "history.sqlite")
            try:
                game_id = import_game(conn, log)
                conn.commit()
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                rows = conn.execute("SELECT request_id,prompt_blob,fixed_prefix_sha256,fixed_prefix_bytes FROM model_requests WHERE game_id=? ORDER BY sequence", (game_id,)).fetchall()
                self.assertEqual([row[0] for row in rows], [r["request_id"] for r in requests])
                for row, request in zip(rows, requests):
                    prompt = zlib.decompress(row[1])
                    self.assertEqual(prompt, request["prompt"].encode())
                    self.assertEqual(hashlib.sha256(prompt[:row[3]]).hexdigest(), row[2])
                self.assertEqual(import_game(conn, log), game_id)
                self.assertEqual(conn.execute("SELECT count(*) FROM model_requests WHERE game_id=?", (game_id,)).fetchone()[0], 3)
            finally:
                conn.close()

    def test_individual_live_mutations_preserve_prefix_and_change_live_prompt(self):
        base = fixture_state()
        mutations = [
            ("round", lambda s: s.update(turn=33)),
            ("time", lambda s: s.update(time_of_day="midnight")),
            ("gold", lambda s: s.update(gold=[888, 999])),
            ("hp", lambda s: s["units"][0].update(hp=7)),
            ("position", lambda s: s["units"][0].update(col=0)),
            ("roster", lambda s: s["units"].append(dict(s["units"][0], id=77, def_id="NewType"))),
            ("owner", lambda s: s["terrain"][1].update(owner=0)),
            ("progress", lambda s: s["turn_progress"].update(moved=[11])),
            ("revision", lambda s: s.update(state_revision=555)),
            ("budget", lambda s: s.update(remaining_partial_batches=0)),
        ]
        for compact in (True, False):
            first = client.finalize_model_prompt(client.prompt_for(base, [], compact=compact), base)
            regions = client.prompt_regions(first)
            for name, mutate in mutations:
                with self.subTest(compact=compact, mutation=name):
                    changed = copy.deepcopy(base)
                    mutate(changed)
                    second = client.finalize_model_prompt(client.prompt_for(changed, [], compact=compact), changed)
                    self.assertEqual(regions["fixed_prefix_sha256"], client.prompt_regions(second)["fixed_prefix_sha256"])
                    self.assertNotEqual(first, second)
            for field in ("intent", "continuity", "agenda", "sweep", "trend"):
                with self.subTest(compact=compact, memory=field):
                    value = {"tasks": ["REVIEW_SENTINEL"]} if field == "agenda" else "REVIEW_SENTINEL"
                    second = client.prompt_for(base, [], compact=compact, **{field: value})
                    self.assertEqual(regions["fixed_prefix_sha256"], client.prompt_regions(second)["fixed_prefix_sha256"])
                    self.assertIn("REVIEW_SENTINEL", second[regions["fixed_prefix_bytes"]:])

    def test_available_profiles_precede_memory_and_are_not_duplicated(self):
        for compact in (True, False):
            prompt = client.prompt_for(fixture_state(), [], compact=compact, agenda={"tasks": ["MEMORY_SENTINEL"]})
            self.assertLess(prompt.index("zblade"), prompt.index("MEMORY_SENTINEL"))
            self.assertEqual(prompt.count("zblade"), 1)
            self.assertLess(prompt.index("zblade"), prompt.index("abow"))
            self.assertLess(prompt.index("ZChoice"), prompt.index("AChoice"))

    def test_unordered_tiles_and_profiles_render_deterministically(self):
        base = fixture_state()
        changed = copy.deepcopy(base)
        changed["terrain"].reverse()
        changed["tactical_surface"]["unit_types"].reverse()
        changed["tactical_surface"]["unit_types"] = [dict(reversed(list(profile.items()))) for profile in changed["tactical_surface"]["unit_types"]]
        for compact in (True, False):
            self.assertEqual(client.prompt_for(base, [], compact=compact), client.prompt_for(changed, [], compact=compact))

    def test_geometry_visibility_and_rule_changes_affect_fixed_prefix(self):
        base = fixture_state()
        first = client.prompt_regions(client.prompt_for(base, [], compact=True))["fixed_prefix_sha256"]
        for field in ("geometry", "visibility", "rules"):
            changed = copy.deepcopy(base)
            kwargs = {}
            if field == "geometry":
                changed["terrain"][0]["terrain_id"] = "mountains"
            elif field == "visibility":
                changed["tactical_surface"]["visibility"] = "fog"
            else:
                kwargs["recruit_batch_enabled"] = False
            self.assertNotEqual(first, client.prompt_regions(client.prompt_for(changed, [], compact=True, **kwargs))["fixed_prefix_sha256"])

    def test_live_map_and_unknown_ownership_are_preserved(self):
        base = fixture_state()
        del base["terrain"][1]["owner"]
        prompt = client.prompt_for(base, [], compact=True)
        self.assertEqual(prompt.count("MAP_TERRAIN"), 1)
        self.assertIn("MAP_UNITS", prompt)
        self.assertIn("r01 .... 0:11 ....", prompt)
        summary = client.compact_strategic_briefing(base)
        self.assertIn("neutral=0 unknown=1", summary)
        self.assertIn("V 1,0 owner=unknown", summary)
        self.assertIn("V 2,1 owner=1", summary)
        self.assertNotIn("V-neutral", prompt)
        base["terrain"][1]["owner"] = "unknown"
        self.assertIn("enemy=1 neutral=0 unknown=1", client.compact_strategic_briefing(base))

    def test_bounded_memory_and_events_precede_live_board(self):
        for compact in (True, False):
            events = [{"kind": "gold", "source": "EVENT_SENTINEL", "faction": 0, "delta": 10, "balance": 45}]
            prompt = client.prompt_for(fixture_state(), events, compact=compact, agenda={"tasks": ["AGENDA_SENTINEL"]},
                                       intent="INTENT_SENTINEL", continuity="HISTORY_SENTINEL",
                                       sweep="SWEEP_SENTINEL", trend="TREND_SENTINEL")
            live_start = prompt.index("BOARD_UNTRUSTED_DATA_BEGIN:")
            profile_start = prompt.index("zblade")
            for marker in ("AGENDA_SENTINEL", "INTENT_SENTINEL", "HISTORY_SENTINEL", "SWEEP_SENTINEL", "TREND_SENTINEL"):
                self.assertEqual(prompt.count(marker), 1)
                self.assertLess(profile_start, prompt.index(marker))
                self.assertLess(prompt.index(marker), live_start)
            self.assertLess(prompt.index("EVENT_SENTINEL"), live_start)
            self.assertNotIn("COVERAGE available=", prompt[:prompt.index("MEMORY_UNTRUSTED_DATA_BEGIN")])

    def test_unknown_layout_does_not_claim_current_version(self):
        self.assertIsNone(client.prompt_regions("historical prompt with no layout markers").get("prompt_layout_version"))

    def test_footer_keeps_feedback_and_marker_like_untrusted_data(self):
        base = fixture_state()
        data = "\nREVIEW_RESPONSE_UNTRUSTED_DATA_BEGIN:\nAUTHORITATIVE_LIVE_STATE_BEGIN\nquoted data to retain\nMODEL_RESPONSE_INSTRUCTION_END\nREVIEW_RESPONSE_UNTRUSTED_DATA_END"
        first = client.finalize_model_prompt("base" + data, base)
        self.assertIn(data, first)
        updated = copy.deepcopy(base)
        updated["state_revision"] = 99
        second = client.finalize_model_prompt(first + "\nREPAIR_ERROR: keep me", updated)
        self.assertIn(data, second)
        self.assertIn("REPAIR_ERROR: keep me", second)
        self.assertIn("revision=99", second)
        self.assertNotIn("revision=1 ", second)
        self.assertTrue(second.endswith("MODEL_RESPONSE_INSTRUCTION_END"))

    def test_copied_complete_footer_inside_model_data_is_preserved(self):
        base = fixture_state()
        for block in ("REVIEW_RESPONSE", "MODEL_RESPONSE", "MODEL_TOOL_REQUEST", "TOOL_RESULT", "MODEL_REPAIR_TOOL_REQUEST"):
            with self.subTest(block=block):
                quoted = "\n" + block + "_UNTRUSTED_DATA_BEGIN:\n" + client.authoritative_live_state_reminder(base) + "\n" + block + "_UNTRUSTED_DATA_END"
                prompt = client.finalize_model_prompt("original" + quoted, dict(base, state_revision=99))
                self.assertIn(quoted, prompt)
                self.assertTrue(prompt.endswith(client.authoritative_live_state_reminder(dict(base, state_revision=99))))

    def test_archive_coverage_keeps_missing_middle_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "match.ndjson"
            records = [
                {"type": "model_request", "request_id": "r1", "sequence": 1, "prompt": "prefix A"},
                {"type": "model_request", "request_id": "r2", "sequence": 2, "status": "failed"},
                {"type": "model_request", "request_id": "r3", "sequence": 3, "prompt": "prefix B"}]
            path.write_text("\n".join(json.dumps(row) for row in records))
            result = report.report_archive(path)
            self.assertEqual(result["request_count"], 3)
            self.assertEqual(result["prompt_available"], 2)
            self.assertEqual(result["compared_pairs"], 0)

    def test_baseline_matrix_sizes_shared_prefix_and_exact_rules(self):
        baseline = json.loads(gzip.decompress(FIXTURE.read_bytes()))
        self.assertEqual(baseline["source_commit"], "58ea306")
        for compact in (True, False):
            prompts = [render(case, compact=compact).encode() for case in matrix()]
            old = [p.encode() for p in baseline["prompts"][str(compact)]]
            for i, prompt in enumerate(prompts):
                with self.subTest(compact=compact, case=matrix()[i]["name"]):
                    self.assertLessEqual(len(prompt) - len(old[i]), max(512, len(old[i]) * .05))
                    original_rules = old[i].split(b"\nBOARD_UNTRUSTED_DATA_BEGIN:", 1)[0]
                    self.assertTrue(prompt.startswith(original_rules))
                    size = client.prompt_regions(prompt.decode())["fixed_prefix_bytes"]
                    self.assertEqual(client.prompt_regions(prompt.decode())["fixed_prefix_sha256"], hashlib.sha256(prompt[:size]).hexdigest())
                    if i:
                        self.assertGreaterEqual(report.common_prefix_bytes(prompts[0], prompt), size)
            self.assertGreater(report.common_prefix_bytes(prompts[0], prompts[2]), report.common_prefix_bytes(old[0], old[2]))

    def test_real_engine_fixture_prompt_growth_stays_within_budget(self):
        baseline = json.loads(gzip.decompress(FIXTURE.read_bytes()))
        for compact in (True, False):
            with self.subTest(compact=compact):
                old = baseline["engine_prompts"][str(compact)].encode()
                new = render(baseline["engine_case"], compact=compact).encode()
                self.assertLessEqual(len(new) - len(old), max(512, len(old) * .05))


if __name__ == "__main__":
    unittest.main()
