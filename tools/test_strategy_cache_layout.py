"""Tests for strategy prompt cache layout (strategy_layout_v1) and telemetry.

Validates the invariant prefix containing contract and static geometry,
dynamic state suffix containing villages and live units, honest region
measurements, and SQLite/report integration.
"""
import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest

from pathlib import Path

from .game_history import open_history
from .game_token_budget import measured_game_budget
from .llm_client import (
    finalize_strategy_prompt,
    game_budget_context,
    prompt_regions,
)
from .model_usage import ModelCall
from .prompt_cache_report import report_sqlite
from .routine_policy import (
    render_policy_brief,
    render_exception_brief,
    render_strategy_fixed_prefix,
    RoutineException,
)
from .strategy_decision import (
    build_decision_packet,
    render_decision_brief,
)


def _sample_state():
    return {
        "scenario": "test_scenario",
        "cols": 4,
        "rows": 4,
        "active_faction": 0,
        "state_revision": 10,
        "turn": 2,
        "time_of_day": "first_watch",
        "gold": [100, 80],
        "terrain": [
            {"col": 0, "row": 0, "terrain_id": "flat"},
            {"col": 1, "row": 0, "terrain_id": "village", "owner": 0},
            {"col": 2, "row": 0, "terrain_id": "hills"},
            {"col": 3, "row": 0, "terrain_id": "village", "owner": 1},
            {"col": 0, "row": 1, "terrain_id": "forest"},
            {"col": 1, "row": 1, "terrain_id": "castle"},
            {"col": 2, "row": 1, "terrain_id": "mountains"},
            {"col": 3, "row": 1, "terrain_id": "flat"},
        ],
        "units": [
            {"id": 1, "faction": 0, "def_id": "Leader", "col": 1, "row": 1, "hp": 30,
             "max_hp": 30, "moved": False, "attacked": False, "movement": 5, "can_recruit": True},
            {"id": 2, "faction": 0, "def_id": "Scout", "col": 1, "row": 0, "hp": 18,
             "max_hp": 18, "moved": False, "attacked": False, "movement": 6, "can_recruit": False},
            {"id": 5, "faction": 1, "def_id": "Enemy", "col": 3, "row": 0, "hp": 20,
             "max_hp": 20, "moved": False, "attacked": False, "movement": 5, "can_recruit": False},
        ],
    }


