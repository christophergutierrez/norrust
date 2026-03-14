#!/usr/bin/env python3
"""Convert a Wesnoth scenario .cfg file to NorRust units.toml + dialogue.toml.

Parses WML (Wesnoth Markup Language) scenario files and extracts:
- Side definitions (factions, leaders, recruits, gold)
- Unit placements from [event]name=prestart blocks
- Dialogue from [message] blocks inside events
- Win/lose objectives
- Turn-based events

Usage:
    python tools/convert_wesnoth_scenario.py <scenario.cfg> [options]

Examples:
    # Parse and show what would be generated
    python tools/convert_wesnoth_scenario.py ~/git_home/wesnoth/.../01_Rooting_Out_a_Mage.cfg

    # Write units.toml and dialogue.toml to a scenario directory
    python tools/convert_wesnoth_scenario.py scenario.cfg -o scenarios/rooting_out/

    # Also generate campaign.toml entry
    python tools/convert_wesnoth_scenario.py scenario.cfg -o scenarios/rooting_out/ --campaign two_brothers
"""

import argparse
import re
import sys
from pathlib import Path


class WMLParser:
    """Minimal WML parser that extracts structured data from Wesnoth .cfg files.

    Handles:
    - [tag]...[/tag] nesting
    - key=value attributes
    - #ifdef/#else/#endif (picks first branch)
    - {MACRO ...} (records but doesn't expand)
    - _ "translated string" markers
    """

    def __init__(self, text):
        self.text = text
        self.pos = 0

    def parse(self):
        """Parse the entire file into a tree of dicts/lists."""
        return self._parse_block(None)

    def _parse_block(self, end_tag):
        """Parse until [/end_tag] or EOF."""
        result = {"_children": []}
        # Stack-based ifdef tracking: each entry is True (taking ifdef branch)
        # or False (skipping, in #else branch). We always want the #ifdef branch.
        skip_stack = []

        while self.pos < len(self.text):
            line = self._next_line()
            if line is None:
                break

            stripped = line.strip()

            # Skip comments
            if stripped.startswith("#textdomain") or stripped.startswith("# "):
                continue
            if stripped.startswith("# wmllint"):
                continue

            # Preprocessor directives
            if stripped.startswith("#ifdef") or stripped.startswith("#ifndef"):
                # Push: not skipping yet (taking the ifdef branch)
                skip_stack.append(False)
                continue
            if stripped.startswith("#else"):
                if skip_stack:
                    # Flip: start skipping the #else branch
                    skip_stack[-1] = True
                continue
            if stripped.startswith("#endif"):
                if skip_stack:
                    skip_stack.pop()
                continue

            # Skip lines if any level in the stack is in skip mode
            if any(skip_stack):
                continue

            # Opening tag: [tag_name] or [+tag_name]
            m = re.match(r"^\[(\+?)(\w+)\]$", stripped)
            if m:
                tag_name = m.group(2)
                child = self._parse_block(tag_name)
                child["_tag"] = tag_name
                result["_children"].append(child)
                continue

            # Closing tag: [/tag_name]
            m = re.match(r"^\[/(\w+)\]$", stripped)
            if m:
                if m.group(1) == end_tag:
                    break
                continue

            # Macro invocation: {MACRO args}
            if stripped.startswith("{") and not stripped.startswith("{~"):
                result.setdefault("_macros", []).append(stripped)
                continue

            # Key=value
            m = re.match(r'^(\w+)\s*=\s*(.+)$', stripped)
            if m:
                key = m.group(1)
                value = self._clean_value(m.group(2))
                result[key] = value
                continue

        return result

    def _next_line(self):
        """Return next non-empty line or None."""
        while self.pos < len(self.text):
            end = self.text.find("\n", self.pos)
            if end == -1:
                line = self.text[self.pos:]
                self.pos = len(self.text)
            else:
                line = self.text[self.pos:end]
                self.pos = end + 1

            stripped = line.strip()
            if stripped:
                return line
        return None

    def _clean_value(self, value):
        """Clean a WML value: strip quotes, translation markers, etc."""
        value = value.strip()
        # Remove trailing WML comments
        if " #" in value and not value.startswith('"'):
            value = value[:value.index(" #")].strip()
        # Remove translation marker: _ "text" → text
        value = re.sub(r'^_\s*"', '"', value)
        # Remove string concatenation
        value = re.sub(r'"\s*\+\s*"', '', value)
        value = re.sub(r'"\s*\+\s*_\s*"', '', value)
        # Strip outer quotes
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        return value


