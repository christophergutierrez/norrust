import json
import unittest

from .llm_client import (
    compact_batch_preview,
    compact_local_recruiter_danger,
    compact_target_inspection,
    compact_targets_inspection,
    compact_units_inspection,
    compact_tactical_surface,
    compact_unit_inspection,
    build_local_execution_context,
    build_current_turn_readiness,
    compact_local_guardrails,
    enrich_inspected_units,
    enrich_target_inspection,
    game_budget_context,
    memory_provenance,
    prompt_for,
    recover_optional_memory,
    local_execution_projection,
)
from .action_choices import Choice


class ReadableMechanicsTests(unittest.TestCase):
    def test_local_context_requires_usable_inspection_and_keeps_revision(self):
        state = {"state_revision": 7, "turn": 2, "active_faction": 0,
                 "units": [{"id": 4, "faction": 0, "hp": 10,
                            "advancement_pending": False},
                           {"id": 8, "faction": 0, "hp": 12,
                            "advancement_pending": True, "advances_to": ["Mage", "Scout"]}],
                 "terrain": [{"terrain_id": "village", "owner": 0}],
                 "tactical_surface": {"economy": {"gold": 30},
                                      "threats": {"recruiters": []}}}
        unavailable = build_local_execution_context(
            state, {"tool": "inspect_units", "unit_ids": [4]}, "inspect_units",
            [{"unit_id": 4, "available": False}], "INSPECT_UNIT unavailable")
        self.assertIsNone(unavailable)
        context = build_local_execution_context(
            state, {"tool": "inspect_units", "unit_ids": [4]}, "inspect_units",
            [{"unit_id": 4, "origins": [{"current": True}]}],
            "INSPECT_UNITS n=1\nmove_destinations=1\nCHOICES move:4:2,1")
        self.assertEqual(context["revision"], 7)
        self.assertIn("pending_promotions", context["guardrails"])
        self.assertIn("army", context["guardrails"])
        prompt = prompt_for(state, [], decision_mode="focused", local_context=context)
        self.assertIn("CHOICES move:4:2,1", prompt)
        self.assertIn("Mage", prompt)
        self.assertIn("Scout", prompt)

        target_context = build_local_execution_context(
            state, {"tool": "inspect_target", "unit_id": 9}, "inspect_target",
            {"target_id": 9, "available": True},
            "TARGET U9 ATTACK U4 defender_killed=0% attacker_retaliation=2.4HP")
        target_prompt = prompt_for(state, [], decision_mode="focused",
                                   local_context=target_context)
        self.assertIn("attacker_retaliation=2.4HP", target_prompt)

    def test_local_context_carries_provisional_purpose_with_untrusted_framing(self):
        state = {"state_revision": 40, "active_faction": 0, "units": [],
                 "terrain": [], "tactical_surface": {"unit_types": []}}
        with_purpose = build_local_execution_context(
            state, {"tool": "inspect_target", "unit_id": 9, "purpose": "check retreat safety"},
            "inspect_target", {"target_id": 9, "available": True},
            "TARGET U9 hp=20 at=1,1 terrain=flat attacks=none")
        self.assertEqual(with_purpose["operation"]["purpose"], "check retreat safety")
        projection = local_execution_projection(state, with_purpose)
        self.assertIn("LOCAL_OPERATION_PURPOSE_UNTRUSTED_DATA_BEGIN:", projection)
        self.assertIn("check retreat safety", projection)
        self.assertIn("LOCAL_OPERATION_PURPOSE_UNTRUSTED_DATA_END", projection)
        self.assertIn("provisional and unverified statement", projection)
        self.assertIn("not a committed intent, rule, hold, or garrison", projection)
        # Item 5: the local view must state its own scope explicitly.
        self.assertIn("scoped to only the entities and options", projection)

        without_purpose = build_local_execution_context(
            state, {"tool": "inspect_target", "unit_id": 9}, "inspect_target",
            {"target_id": 9, "available": True},
            "TARGET U9 hp=20 at=1,1 terrain=flat attacks=none")
        self.assertIsNone(without_purpose["operation"]["purpose"])
        no_purpose_projection = local_execution_projection(state, without_purpose)
        self.assertIn("none supplied", no_purpose_projection)

    def test_purpose_lifecycle_across_reinspection_repair_and_unavailability(self):
        state = {"state_revision": 50, "active_faction": 0,
                 "units": [{"id": 6, "faction": 0, "hp": 10}],
                 "terrain": [], "tactical_surface": {"unit_types": []}}
        # Reinspection replacement: a fresh inspection with a new (or absent)
        # purpose fully replaces the prior one -- nothing carries over.
        first = build_local_execution_context(
            state, {"tool": "inspect_target", "unit_id": 9, "purpose": "first look"},
            "inspect_target", {"target_id": 9, "available": True}, "TARGET U9 x")
        second = build_local_execution_context(
            state, {"tool": "inspect_target", "unit_id": 9},
            "inspect_target", {"target_id": 9, "available": True}, "TARGET U9 x")
        self.assertEqual(first["operation"]["purpose"], "first look")
        self.assertIsNone(second["operation"]["purpose"])

        # Repair retention: rebuilding the identical operation/request (as the
        # repair path does when it does not re-inspect) keeps the same purpose,
        # since the client simply keeps reusing the existing local_context
        # object rather than rebuilding it -- proven here by rebuilding from
        # the same request and asserting the purpose is unchanged.
        repaired = build_local_execution_context(
            state, {"tool": "inspect_target", "unit_id": 9, "purpose": "first look"},
            "inspect_target", {"target_id": 9, "available": True}, "TARGET U9 x")
        self.assertEqual(repaired["operation"]["purpose"], "first look")

        # Unavailable result: build_local_execution_context returns None, so
        # any previously carried purpose has nothing left to attach to.
        unavailable = build_local_execution_context(
            state, {"tool": "inspect_target", "unit_id": 9, "purpose": "first look"},
            "inspect_target", {"available": False}, "TARGET unavailable")
        self.assertIsNone(unavailable)

        # Accepted-partial invalidation and the side-turn boundary are enforced
        # by run()'s `local_active` revision check in prompt_for: a stale
        # local_context whose revision no longer matches the live state is not
        # rendered at all, so its purpose cannot leak into a new revision.
        prompt = prompt_for(dict(state, state_revision=51), [], decision_mode="focused",
                            local_context=first)
        self.assertNotIn("first look", prompt)
        self.assertNotIn("FOCUSED_LOCAL_CONTEXT_BEGIN", prompt)

        # Rejected draft: the purpose lives only in operation/local_context and
        # is never copied into intent or agenda memory, so a rejected draft
        # (which never updates those) cannot promote it into committed memory.
        self.assertNotIn("purpose", first["objective"])

    def test_local_guardrails_carry_both_next_phase_facts_with_unknown_handling(self):
        both_known = compact_local_guardrails({
            "state_revision": 23, "active_faction": 0, "time_of_day": "Day",
            "tactical_surface": {"next_opponent_time_of_day": "Day",
                                 "next_round_time_of_day": "Dusk",
                                 "threats": {"recruiters": []}},
        })
        self.assertIn('"phase":"Day"', both_known)
        self.assertIn('"next_opponent_phase":"Day"', both_known)
        self.assertIn('"next_round_phase":"Dusk"', both_known)

        # Historical archives predate the two-key surface and only carried
        # the old singular `next_time_of_day`; the round phase falls back to
        # it exactly like `compact_observation` does, while the opponent
        # phase (which never existed under the old key) stays unknown.
        legacy = compact_local_guardrails({
            "state_revision": 23, "active_faction": 0,
            "tactical_surface": {"next_time_of_day": "Night", "threats": {"recruiters": []}},
        })
        self.assertIn('"next_round_phase":"Night"', legacy)
        self.assertIn('"next_opponent_phase":"?"', legacy)

        missing_surface = compact_local_guardrails({"state_revision": 23, "active_faction": 0})
        self.assertIn('"next_opponent_phase":"?"', missing_surface)
        self.assertIn('"next_round_phase":"?"', missing_surface)

    def test_focused_local_prompt_stays_smaller_than_equivalent_full_followup(self):
        # A sizable board: enough units/attacks that the full tactical surface
        # dwarfs one inspection's local rows and options.
        many_units = [
            {"unit_id": n, "moved": False, "attacked": False,
             "origins": [{"col": n, "row": n, "current": True,
                          "engagements": [{"defender_id": 900 + n, "forecast": {
                              "outcome_bps": [1000, 8000, 1000],
                              "expected_damage_tenths": [20, 10]}}]}]}
            for n in range(1, 21)
        ]
        live_units = [{"id": n, "faction": 0, "def_id": "Grunt", "col": n, "row": n,
                       "hp": 30, "max_hp": 38} for n in range(1, 21)]
        state = {
            "state_revision": 60, "active_faction": 0, "turn": 4,
            "units": live_units, "terrain": [],
            "tactical_surface": {"unit_types": [], "units": many_units,
                                 "threats": {"recruiters": []}},
        }
        full_prompt = prompt_for(state, [], compact=True, decision_mode="batch")
        context = build_local_execution_context(
            state, {"tool": "inspect_target", "unit_id": 901, "purpose": "check retreat safety"},
            "inspect_target", {"target_id": 901, "available": True},
            "TARGET U901 hp=20 at=1,1 terrain=flat attacks=none")
        local_prompt = prompt_for(state, [], compact=True, decision_mode="focused",
                                  local_context=context)
        self.assertLess(len(local_prompt.encode()), len(full_prompt.encode()))

    def test_local_guardrails_do_not_fabricate_missing_global_data(self):
        rendered = compact_local_guardrails({"state_revision": 8, "active_faction": 0})
        self.assertIn('"army":"unknown"', rendered)
        self.assertIn('"recruiter_danger":"unknown"', rendered)
        self.assertIn('"villages":"unknown"', rendered)

        malformed = compact_local_guardrails({
            "active_faction": 0, "units": None,
            "tactical_surface": {"economy": None, "recruitment": None,
                                  "threats": {"recruiters": []}},
        }, {"tasks": [{"units": None}], "holds": None})
        self.assertIn('"army":"unknown"', malformed)
        self.assertIn('"pending_promotions":"unknown"', malformed)
        self.assertIn('"agenda_assigned":[]', malformed)
        self.assertIn('"agenda_holds":"unknown"', malformed)

        readable = compact_local_guardrails({
            "state_revision": 8, "active_faction": 0,
            "units": [{"id": 1, "faction": 0, "hp": 10},
                      {"id": 2, "faction": 0}],
            "terrain": [{"terrain_id": "village", "owner": 0}],
            "tactical_surface": {
                "threats": {"projected_time_of_day": "Night", "recruiters": [{
                    "recruiter_id": 9, "hp": 20, "col": 2, "row": 7,
                    "distinct_attacker_count": 1, "max_incoming_sum": 20,
                    "lethal_attackers_needed": 1,
                    "focus_kill_bps": [705],
                    "focus_expected_damage_tenths": [24],
                }]},
                "economy": {"next_village_income": 4},
                "recruitment": {"gold": 6, "legal_now": True, "reason": "ready",
                                "placement_hexes": [{"col": 1, "row": 1}],
                                "options": [{"def_id": "Skeleton", "affordable": True}]},
            },
        })
        self.assertIn('"hp":"unknown"', readable)
        self.assertIn('projected_village_income', readable)
        self.assertIn('Skeleton', readable)
        self.assertIn('legal_now', readable)
        self.assertIn('focus_expected=(damage_from_1=2.4HP', readable)
        self.assertIn('lethal_attackers_needed=1', readable)
        self.assertNotIn("focus_kill_bps", readable)
        self.assertNotIn("tenths", readable)
        self.assertNotIn("bps", readable)

        self.assertIn("lethal_attackers_needed=null (unreachable under supplied maximum volleys)",
                      compact_local_recruiter_danger({
                          "tactical_surface": {"threats": {"recruiters": [
                              {"recruiter_id": 9, "lethal_attackers_needed": None}
                          ]}}
                      }))
        self.assertIn("lethal_attackers_needed=unknown", compact_local_recruiter_danger({
            "tactical_surface": {"threats": {"recruiters": [{"recruiter_id": 9}]}}
        }))

    def test_local_prompt_uses_selected_inspection_options_only(self):
        state = {"state_revision": 3, "active_faction": 0, "units": [],
                 "terrain": [], "tactical_surface": {"unit_types": []}}
        context = build_local_execution_context(
            state, {"tool": "inspect_hex", "col": 2, "row": 1, "phase": "current"},
            "inspect_hex", {"col": 2, "row": 1, "phase": "current", "options": ["x"]},
            "HEX 2,1 current options=x")
        readiness = build_current_turn_readiness(
            state, moved=[4], attacked=[5], agenda_unassigned=[6], agenda_holds=[7])
        prompt = prompt_for(
            state, [], choices=[{"handle": "unrelated-global-choice"}],
            decision_mode="focused", local_context=context,
            current_turn_readiness=readiness)
        self.assertIn("FOCUSED_LOCAL_CONTEXT_BEGIN revision=3", prompt)
        self.assertIn("HEX 2,1 current options=x", prompt)
        self.assertIn("LOCAL_OPERATION_OPTIONS_UNTRUSTED_DATA_BEGIN:", prompt)
        self.assertIn("LOCAL_OPERATION_OPTIONS_UNTRUSTED_DATA_END", prompt)
        self.assertNotIn("unrelated-global-choice", prompt)
        memory = json.loads(prompt.split("MEMORY_UNTRUSTED_DATA_BEGIN:\n", 1)[1]
                            .split("\nMEMORY_UNTRUSTED_DATA_END", 1)[0])
        self.assertEqual(memory["current_turn_readiness"], readiness)

    def test_shared_formatter_scales_raw_values_and_names_exchange_roles(self):
        forecast = {"outcome_bps": [705, 9000, 295],
                    "expected_damage_tenths": [24, 14]}
        rendered = compact_target_inspection({
            "target_id": 9, "hp": 20, "col": 1, "row": 1, "terrain": "flat",
            "attacks": [{"attacker_id": 2, "origin_col": 1, "origin_row": 0,
                         "forecast": forecast}],
        })
        self.assertIn("defender_killed=7.05%", rendered)
        self.assertIn("to_defender=2.4HP", rendered)
        self.assertIn("attacker_retaliation=1.4HP", rendered)
        self.assertNotIn("bps", rendered)
        self.assertNotIn("tenths", rendered)

    def test_focus_and_aggregate_damage_keep_distinct_names(self):
        rendered = compact_batch_preview({"candidates": [{
            "attack_sequences": [{"target_id": 7, "target_hp": 20,
                                   "attacker_ids": [3, 4], "kill_bps": 705,
                                   "expected_damage_tenths": 144}],
            "recruiter_threats": {"recruiters": [{
                "recruiter_id": 1, "hp": 38, "distinct_attacker_count": 1,
                "max_incoming_sum": 144, "lethal_attackers_needed": None,
                "origins_conflict": False, "focus_kill_bps": [705, 8000, 0],
                "focus_expected_damage_tenths": [24, 40, 60],
            }]},
        }]})
        self.assertIn("kill_probabilities=(7.05%)", rendered)
        self.assertIn("expected_damage=(14.4HP)", rendered)
        self.assertIn("maximum_incoming=144HP", rendered)
        self.assertIn("kill_by_1=7.05%", rendered)
        self.assertIn("damage_from_1=2.4HP", rendered)
        nonlethal = compact_batch_preview({"candidates": [{
            "recruiter_threats": {"recruiters": [{
                "recruiter_id": 1, "hp": 10, "distinct_attacker_count": 0,
                "max_incoming_sum": 0, "lethal_attackers_needed": None,
            }]},
        }]})
        self.assertIn("lethal_attackers_needed=null (unreachable under supplied maximum volleys)", nonlethal)
        missing = compact_batch_preview({"candidates": [{
            "recruiter_threats": {"recruiters": [{"recruiter_id": 1, "hp": 10}]},
        }]})
        self.assertIn("lethal_attackers_needed=unknown", missing)

    def test_readiness_does_not_turn_no_target_into_spent(self):
        rendered = compact_tactical_surface({"units": [{
            "unit_id": 5, "moved": False, "attacked": False, "origins": [],
        }]})
        self.assertIn("readiness=moved=False attacked=False", rendered)
        self.assertIn("none (no_legal_target_from_current_origin)", rendered)
        spent = compact_tactical_surface({"units": [{
            "unit_id": 5, "moved": False, "attacked": True, "origins": [],
        }]})
        self.assertIn("none (already_attacked)", spent)
        all_spent = compact_tactical_surface({"units": [
            {"unit_id": 5, "moved": True, "attacked": True, "origins": []},
            {"unit_id": 6, "moved": False, "attacked": True, "origins": []},
        ]})
        self.assertIn("ATTACK_READINESS ready=none (all attacks spent)", all_spent)

    def test_rules_state_independent_move_attack_and_six_phase_cycle(self):
        prompt = prompt_for({"units": []}, [])
        for text in (
            "one independent Move and one independent Attack",
            "Move then Attack and Attack then Move are legal",
            "Move then Attack then Move is not",
            "odd-r (col,row)",
            "six live labels in order: Dawn, Day, Day, Dusk, Night, Night",
            "no six-recruit turn cap",
        ):
            self.assertIn(text, prompt)

    def test_focused_context_pins_inspection_and_keeps_provenance_internal(self):
        prompt = prompt_for(
            {"state_revision": 12, "units": []}, [], intent="screen recruiter",
            intent_origin={"origin_turn": 3, "origin_revision": 11,
                           "origin_request_id": "r1"},
            agenda={"tasks": [], "holds": []},
            agenda_origin={"origin_turn": 3, "origin_revision": 12,
                           "origin_request_id": "r2"},
            decision_mode="focused")
        self.assertIn("two tiers", prompt)
        self.assertIn("objective_then_local_operation", prompt)
        self.assertIn("stale_revision", prompt)
        self.assertIn("global board, recruiter, economy", prompt)

    def test_budget_suffix_is_bounded_when_sidecar_usage_is_unknown(self):
        class Args:
            max_game_total_tokens = 1000
        context = game_budget_context(Args(), {
            "cumulative_game_total_tokens": 144,
            "game_token_usage_unknown_calls": 1,
            "game_token_usage_gaps": 0,
        })
        self.assertIn("known_measured_spend=144", context)
        self.assertIn("remaining_allowance=856 (upper_bound; usage_unknown)", context)
        self.assertIn("coverage=bounded_unknown", context)

    def test_provenance_without_origin_stays_unknown(self):
        self.assertEqual(memory_provenance(None, {"state_revision": 9})["status"], "unknown")

    def test_resume_memory_requires_commit_and_keeps_text_paired_with_origin(self):
        records = [
            {"type": "forwarded_orders", "batch_id": "b-a", "intent": "accepted A",
             "intent_origin": {"origin_revision": 4}},
            {"type": "batch_committed", "batch_id": "b-a"},
            {"type": "forwarded_orders", "batch_id": "b-b", "intent": "rejected B",
             "intent_origin": {"origin_revision": 5}},
            {"type": "action_failure", "batch_id": "b-b"},
            {"type": "checkpoint_ref", "batch_id": "b-c", "intent": "accepted C",
             "intent_origin": {"origin_revision": 6}},
            {"type": "batch_committed", "batch_id": "b-c"},
        ]
        recovered = recover_optional_memory(records)
        self.assertEqual(recovered["intent"], "accepted C")
        self.assertEqual(recovered["intent_origin"]["origin_revision"], 6)
        # Stop at the rejected/open proposal: a later accepted C must not mask
        # accidental publication of B merely because it was forwarded.
        rejected = recover_optional_memory(records[:4])
        self.assertEqual(rejected["intent"], "accepted A")
        self.assertEqual(rejected["intent_origin"]["origin_revision"], 4)
        unacknowledged = recover_optional_memory(records[:3])
        self.assertEqual(unacknowledged["intent"], "accepted A")
        checkpoint_before_ack = recover_optional_memory([
            {"type": "forwarded_orders", "batch_id": "b-before-ack",
             "intent": "accepted before ack",
             "intent_origin": {"origin_revision": 7}},
            {"type": "checkpoint_ref", "batch_id": "b-before-ack",
             "intent": "accepted before ack",
             "intent_origin": {"origin_revision": 7},
             "path": "match.ckpt", "digest": "checkpoint-digest"},
        ])
        self.assertEqual(checkpoint_before_ack["intent"], "accepted before ack")
        self.assertEqual(checkpoint_before_ack["intent_origin"]["origin_revision"], 7)
        self.assertEqual(recover_optional_memory([
            {"type": "forwarded_orders", "batch_id": "", "intent": "unproven",
             "intent_origin": {"origin_revision": 99}},
            {"type": "batch_committed", "batch_id": ""},
            {"type": "checkpoint_ref", "batch_id": "other", "intent": "wrong",
             "intent_origin": {"origin_revision": 98}},
            {"type": "batch_committed", "batch_id": "proven"},
        ])["intent"], "")
        missing_origin = recover_optional_memory([
            {"type": "intent_update", "intent": "old", "origin": {"origin_revision": 1}},
            {"type": "intent_update", "intent": "new"},
        ])
        self.assertIsNone(missing_origin["intent_origin"])

    def test_local_inspection_repeats_live_type_and_weapon_facts(self):
        enriched = enrich_inspected_units(
            [{"unit_id": 7, "origins": [{"current": True, "engagements": [{"defender_id": 9}]}]}],
            {"units": [{"id": 7, "def_id": "Bowman", "hp": 9, "max_hp": 12},
                       {"id": 9, "def_id": "EnemyBowman"}],
             "tactical_surface": {"unit_types": [{"def_id": "Bowman",
                                                     "attacks": [{"name": "bow", "range": 2}]},
                                                    {"def_id": "EnemyBowman",
                                                     "attacks": [{"name": "sword", "range": 1},
                                                                 {"name": "bow", "range": 2}]}]}},
        )
        rendered = compact_unit_inspection(enriched[0])
        self.assertIn("facts=type:Bowman hp:9/12", rendered)
        self.assertIn('weapons:[{"name":"bow","range":2}]', rendered)
        self.assertIn("defender_facts=type:EnemyBowman", rendered)
        target = enrich_target_inspection(
            {"target_id": 9, "attacks": []},
            {"units": [{"id": 9, "def_id": "EnemyBowman"}],
             "tactical_surface": {"unit_types": [{"def_id": "EnemyBowman",
                                                     "attacks": [{"name": "sword", "range": 1},
                                                                 {"name": "bow", "range": 2}]}]}},
        )
        target_rendered = compact_target_inspection(target)
        self.assertIn("target_facts=type:EnemyBowman", target_rendered)
        self.assertIn('"range":1', target_rendered)

    def test_local_context_projects_referenced_targets_and_matching_support(self):
        state = {
            "state_revision": 135, "active_faction": 0,
            "units": [
                {"id": 6, "faction": 0, "def_id": "Grunt", "col": 6, "row": 6,
                 "hp": 18, "max_hp": 38, "moved": False, "attacked": False,
                 "poisoned": True, "slowed": False, "advancement_pending": False},
                {"id": 9, "faction": 0, "def_id": "Troll", "col": 5, "row": 6,
                 "hp": 30, "max_hp": 42, "moved": True, "attacked": False,
                 "poisoned": False, "slowed": True, "advancement_pending": False},
                {"id": 25, "faction": 1, "def_id": "Bowman", "col": 11, "row": 7,
                 "hp": 33, "max_hp": 33, "moved": False, "attacked": False,
                 "poisoned": False, "slowed": False, "advancement_pending": False},
                {"id": 46, "faction": 0, "def_id": "Wolf Rider", "col": 2, "row": 6,
                 "hp": 20, "max_hp": 32, "moved": False, "attacked": False,
                 "poisoned": False, "slowed": False, "advancement_pending": True,
                 "advances_to": ["Goblin Knight"]},
            ],
            "terrain": [{"terrain_id": "village", "col": 3, "row": 2, "owner": 0},
                        {"terrain_id": "village", "col": 11, "row": 8}],
            "tactical_surface": {"threats": {"recruiters": []}},
        }
        result = {"units": [{"unit_id": 6, "origins": [{
            "current": True, "col": 6, "row": 6,
            "engagements": [{"defender_id": 25, "forecast": {
                "outcome_bps": [1000, 8000, 1000],
                "expected_damage_tenths": [20, 10]}}]}]}]}
        context = build_local_execution_context(
            state, {"tool": "inspect_units", "unit_ids": [6]}, "inspect_units",
            result, "INSPECT_UNITS n=1", agenda={"tasks": [
                {"id": "support", "goal": "screen", "units": [6, 9], "status": "active"},
                {"id": "unrelated", "goal": "elsewhere", "units": [46], "status": "pending"}],
                "holds": []})
        self.assertIsNotNone(context)
        rows = {row["id"]: row for row in context["live_rows"]}
        self.assertEqual(rows[25]["position"], [11, 7])
        self.assertEqual(rows[25]["hp"], 33)
        self.assertEqual(rows[25]["side"], 1)
        self.assertEqual(rows[6]["promotion"], False)
        self.assertEqual(rows[9]["position"], [5, 6])
        self.assertNotIn(46, rows)
        self.assertEqual(context["objective"]["matching_task"]["id"], "support")
        self.assertEqual(context["objective"]["matching_task"]["status"], "active")
        self.assertEqual(context["villages"][1]["owner"], "unknown")
        projection = local_execution_projection(state, context)
        self.assertIn('"id":25', projection)
        self.assertIn('"poisoned":true', projection)

    def test_group_inspection_factors_repeated_profiles_and_forecasts_losslessly(self):
        forecast = {"outcome_bps": [1000, 8000, 1000],
                    "expected_damage_tenths": [20, 10]}
        units = []
        for unit_id in (6, 7):
            units.append({"unit_id": unit_id, "def_id": "Grunt", "hp": 38, "max_hp": 38,
                          "weapons": [{"name": "sword", "damage": 8, "strikes": 2}],
                          "origins": [{"col": 1, "row": unit_id, "current": True,
                                       "engagements": [{"defender_id": 25,
                                                        "defender_def_id": "Bowman",
                                                        "defender_weapons": [{"name": "bow"}],
                                                        "forecast": forecast}]}]})
        rendered = compact_units_inspection(units)
        self.assertIn("PROFILE P1", rendered)
        self.assertIn("FORECAST X1", rendered)
        self.assertEqual(rendered.count("defender_killed="), 1)
        self.assertEqual(rendered.count("T25"), 2)
        self.assertIn("move_destinations=none", rendered)
        self.assertIn("attack_options=@>T25 exchange=X1", rendered)

    def test_group_factor_keeps_heterogeneous_origins_choices_and_dangers(self):
        repeated = {"outcome_bps": [1000, 8000, 1000],
                     "expected_damage_tenths": [20, 10]}
        distinct = {"outcome_bps": [0, 9000, 1000],
                    "expected_damage_tenths": [35, 5]}
        same_danger = {"col": 1, "row": 1, "distinct_attacker_count": 1,
                       "max_incoming_sum": 12, "lethal_attackers_needed": 2,
                       "origins_conflict": False, "focus_kill_bps": [0, 0],
                       "focus_expected_damage_tenths": [20, 30]}
        different_danger = dict(same_danger, col=2, row=1, max_incoming_sum=24,
                                lethal_attackers_needed=1,
                                focus_kill_bps=[1000, 3000],
                                focus_expected_damage_tenths=[40, 50])
        unit = {"unit_id": 6, "def_id": "Grunt", "hp": 20, "max_hp": 38,
                "weapons": [{"name": "sword", "damage": 8}],
                "origins": [
                    {"col": 3, "row": 3, "current": True,
                     "engagements": [{"defender_id": 25, "defender_def_id": "Bowman",
                                       "defender_weapons": [{"name": "bow"}],
                                       "forecast": repeated}]},
                    {"col": 4, "row": 3, "movable": True,
                     "engagements": [{"defender_id": 25, "defender_def_id": "Bowman",
                                       "defender_weapons": [{"name": "bow"}],
                                       "forecast": repeated},
                                      {"defender_id": 26, "defender_def_id": "Mage",
                                       "defender_weapons": [{"name": "staff"}],
                                       "forecast": distinct}]},
                ],
                "destination_threats": [same_danger, dict(same_danger, col=5), different_danger]}
        choices = [
            Choice("c_4_move", "Move U6 to (4,3)", [], "move", {"unit_id": 6}),
            Choice("c_4_attack", "Attack U25 with U6", [], "attack", {"unit_id": 6}),
            Choice("c_4_other", "Move U6 to (4,3) and attack U26", [], "move_attack", {"unit_id": 6}),
        ]
        rendered = compact_units_inspection([unit], choices)
        # Every legal origin and target remains present; repeated and distinct
        # numeric facts are either references or inline values.
        for coordinate in ("at=3,3", "4,3", "->1,1", "->2,1", "->5,1"):
            self.assertIn(coordinate, rendered)
        self.assertIn("@>T25 exchange=", rendered)
        self.assertIn("4,3>T25 exchange=", rendered)
        self.assertIn("4,3>T26 exchange=", rendered)
        self.assertIn("defender_killed=10%", rendered)
        self.assertIn("defender_killed=0%", rendered)
        self.assertIn("to_defender=3.5HP", rendered)
        self.assertIn("PROFILE", rendered)
        for choice in choices:
            self.assertEqual(rendered.count(choice.handle), 1)
        self.assertLessEqual(rendered.count("defender_killed=10%"), 1)

    def test_single_target_renderer_factors_repeated_origin_forecasts(self):
        forecast = {"outcome_bps": [6400, 3600, 0],
                    "expected_damage_tenths": [24, 7]}
        target = {"target_id": 25, "hp": 33, "col": 8, "row": 4,
                  "attacks": [
                      {"attacker_id": 6, "origin_col": 7, "origin_row": 4,
                       "forecast": forecast, "attacker_weapons": [{"name": "axe"}], "moved": True},
                      {"attacker_id": 6, "origin_col": 7, "origin_row": 5,
                       "forecast": forecast, "attacker_weapons": [{"name": "axe"}], "moved": True},
                  ]}
        rendered = compact_target_inspection(target)
        self.assertIn("LOCAL_FACTS_BEGIN", rendered)
        self.assertIn("FORECAST X1", rendered)
        self.assertIn("ENGAGE_STEP U6 via=7,4 exchange=X1", rendered)
        self.assertIn("ENGAGE_STEP U6 via=7,5 exchange=X1", rendered)
        self.assertEqual(rendered.count("defender_killed=64%"), 1)

    def test_local_rows_include_pending_matching_support_and_missing_reference(self):
        state = {"state_revision": 9, "active_faction": 0,
                 "units": [{"id": 6, "faction": 0, "def_id": "Grunt", "col": 3, "row": 3,
                            "hp": 12, "max_hp": 38},
                           {"id": 46, "faction": 0, "def_id": "Wolf Rider", "col": 2, "row": 6,
                            "hp": 20, "max_hp": 32, "advancement_pending": True,
                            "advances_to": ["Goblin Knight", "Direwolf"]}],
                 "terrain": [], "tactical_surface": {"unit_types": []}}
        result = {"units": [{"unit_id": 6, "origins": [{"current": True,
                    "engagements": [{"defender_id": 999, "forecast": {}}]}]}]}
        agenda = {"tasks": [
            {"id": "unrelated", "goal": "old", "units": [46], "status": "active"},
            {"id": "matching", "goal": "screen", "units": [6, 46], "status": "pending"}],
            "holds": []}
        context = build_local_execution_context(
            state, {"tool": "inspect_units", "unit_ids": [6]}, "inspect_units",
            result, "INSPECT_UNITS n=1", agenda=agenda)
        rows = {row["id"]: row for row in context["live_rows"]}
        self.assertEqual(rows[46]["promotion"], ["Goblin Knight", "Direwolf"])
        self.assertEqual(rows[46]["position"], [2, 6])
        self.assertEqual(rows[999]["type"], "unknown")
        self.assertEqual(rows[999]["position"], "unknown")
        self.assertEqual(context["objective"]["matching_task"]["id"], "matching")
        self.assertEqual(context["objective"]["matching_task"]["status"], "pending")
        projection = local_execution_projection(state, context)
        self.assertNotIn("LOCAL_PROVISIONAL_OBJECTIVE", projection)
        delivered = prompt_for(state, [], compact=True, decision_mode="focused",
                               agenda=agenda, local_context=context)
        self.assertIn('"matching_task":{"goal":"screen","id":"matching","status":"pending"', delivered)

    def test_factored_danger_retains_null_and_missing_distinctions(self):
        base = {"unit_id": 4, "origins": [], "destination_threats": [
            {"col": 1, "row": 1, "distinct_attacker_count": 0,
             "max_incoming_sum": 0, "lethal_attackers_needed": None,
             "origins_conflict": False},
            {"col": 2, "row": 1, "distinct_attacker_count": 0,
             "max_incoming_sum": 0, "origins_conflict": False},
        ]}
        rendered = compact_units_inspection([base])
        self.assertIn("lethal_attackers_needed=null (unreachable under supplied maximum volleys)", rendered)
        self.assertIn("lethal_attackers_needed=unknown", rendered)
        self.assertIn("->1,1 direct_attackers=", rendered)
        self.assertIn("->2,1 direct_attackers=", rendered)


if __name__ == "__main__":
    unittest.main()
