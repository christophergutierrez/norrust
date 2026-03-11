#!/usr/bin/env python3
"""
verify_stats.py — Compare norrust unit TOMLs against Wesnoth WML source data.

Reports stat discrepancies between our TOML files and the authoritative WML.
Skips: abilities, advances_to, name (intentional overrides).
"""

import os
import re
import sys
from pathlib import Path

# Import WML parsing from scraper
sys.path.insert(0, str(Path(__file__).parent))
from scrape_wesnoth import parse_movetypes, parse_units_from_file, resolve_unit, UNITS_CFG, UNITS_DIR

# ── TOML parser (minimal, stdlib only) ─────────────────────────────────────────

def parse_toml(path: Path) -> dict:
    """Parse a unit TOML file into a dict matching scraper's output format."""
    text = path.read_text(encoding="utf-8")
    unit = {
        "id": "", "name": "", "race": "", "level": 0, "experience": 0,
        "max_hp": 0, "movement": 0, "alignment": "", "cost": 0, "usage": "",
        "abilities": [], "advances_to": [],
        "attacks": [],
        "resistances": {}, "movement_costs": {}, "defense": {},
    }

    section = None  # current [section] or None for top-level
    current_attack = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Section headers
        if stripped == "[[attacks]]":
            if current_attack is not None:
                unit["attacks"].append(current_attack)
            current_attack = {"id": "", "name": "", "damage": 0, "strikes": 0,
                              "attack_type": "", "range": "", "specials": []}
            section = "attack"
            continue
        if stripped.startswith("[") and not stripped.startswith("[["):
            if current_attack is not None:
                unit["attacks"].append(current_attack)
                current_attack = None
            sec_name = stripped.strip("[]")
            section = sec_name
            continue

        if "=" not in stripped:
            continue

        key, _, raw_val = stripped.partition("=")
        key = key.strip()
        val = raw_val.strip()

        # Parse value
        if val.startswith('"'):
            val = val.strip('"')
        elif val.startswith("["):
            # Parse array
            items = re.findall(r'"([^"]*)"', val)
            if section == "attack" and current_attack is not None:
                current_attack[key] = items
            elif section is None:
                unit[key] = items
            continue
        else:
            try:
                val = int(val)
            except ValueError:
                pass

        # Assign to correct section
        if section == "attack" and current_attack is not None:
            current_attack[key] = val
        elif section == "resistances":
            unit["resistances"][key] = val
        elif section == "movement_costs":
            unit["movement_costs"][key] = val
        elif section == "defense":
            unit["defense"][key] = val
        elif section is None:
            unit[key] = val

    if current_attack is not None:
        unit["attacks"].append(current_attack)

    return unit


# ── Comparison ─────────────────────────────────────────────────────────────────

SKIP_FIELDS = {"abilities", "advances_to", "name"}  # Intentional overrides

NUMERIC_FIELDS = ["max_hp", "movement", "level", "experience", "cost"]
STRING_FIELDS = ["alignment", "race", "usage"]
DICT_SECTIONS = ["resistances", "movement_costs", "defense"]


def compare_units(toml_path: Path, toml_unit: dict, wml_unit: dict) -> list:
    """Compare a TOML unit against WML source. Returns list of (field, expected, actual)."""
    diffs = []

    for field in NUMERIC_FIELDS:
        expected = wml_unit.get(field, 0)
        actual = toml_unit.get(field, 0)
        if expected != actual:
            diffs.append((field, expected, actual))

    for field in STRING_FIELDS:
        expected = wml_unit.get(field, "")
        actual = toml_unit.get(field, "")
        if expected != actual:
            diffs.append((field, expected, actual))

    # Compare attacks
    wml_attacks = wml_unit.get("attacks", [])
    toml_attacks = toml_unit.get("attacks", [])

    if len(wml_attacks) != len(toml_attacks):
        diffs.append(("attacks.count", len(wml_attacks), len(toml_attacks)))
    else:
        for i, (wa, ta) in enumerate(zip(wml_attacks, toml_attacks)):
            for afield in ["damage", "strikes", "attack_type", "range"]:
                we = wa.get(afield, "")
                te = ta.get(afield, "")
                if we != te:
                    diffs.append((f"attacks[{i}].{afield}", we, te))

    # Compare dict sections
    for section in DICT_SECTIONS:
        wml_dict = wml_unit.get(section, {})
        toml_dict = toml_unit.get(section, {})
        all_keys = sorted(set(wml_dict.keys()) | set(toml_dict.keys()))
        for k in all_keys:
            we = wml_dict.get(k)
            te = toml_dict.get(k)
            if we is not None and te is not None and we != te:
                diffs.append((f"{section}.{k}", we, te))
            elif we is not None and te is None:
                diffs.append((f"{section}.{k}", we, "MISSING"))
            elif we is None and te is not None:
                diffs.append((f"{section}.{k}", "MISSING", te))

    return diffs


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("Parsing Wesnoth WML source...")
    movetypes = parse_movetypes(UNITS_CFG)

    # Build WML unit dict keyed by ID
    wml_units = {}
    cfg_files = sorted(UNITS_DIR.rglob("*.cfg"))
    for cfg_path in cfg_files:
        raw = parse_units_from_file(cfg_path, movetypes)
        for u in raw:
            resolved = resolve_unit(u, movetypes)
            if resolved:
                wml_units[resolved["id"]] = resolved

    print(f"  {len(wml_units)} WML units resolved")

    # Walk our TOML tree
    data_dir = Path(__file__).parent.parent / "data" / "units"
    toml_files = sorted(data_dir.rglob("*.toml"))

    total_checked = 0
    units_with_diffs = 0
    total_field_mismatches = 0
    unmatched = []

    for toml_path in toml_files:
        toml_unit = parse_toml(toml_path)
        unit_id = toml_unit["id"]

        if unit_id not in wml_units:
            unmatched.append((toml_path.relative_to(data_dir.parent.parent), unit_id))
            continue

        total_checked += 1
        wml_unit = wml_units[unit_id]
        diffs = compare_units(toml_path, toml_unit, wml_unit)

        if diffs:
            units_with_diffs += 1
            total_field_mismatches += len(diffs)
            rel = toml_path.relative_to(data_dir.parent.parent)
            print(f"\nDISCREPANCY: {rel}")
            for field, expected, actual in diffs:
                print(f"  {field}: expected {expected} (WML), got {actual} (TOML)")

    print(f"\n{'='*60}")
    print(f"Summary: {total_checked} checked, {units_with_diffs} with discrepancies, {total_field_mismatches} field mismatches")

    if unmatched:
        print(f"\nUnmatched (no WML counterpart, skipped): {len(unmatched)}")
        for path, uid in unmatched:
            print(f"  {path} (id={uid})")

    if units_with_diffs == 0:
        print("\nAll stats match WML source.")

    return units_with_diffs


if __name__ == "__main__":
    sys.exit(0 if main() == 0 else 1)