def find_children(node, tag):
    """Find all direct children with the given tag name."""
    return [c for c in node.get("_children", []) if c.get("_tag") == tag]


def find_child(node, tag):
    """Find first child with the given tag name."""
    children = find_children(node, tag)
    return children[0] if children else None


def extract_sides(scenario):
    """Extract faction/side information from scenario."""
    sides = []
    for side in find_children(scenario, "side"):
        info = {
            "side_num": int(side.get("side", 1)),
            "controller": side.get("controller", "ai"),
            "team_name": side.get("team_name", ""),
            "gold": int(side.get("gold", 100)),
            "recruits": [],
            "leader_type": side.get("type"),
            "leader_id": side.get("id"),
            "leader_name": side.get("name"),
            "canrecruit": side.get("canrecruit", "no") == "yes",
        }
        recruits = side.get("recruit", "")
        if recruits:
            info["recruits"] = [r.strip() for r in recruits.split(",")]
        sides.append(info)
    return sides


def extract_units_from_macros(scenario):
    """Extract unit placements from NAMED_LOYAL_UNIT macros in prestart events."""
    units = []
    unit_id = 100  # Start IDs high to avoid conflicts with leader IDs

    for event in find_children(scenario, "event"):
        if event.get("name") != "prestart":
            continue

        for macro in event.get("_macros", []):
            # {NAMED_LOYAL_UNIT side type x y id name}
            m = re.match(
                r"\{NAMED_LOYAL_UNIT\s+(\d+)\s+(\w[\w\s]*?)\s+(\d+)\s+(\d+)\s+(\w+)\s+",
                macro,
            )
            if m:
                side = int(m.group(1))
                unit_type = m.group(2).strip()
                col = int(m.group(3))
                row = int(m.group(4))
                name = m.group(5)
                units.append({
                    "id": unit_id,
                    "unit_type": unit_type,
                    "faction": side - 1,  # Wesnoth 1-indexed → NorRust 0-indexed
                    "col": col - 1,       # Wesnoth 1-indexed → NorRust 0-indexed
                    "row": row - 1,
                    "name": name,
                })
                unit_id += 1

    return units


def extract_dialogue(scenario):
    """Extract dialogue from events into NorRust dialogue.toml format."""
    dialogues = []
    dialogue_id = 0

    for event in find_children(scenario, "event"):
        event_name = event.get("name", "")
        turn = None

        # Map event name to trigger
        if event_name == "start":
            trigger = "scenario_start"
        elif event_name == "prestart":
            continue  # Skip prestart (unit placement, not dialogue)
        elif event_name.startswith("turn "):
            trigger = "turn_start"
            turn = int(event_name.split()[1])
        elif event_name == "time over":
            trigger = "turn_end"
        elif event_name == "last breath":
            trigger = "leader_attacked"
        elif event_name in ("die", "attack"):
            trigger = "scenario_start"  # One-shot event, treat as general
        elif event_name == "recruit":
            continue  # Skip recruitment events
        elif event_name == "victory":
            continue  # Skip victory events
        else:
            trigger = "scenario_start"

        for message in find_children(event, "message"):
            speaker = message.get("speaker", "narrator")
            text = message.get("message", "")
            if not text:
                continue

            # Clean up WML formatting
            text = text.replace("<i>", "").replace("</i>", "")
            text = text.replace("<b>", "").replace("</b>", "")
            text = re.sub(r'\s+', ' ', text).strip()

            # Build speaker prefix
            if speaker not in ("narrator", "unit", "second_unit"):
                text = f"[{speaker}] {text}"

            entry = {
                "id": f"dialogue_{dialogue_id:03d}",
                "trigger": trigger,
                "text": text,
            }
            if turn is not None:
                entry["turn"] = turn
                entry["faction"] = 0  # Most events happen on player's turn

            dialogues.append(entry)
            dialogue_id += 1

    return dialogues


