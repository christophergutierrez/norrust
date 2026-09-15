"""Byte-identical-extraction tests for tools/threat_render.py.

These functions were moved verbatim out of tools/llm_client.py (Stack 2 of
the proposed-movement plan). The expected strings below were captured from
the pre-move llm_client implementation and are kept as literals so this
suite fails if the moved bodies ever drift from what llm_client rendered.
"""
from __future__ import annotations

import unittest

from . import threat_render as tr


class ReadableProbabilityTests(unittest.TestCase):
    def test_values(self):
        self.assertEqual(tr._readable_probability(5000), "50%")
        self.assertEqual(tr._readable_probability(0), "0%")
        self.assertEqual(tr._readable_probability(10000), "100%")
        self.assertEqual(tr._readable_probability(33), "0.33%")

    def test_missing_or_wrong_type_is_unknown(self):
        self.assertEqual(tr._readable_probability(None), "unknown")
        self.assertEqual(tr._readable_probability("x"), "unknown")
        self.assertEqual(tr._readable_probability(True), "unknown")


class ReadableHpTenthsTests(unittest.TestCase):
    def test_values(self):
        self.assertEqual(tr._readable_hp_tenths(50), "5HP")
        self.assertEqual(tr._readable_hp_tenths(0), "0HP")
        self.assertEqual(tr._readable_hp_tenths(7), "0.7HP")
        self.assertEqual(tr._readable_hp_tenths(105), "10.5HP")

    def test_missing_or_wrong_type_is_unknown(self):
        self.assertEqual(tr._readable_hp_tenths(None), "unknown")
        self.assertEqual(tr._readable_hp_tenths(True), "unknown")


class ReadableWholeHpTests(unittest.TestCase):
    def test_values(self):
        self.assertEqual(tr._readable_whole_hp(5), "5HP")
        self.assertEqual(tr._readable_whole_hp(0), "0HP")

    def test_missing_or_wrong_type_is_unknown(self):
        self.assertEqual(tr._readable_whole_hp(None), "unknown")
        self.assertEqual(tr._readable_whole_hp(True), "unknown")
        self.assertEqual(tr._readable_whole_hp("x"), "unknown")


class ReadableProbabilityListTests(unittest.TestCase):
    def test_full_list(self):
        self.assertEqual(
            tr._readable_probability_list([5000, 10000], ("a", "b", "c")),
            "a=50%,b=100%,c=unknown")

    def test_empty_list(self):
        self.assertEqual(tr._readable_probability_list([], ("a", "b")), "a=unknown,b=unknown")

    def test_none_is_unknown(self):
        self.assertEqual(tr._readable_probability_list(None, ("a", "b")), "unknown")

    def test_short_list(self):
        self.assertEqual(
            tr._readable_probability_list([5000], ("a", "b", "c")),
            "a=50%,b=unknown,c=unknown")


class ReadableExchangeTests(unittest.TestCase):
    def test_full_forecast(self):
        forecast = {"outcome_bps": [100, 200, 300], "expected_damage_tenths": [10, 20]}
        self.assertEqual(
            tr._readable_exchange(forecast),
            "exchange=(defender_killed=1%,both_survive=2%,attacker_killed=3%; "
            "expected_damage=(to_defender=1HP,attacker_retaliation=2HP))")

    def test_empty_dict(self):
        self.assertEqual(
            tr._readable_exchange({}),
            "exchange=(unknown; expected_damage=(to_defender=unknown,attacker_retaliation=unknown))")

    def test_none_forecast(self):
        self.assertEqual(tr._readable_exchange(None), "exchange=unknown")

    def test_non_list_damage_and_short_outcomes(self):
        forecast = {"outcome_bps": [100], "expected_damage_tenths": 5}
        self.assertEqual(
            tr._readable_exchange(forecast),
            "exchange=(defender_killed=1%,both_survive=unknown,attacker_killed=unknown; "
            "expected_damage=(to_defender=unknown,attacker_retaliation=unknown))")