class StrategyCacheLayoutTests(unittest.TestCase):
    def setUp(self):
        self.state = _sample_state()
        self.defs = ("Archer", "Fighter", "Scout")

    def test_prefix_matches_across_different_packet_types(self):
        """Initial policy, contact, and exhausted packets share identical fixed prefix."""
        # 1. Initial policy brief
        init_packet = build_decision_packet("initial", {}, revision=10, decision_id="dec-init")
        init_brief = render_policy_brief(0, self.defs, state=self.state)
        init_prompt = finalize_strategy_prompt(init_brief, self.state, packet=init_packet)
        init_regions = prompt_regions(init_prompt)

        # 2. Contact decision brief
        contact_evidence = {
            "stage": "current_state",
            "trigger": "exposure",
            "friendly_unit_ids": [2],
            "enemy_unit_ids": [5],
            "actor_ids": [2],
            "eligible_actor_count": 1,
            "options": [
                {"option_id": "u2-move-1", "category": "safe_alternative",
                 "actions": [{"action": "Move", "unit_id": 2, "col": 0, "row": 0}]}
            ],
        }
        contact_packet = build_decision_packet("contact", contact_evidence, revision=10, decision_id="dec-contact")
        contact_brief = render_decision_brief(contact_packet, state=self.state, recruitable_defs=self.defs)
        contact_prompt = finalize_strategy_prompt(contact_brief, self.state, packet=contact_packet)
        contact_regions = prompt_regions(contact_prompt)

        # 3. Exhausted contact decision brief
        exhausted_evidence = {
            "stage": "current_state",
            "trigger": "exposure",
            "friendly_unit_ids": [2],
            "enemy_unit_ids": [5],
            "actor_ids": [],
            "eligible_actor_count": 0,
            "options": [],
            "options_empty_reason": "exhausted_contact_no_automatic_rescue_menu",
            "contact_actionability": "exhausted",
            "contact_state_key": "k" * 64,
        }
        exhausted_packet = build_decision_packet("contact", exhausted_evidence, revision=10, decision_id="dec-exh")
        exhausted_brief = render_decision_brief(exhausted_packet, state=self.state, recruitable_defs=self.defs)
        exhausted_prompt = finalize_strategy_prompt(exhausted_brief, self.state, packet=exhausted_packet)
        exhausted_regions = prompt_regions(exhausted_prompt)

        # Assert layout and prefix telemetry
        for regions in (init_regions, contact_regions, exhausted_regions):
            self.assertEqual(regions["prompt_layout_version"], "strategy_layout_v1")
            self.assertEqual(regions["fixed_prefix_bytes"], init_regions["fixed_prefix_bytes"])
            self.assertEqual(regions["fixed_prefix_sha256"], init_regions["fixed_prefix_sha256"])
            self.assertIsNone(regions["preamble_bytes"])
            self.assertIsNone(regions["turn_card_bytes"])
            self.assertIsNone(regions["tool_result_bytes"])

        # Delivered prompts differ only after the fixed prefix
        prefix_bytes = init_regions["fixed_prefix_bytes"]
        self.assertEqual(init_prompt.encode("utf-8")[:prefix_bytes], contact_prompt.encode("utf-8")[:prefix_bytes])
        self.assertEqual(init_prompt.encode("utf-8")[:prefix_bytes], exhausted_prompt.encode("utf-8")[:prefix_bytes])
        self.assertNotEqual(init_prompt, contact_prompt)
        self.assertNotEqual(contact_prompt, exhausted_prompt)

    def test_live_mutations_preserve_fixed_prefix(self):
        """Mutations to unit HP, gold, turn, village ownership, and budget only change dynamic suffix."""
        base_packet = build_decision_packet("initial", {}, revision=10, decision_id="dec-base")
        base_brief = render_policy_brief(0, self.defs, state=self.state)
        base_prompt = finalize_strategy_prompt(base_brief, self.state, packet=base_packet)
        base_regions = prompt_regions(base_prompt)
        prefix_sha = base_regions["fixed_prefix_sha256"]
        prefix_bytes = base_regions["fixed_prefix_bytes"]

        # Mutate live state
        mutated_state = copy.deepcopy(self.state)
        mutated_state["turn"] = 5
        mutated_state["gold"] = [250, 10]
        mutated_state["state_revision"] = 25
        # Capture village (tile index 1): owner changes from 0 to 1
        mutated_state["terrain"][1]["owner"] = 1
        # Damage unit
        mutated_state["units"][0]["hp"] = 12

        mutated_brief = render_policy_brief(0, self.defs, state=mutated_state)
        # Add volatile game budget context
        budget_line = game_budget_context(None, {"cumulative_game_total_tokens": 150000})
        mutated_brief_with_budget = mutated_brief + "\n" + budget_line
        mutated_prompt = finalize_strategy_prompt(
            mutated_brief_with_budget, mutated_state, packet=base_packet)
        mutated_regions = prompt_regions(mutated_prompt)

        self.assertEqual(mutated_regions["fixed_prefix_sha256"], prefix_sha)
        self.assertEqual(mutated_regions["fixed_prefix_bytes"], prefix_bytes)
        self.assertEqual(base_prompt.encode("utf-8")[:prefix_bytes], mutated_prompt.encode("utf-8")[:prefix_bytes])
        # Live mutations are visible in the dynamic suffix
        self.assertIn('"hp":12', mutated_prompt[prefix_bytes:])
        self.assertIn('"gold":[250,10]', mutated_prompt[prefix_bytes:])
        self.assertIn("GAME_BUDGET_CONTEXT_BEGIN", mutated_prompt[prefix_bytes:])

    def test_geometry_or_scenario_or_defs_change_fixed_prefix(self):
        """Changes to static map, scenario, or recruitable defs change the prefix hash."""
        base_prefix_sha = prompt_regions(render_strategy_fixed_prefix(self.state, self.defs))["fixed_prefix_sha256"]

        # 1. Change terrain tile type (flat -> mountains)
        mod_terrain = copy.deepcopy(self.state)
        mod_terrain["terrain"][0]["terrain_id"] = "mountains"
        sha_terrain = prompt_regions(render_strategy_fixed_prefix(mod_terrain, self.defs))["fixed_prefix_sha256"]
        self.assertNotEqual(base_prefix_sha, sha_terrain)

        # 2. Change cols / dimensions
        mod_cols = copy.deepcopy(self.state)
        mod_cols["cols"] = 5
        sha_cols = prompt_regions(render_strategy_fixed_prefix(mod_cols, self.defs))["fixed_prefix_sha256"]
        self.assertNotEqual(base_prefix_sha, sha_cols)

        # 3. Change scenario name
        mod_scen = copy.deepcopy(self.state)
        mod_scen["scenario"] = "different_scenario"
        sha_scen = prompt_regions(render_strategy_fixed_prefix(mod_scen, self.defs))["fixed_prefix_sha256"]
        self.assertNotEqual(base_prefix_sha, sha_scen)

        # 4. Change recruitable definitions
        sha_defs = prompt_regions(render_strategy_fixed_prefix(self.state, ("Heavy Infantry", "Mage")))["fixed_prefix_sha256"]
        self.assertNotEqual(base_prefix_sha, sha_defs)

    def test_unordered_terrain_tiles_render_deterministically(self):
        """Terrain tiles render in deterministic col,row order regardless of state list order."""
        reversed_state = copy.deepcopy(self.state)
        reversed_state["terrain"].reverse()
        base_prefix = render_strategy_fixed_prefix(self.state, self.defs)
        rev_prefix = render_strategy_fixed_prefix(reversed_state, self.defs)
        self.assertEqual(base_prefix, rev_prefix)

    def test_unicode_and_exact_byte_slice_equivalence(self):
        """Unicode characters produce exact UTF-8 byte count matching prompt prefix slice."""
        unicode_defs = ("🏹Elvish Archer", "⚔️Fighter")
        prefix = render_strategy_fixed_prefix(self.state, unicode_defs)
        prompt = prefix + "\nSTRATEGY_CONTEXT_UNTRUSTED_DATA_BEGIN\n{}\nSTRATEGY_CONTEXT_UNTRUSTED_DATA_END\n"
        regions = prompt_regions(prompt)
        size = regions["fixed_prefix_bytes"]
        encoded = prompt.encode("utf-8")
        self.assertEqual(hashlib.sha256(encoded[:size]).hexdigest(), regions["fixed_prefix_sha256"])

    def test_repeated_finalization_and_quoted_markers(self):
        """Repeated finalization replaces footer and ignores quoted marker text."""
        packet = build_decision_packet("initial", {}, revision=10, decision_id="dec-1")
        brief = render_policy_brief(0, self.defs, state=self.state)
        # Add quoted marker inside untrusted comment
        untrusted = '\nUNTRUSTED_DATA_BEGIN\nquoted STRATEGY_LIVE_STATE_BEGIN\nSTRATEGY_RESPONSE_INSTRUCTION_END\nUNTRUSTED_DATA_END'
        first = finalize_strategy_prompt(brief + untrusted, self.state, packet=packet)
        first_regions = prompt_regions(first)

        # Finalize again with revised state
        revised_state = copy.deepcopy(self.state)
        revised_state["state_revision"] = 11
        second = finalize_strategy_prompt(first, revised_state, packet=packet)
        second_regions = prompt_regions(second)

        self.assertEqual(first_regions["fixed_prefix_sha256"], second_regions["fixed_prefix_sha256"])
        self.assertEqual(first_regions["fixed_prefix_bytes"], second_regions["fixed_prefix_bytes"])
        self.assertIn('"revision":11', second)
        self.assertEqual(second.count("STRATEGY_RESPONSE_INSTRUCTION_BEGIN"), 1)

    def test_game_history_import_and_prompt_cache_report(self):
        """SQLite import populates strategy_layout_v1 and prompt_cache_report surfaces it."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            conn = open_history(tmp.name)
            game_id = "strat-test-game"
            conn.execute(
                "INSERT INTO games(game_id,status,config_json,provenance_json,schema_version,artifact_path) VALUES(?,'completed','{}','{}',5,'/tmp')",
                (game_id,)
            )
            # Insert request and call with strategy_layout_v1
            prefix = render_strategy_fixed_prefix(self.state, self.defs)
            prefix_bytes = len(prefix.encode("utf-8"))
            prefix_sha = hashlib.sha256(prefix.encode("utf-8")).hexdigest()
            prompt = prefix + "\nSTRATEGY_CONTEXT_UNTRUSTED_DATA_BEGIN\n{}\nSTRATEGY_CONTEXT_UNTRUSTED_DATA_END\n"

            conn.execute(
                """INSERT INTO model_requests(
                    request_id, game_id, sequence, status, prompt_bytes, prompt_hash,
                    prompt_layout_version, fixed_prefix_sha256, fixed_prefix_bytes, record_hash
                ) VALUES (?, ?, 1, 'completed', ?, ?, 'strategy_layout_v1', ?, ?, ?)""",
                ("req-1", game_id, len(prompt.encode("utf-8")), "hash1", prefix_sha, prefix_bytes, "rec-hash-1")
            )
            conn.execute(
                """INSERT INTO model_calls(
                    call_id, game_id, request_id, status, requested_model,
                    prompt_layout_version, requested_affinity, record_hash
                ) VALUES (?, ?, ?, 'completed', 'accounts/fireworks/models/glm-5p3-flash', 'strategy_layout_v1', 'aff-1', ?)""",
                ("call-1", game_id, "req-1", "call-hash-1")
            )
            conn.commit()
            conn.close()

            # Run prompt_cache_report
            report = report_sqlite(tmp.name, game_id, layout="strategy_layout_v1")
            self.assertEqual(report["game_id"], game_id)
            self.assertEqual(len(report["calls"]), 1)
            self.assertEqual(report["calls"][0]["layout"], "strategy_layout_v1")
            groups = report["cache_usage"]["groups"]
            self.assertTrue(any(g["layout"] == "strategy_layout_v1" for g in groups))

    def test_cache_accounting_fake_transport(self):
        """Acceptance check for cache accounting: hit, zero, missing, affinity, ceiling."""
        with tempfile.NamedTemporaryFile(suffix=".ndjson") as tmp:
            sidecar = Path(tmp.name)
            game_id = "game-cache-acc"
            # 1. Measured hit: input=1000, cached=800, output=100, total=1100
            call1 = {
                "game_id": game_id, "call_id": "c1", "request_id": "r1",
                "call_role": "player", "transport": "fireworks_chat_completions",
                "requested_affinity": "game-session-1",
                "prompt_layout_version": "strategy_layout_v1",
                "input_tokens": 1000, "cached_input_tokens": 800,
                "output_tokens": 100, "total_tokens": 1100,
                "cache_write_input_tokens": None,  # preserve cache-write unknowns
                "status": "completed",
            }
            # 2. Measured zero: input=1000, cached=0, output=50, total=1050
            call2 = {
                "game_id": game_id, "call_id": "c2", "request_id": "r2",
                "call_role": "player", "transport": "fireworks_chat_completions",
                "requested_affinity": "game-session-1",  # stable affinity
                "prompt_layout_version": "strategy_layout_v1",
                "input_tokens": 1000, "cached_input_tokens": 0,
                "output_tokens": 50, "total_tokens": 1050,
                "cache_write_input_tokens": None,
                "status": "completed",
            }
            # 3. Missing cached field: input=500, cached=None, output=20, total=520
            call3 = {
                "game_id": game_id, "call_id": "c3", "request_id": "r3",
                "call_role": "player", "transport": "fireworks_chat_completions",
                "requested_affinity": "game-session-1",
                "prompt_layout_version": "strategy_layout_v1",
                "input_tokens": 500, "cached_input_tokens": None,
                "output_tokens": 20, "total_tokens": 520,
                "cache_write_input_tokens": None,
                "status": "completed",
            }
            # 4. Changed game identity call
            call_other = {
                "game_id": "other-game", "call_id": "c_other", "request_id": "r_other",
                "call_role": "player", "transport": "fireworks_chat_completions",
                "requested_affinity": "other-session",
                "prompt_layout_version": "strategy_layout_v1",
                "input_tokens": 500, "cached_input_tokens": 200,
                "output_tokens": 50, "total_tokens": 550,
                "status": "completed",
            }

            with open(sidecar, "w") as f:
                for c in (call1, call2, call3, call_other):
                    f.write(json.dumps(c) + "\n")

            # Check measured_game_budget
            budget = measured_game_budget(sidecar, game_id, {"r1", "r2", "r3"})
            # Total tokens: 1100 + 1050 + 520 = 2670.
            # Cached tokens (800) did NOT reduce the 2670 total ceiling spend!
            self.assertEqual(budget["cumulative_game_total_tokens"], 2670)
            self.assertTrue(budget["game_token_limit_enforced"])


if __name__ == "__main__":
    unittest.main()