def extract_story(scenario):
    """Extract story/intro text from [story] blocks."""
    stories = []
    for story in find_children(scenario, "story"):
        for part in find_children(story, "part"):
            text = part.get("story", "")
            if text:
                text = text.replace("<i>", "").replace("</i>", "")
                text = text.replace("<b>", "").replace("</b>", "")
                # Collapse whitespace but preserve paragraph breaks
                paragraphs = [re.sub(r'\s+', ' ', p.strip()) for p in text.split("\n\n")]
                text = "\n\n".join(p for p in paragraphs if p)
                stories.append(text)
    return stories


def extract_objectives(scenario):
    """Extract win/lose conditions from [objectives] blocks."""
    objectives = {"win": [], "lose": [], "gold_carryover": 40}

    # Search in prestart events too
    for event in find_children(scenario, "event"):
        for obj_block in find_children(event, "objectives"):
            for obj in find_children(obj_block, "objective"):
                desc = obj.get("description", "")
                condition = obj.get("condition", "win")
                if desc:
                    objectives[condition].append(desc)
            for gc in find_children(obj_block, "gold_carryover"):
                pct = gc.get("carryover_percentage")
                if pct:
                    objectives["gold_carryover"] = int(pct)

    return objectives


def escape_toml(s):
    """Escape a string for use in a TOML quoted string value."""
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "\\r")
    s = s.replace("\t", "\\t")
    return s


def write_units_toml(sides, units, output_path, scenario_name=""):
    """Write a NorRust units.toml file."""
    lines = []
    if scenario_name:
        lines.append(f"# Units for scenario: {scenario_name}")
        lines.append("")

    uid = 1

    # Place leaders from sides
    for side in sides:
        if side["leader_type"]:
            faction = side["side_num"] - 1
            leader_name = side.get("leader_name", "Leader")
            lines.append(f"# {side['team_name']} leader: {leader_name}")
            lines.append("[[units]]")
            lines.append(f'id = {uid}')
            lines.append(f'unit_type = "{side["leader_type"]}"')
            lines.append(f'faction = {faction}')
            lines.append(f"# Placed on keep (set col/row after map conversion)")
            lines.append(f"col = 0")
            lines.append(f"row = 0")
            lines.append("")
            uid += 1

    # Place named units
    for u in units:
        lines.append(f"# {u.get('name', u['unit_type'])}")
        lines.append("[[units]]")
        lines.append(f"id = {uid}")
        lines.append(f'unit_type = "{u["unit_type"]}"')
        lines.append(f"faction = {u['faction']}")
        lines.append(f"col = {u['col']}")
        lines.append(f"row = {u['row']}")
        lines.append("")
        uid += 1

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines))
    return output_path


