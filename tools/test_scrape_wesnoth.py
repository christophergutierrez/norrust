"""Focused importer contract tests for Wesnoth defense conversion."""

import tempfile
import unittest
from pathlib import Path

try:
    from .scrape_wesnoth import convert_defense, parse_movetypes, parse_units_from_file, resolve_unit
except ImportError:  # Direct invocation: python tools/test_scrape_wesnoth.py
    from scrape_wesnoth import convert_defense, parse_movetypes, parse_units_from_file, resolve_unit


class DefenseImportTests(unittest.TestCase):
    def test_wesnoth_hit_chance_becomes_avoidance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "units.cfg"
            path.write_text(
                """
[movetype]
name=orcishfoot
[movement_costs]
flat=1
[/movement_costs]
[defense]
flat=60
forest=50
castle=40
swamp_water=70
fungus=-80
[/defense]
[/movetype]
"""
            )
            movetypes = parse_movetypes(path)

        self.assertEqual(
            movetypes["orcishfoot"]["defense"],
            {"flat": 40, "forest": 50, "castle": 60, "swamp_water": 30, "fungus": 20},
        )

    def test_unit_resolution_keeps_converted_movement_type_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            movement_path = root / "units.cfg"
            movement_path.write_text(
                """
[movetype]
name=orcishfoot
[defense]
flat=60
castle=40
[/defense]
[/movetype]
"""
            )
            unit_path = root / "unit.cfg"
            unit_path.write_text(
                """
[unit_type]
id=orcishfoot
name=Orcish Foot
hitpoints=30
movement_type=orcishfoot
[attack]
name=blade
description=blade
damage=5
number=2
type=blade
range=melee
[/attack]
[defense]
castle=30
[/defense]
[/unit_type]
"""
            )
            movetypes = parse_movetypes(movement_path)
            units = parse_units_from_file(unit_path, movetypes)
            resolved = resolve_unit(units[0], movetypes)

        self.assertEqual(resolved["defense"], {"flat": 40, "castle": 70})

    def test_out_of_range_defense_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "units.cfg"
            path.write_text(
                """
[movetype]
name=bad
[defense]
flat=101
[/defense]
[/movetype]
"""
            )
            with self.assertRaisesRegex(ValueError, r"invalid defense value flat=\'101\'"):
                parse_movetypes(path)

    def test_negative_conversion_is_bounded_magnitude_only(self):
        self.assertEqual(convert_defense(-70), 30)
        self.assertEqual(convert_defense(0), 100)
        with self.assertRaises(ValueError):
            convert_defense(-101)


if __name__ == "__main__":
    unittest.main()