class ReadableFocusTests(unittest.TestCase):
    def test_probability_focus(self):
        self.assertEqual(
            tr._readable_focus([100, 200, 300]),
            "kill_by_1=1%,kill_by_2=2%,kill_by_3=3%")

    def test_damage_focus(self):
        self.assertEqual(
            tr._readable_focus([100, 200, 300], damage=True),
            "damage_from_1=10HP,damage_from_2=20HP,damage_from_3=30HP")

    def test_none_is_unknown(self):
        self.assertEqual(tr._readable_focus(None), "unknown")
        self.assertEqual(tr._readable_focus(None, damage=True), "unknown")

    def test_short_list_pads_unknown_not_zero(self):
        self.assertEqual(
            tr._readable_focus([50]),
            "kill_by_1=0.5%,kill_by_2=unknown,kill_by_3=unknown")
        self.assertEqual(
            tr._readable_focus([50], damage=True),
            "damage_from_1=5HP,damage_from_2=unknown,damage_from_3=unknown")

    def test_empty_list(self):
        self.assertEqual(
            tr._readable_focus([]),
            "kill_by_1=unknown,kill_by_2=unknown,kill_by_3=unknown")
        self.assertEqual(
            tr._readable_focus([], damage=True),
            "damage_from_1=unknown,damage_from_2=unknown,damage_from_3=unknown")


class ReadableKillTests(unittest.TestCase):
    def test_list_delegates_to_focus(self):
        self.assertEqual(
            tr._readable_kill([100, 200, 300]),
            "kill_by_1=1%,kill_by_2=2%,kill_by_3=3%")

    def test_scalar_delegates_to_probability(self):
        self.assertEqual(tr._readable_kill(5000), "50%")

    def test_none_is_unknown(self):
        self.assertEqual(tr._readable_kill(None), "unknown")


class ReadableDamageTests(unittest.TestCase):
    def test_list_delegates_to_focus_damage(self):
        self.assertEqual(
            tr._readable_damage([100, 200, 300]),
            "damage_from_1=10HP,damage_from_2=20HP,damage_from_3=30HP")

    def test_scalar_delegates_to_hp_tenths(self):
        self.assertEqual(tr._readable_damage(50), "5HP")

    def test_none_is_unknown(self):
        self.assertEqual(tr._readable_damage(None), "unknown")


class ReadableThreatCountTests(unittest.TestCase):
    def test_present_value(self):
        self.assertEqual(tr._readable_threat_count({"distinct_attacker_count": 4},
                                                     "distinct_attacker_count"), "4")

    def test_none_value_is_unknown(self):
        self.assertEqual(tr._readable_threat_count({"distinct_attacker_count": None},
                                                     "distinct_attacker_count"), "unknown")

    def test_missing_key_is_unknown(self):
        self.assertEqual(tr._readable_threat_count({}, "distinct_attacker_count"), "unknown")


class ReadableLethalAttackersTests(unittest.TestCase):
    def test_present_value(self):
        self.assertEqual(tr._readable_lethal_attackers({"lethal_attackers_needed": 2}), "2")

    def test_null_means_unreachable_not_missing(self):
        self.assertEqual(
            tr._readable_lethal_attackers({"lethal_attackers_needed": None}),
            "null (unreachable under supplied maximum volleys)")

    def test_missing_key_is_unknown(self):
        self.assertEqual(tr._readable_lethal_attackers({}), "unknown")

    def test_negative_value_is_unknown(self):
        self.assertEqual(tr._readable_lethal_attackers({"lethal_attackers_needed": -1}), "unknown")

    def test_bool_value_is_unknown(self):
        self.assertEqual(tr._readable_lethal_attackers({"lethal_attackers_needed": True}), "unknown")

    def test_custom_key(self):
        self.assertEqual(
            tr._readable_lethal_attackers({"open_lethal_attackers_needed": 3},
                                           "open_lethal_attackers_needed"), "3")


if __name__ == "__main__":
    unittest.main()