def write_dialogue_toml(dialogues, stories, output_path, scenario_name=""):
    """Write a NorRust dialogue.toml file."""
    lines = []
    if scenario_name:
        lines.append(f"# Dialogue for scenario: {scenario_name}")
        lines.append("")

    # Add story intro as scenario_start dialogues
    for i, story_text in enumerate(stories):
        lines.append("[[dialogue]]")
        lines.append(f'id = "story_{i:03d}"')
        lines.append('trigger = "scenario_start"')
        # Escape for TOML strings
        escaped = escape_toml(story_text)
        lines.append(f'text = "{escaped}"')
        lines.append("")

    # Add event dialogues
    for d in dialogues:
        lines.append("[[dialogue]]")
        lines.append(f'id = "{d["id"]}"')
        lines.append(f'trigger = "{d["trigger"]}"')
        if "turn" in d:
            lines.append(f'turn = {d["turn"]}')
        if "faction" in d:
            lines.append(f'faction = {d["faction"]}')
        escaped = escape_toml(d["text"])
        lines.append(f'text = "{escaped}"')
        lines.append("")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines))
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Convert a Wesnoth scenario .cfg to NorRust units.toml + dialogue.toml",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("cfg_file", help="Path to Wesnoth scenario .cfg file")
    parser.add_argument("-o", "--output-dir", help="Output directory for TOML files")
    parser.add_argument("--campaign", help="Campaign ID (for generating campaign.toml entry)")
    parser.add_argument("--col-offset", type=int, default=0,
                        help="Column offset for unit coordinates (for cropped maps)")
    parser.add_argument("--row-offset", type=int, default=0,
                        help="Row offset for unit coordinates (for cropped maps)")

    args = parser.parse_args()

    cfg_path = Path(args.cfg_file)
    if not cfg_path.exists():
        print(f"Error: {cfg_path} not found", file=sys.stderr)
        sys.exit(1)

    # Parse the WML file
    text = cfg_path.read_text()
    tree = WMLParser(text).parse()

    # Find the scenario block
    scenario = find_child(tree, "scenario")
    if not scenario:
        print("Error: no [scenario] block found", file=sys.stderr)
        sys.exit(1)

    scenario_id = scenario.get("id", "unknown")
    scenario_name = scenario.get("name", scenario_id)
    turns = scenario.get("turns", "20")
    next_scenario = scenario.get("next_scenario", "")
    map_file = scenario.get("map_file", "")

    print(f"Scenario: {scenario_name}")
    print(f"  ID: {scenario_id}")
    print(f"  Turns: {turns}")
    print(f"  Map file: {map_file}")
    print(f"  Next scenario: {next_scenario}")
    print()

    # Extract sides
    sides = extract_sides(scenario)
    for s in sides:
        controller = "Player" if s["controller"] == "human" else "AI"
        print(f"  Side {s['side_num']} ({controller}): {s['team_name']}")
        if s["leader_type"]:
            print(f"    Leader: {s['leader_name']} ({s['leader_type']})")
        print(f"    Gold: {s['gold']}")
        if s["recruits"]:
            print(f"    Recruits: {', '.join(s['recruits'])}")
        print()

    # Extract units
    units = extract_units_from_macros(scenario)
    # Apply coordinate offsets
    for u in units:
        u["col"] -= args.col_offset
        u["row"] -= args.row_offset

    if units:
        print(f"  Named units ({len(units)}):")
        for u in units:
            print(f"    {u['name']:12s} {u['unit_type']:12s} faction={u['faction']} ({u['col']},{u['row']})")
        print()

    # Extract objectives
    objectives = extract_objectives(scenario)
    if objectives["win"]:
        print("  Win conditions:")
        for obj in objectives["win"]:
            print(f"    - {obj}")
    if objectives["lose"]:
        print("  Lose conditions:")
        for obj in objectives["lose"]:
            print(f"    - {obj}")
    print(f"  Gold carryover: {objectives['gold_carryover']}%")
    print()

    # Extract dialogue
    stories = extract_story(scenario)
    dialogues = extract_dialogue(scenario)
    print(f"  Story parts: {len(stories)}")
    print(f"  Dialogue entries: {len(dialogues)}")

    if stories:
        print("\n  Story preview:")
        for i, s in enumerate(stories):
            preview = s[:100].replace("\n", " ")
            print(f"    Part {i+1}: {preview}...")

    if dialogues:
        print("\n  Dialogue preview:")
        for d in dialogues[:5]:
            preview = d["text"][:80].replace("\n", " ")
            print(f"    [{d['trigger']}] {preview}...")
        if len(dialogues) > 5:
            print(f"    ... and {len(dialogues) - 5} more")

    # Write output files
    if args.output_dir:
        out_dir = Path(args.output_dir)
        units_path = write_units_toml(sides, units, out_dir / "units.toml", scenario_name)
        dialogue_path = write_dialogue_toml(dialogues, stories, out_dir / "dialogue.toml", scenario_name)
        print(f"\nWrote {units_path}")
        print(f"Wrote {dialogue_path}")

        # Print the needed recruits that must exist in NorRust's unit registry
        all_unit_types = set()
        for s in sides:
            all_unit_types.update(s["recruits"])
            if s["leader_type"]:
                all_unit_types.add(s["leader_type"])
        for u in units:
            all_unit_types.add(u["unit_type"])

        print(f"\nRequired unit types ({len(all_unit_types)}):")
        for t in sorted(all_unit_types):
            print(f"  {t}")

        if args.campaign:
            print(f"\nCampaign entry for campaigns/{args.campaign}.toml:")
            print(f'[[scenarios]]')
            print(f'board = "{out_dir.name}/board.toml"')
            print(f'units = "{out_dir.name}/units.toml"')
            print(f'preset_units = true')


if __name__ == "__main__":
    main()
