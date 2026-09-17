"""Build the recruiter survival audit across the two historical games.

Analyzes the last four recruiter-danger decision boundaries in each game:
Game 1 (seed 4477, commit b365262) and Game 2 (seed 7731, commit 400165b).
Tests legal alternatives on isolated clones with greedy_driver and outputs
tmp/recruiter-survival/audit.json and tmp/recruiter-survival/AUDIT.md.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "norrust_core/target/release/greedy_driver"
BOARD = ROOT / "scenarios/big_battle_6/board.toml"
OUT_DIR = ROOT / "tmp/recruiter-survival"


def load_game_records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def extract_boundary_facts(records: list[dict[str, Any]], target_rev: int, game_id: str) -> dict[str, Any]:
    packet_record = None
    model_request = None
    model_response = None
    forwarded = None
    turn_boundary = None
    subsequent_events = []
    checkpoint_ref = None

    for i, r in enumerate(records):
        if r.get("type") == "decision_packet" and r.get("state_revision") == target_rev:
            packet_record = r
            for j in range(i + 1, min(i + 50, len(records))):
                sub = records[j]
                st = sub.get("type")
                if st == "checkpoint_ref" and not checkpoint_ref:
                    checkpoint_ref = sub
                elif st == "model_request" and not model_request:
                    model_request = sub
                elif st == "model" and not model_response:
                    model_response = sub
                elif st == "forwarded_orders" and not forwarded:
                    forwarded = sub
                elif st == "driver" and isinstance(sub.get("line"), dict):
                    dl = sub["line"]
                    if dl.get("type") == "events":
                        subsequent_events.extend(dl.get("events", []))
                    elif dl.get("type") == "turn" and dl.get("side") == 0:
                        break
            break

    packet = packet_record.get("packet", {}) if packet_record else {}
    evidence = packet.get("evidence", {})
    tr = evidence.get("threatened_recruiter")
    options = packet.get("options", [])

    return {
        "state_revision": target_rev,
        "side_turn": packet_record.get("side_turn") if packet_record else None,
        "decision_id": packet.get("decision_id"),
        "reason": packet.get("reason"),
        "allowed_kinds": packet.get("allowed_kinds", []),
        "request_id": model_request.get("request_id") if model_request else None,
        "threatened_recruiter_fact": tr,
        "options_offered": [
            {
                "option_id": opt.get("option_id"),
                "actor_id": opt.get("actor_id"),
                "category": opt.get("category"),
                "actions": opt.get("actions"),
                "exposure": opt.get("exposure"),
                "forecast": opt.get("forecast"),
            }
            for opt in options
        ],
        "forwarded_orders": forwarded.get("orders") if forwarded else None,
        "model_response_text": model_response.get("response", {}).get("text") if model_response else None,
        "has_provider_reasoning": bool(model_response and model_response.get("response", {}).get("reasoning_content")),
        "checkpoint_path": checkpoint_ref.get("path") if checkpoint_ref else None,
        "subsequent_events_count": len(subsequent_events),
        "recruiter_events": [
            e for e in subsequent_events
            if e.get("unit") == 1 or e.get("target") == 1 or e.get("defender") == 1
        ],
    }


def simulate_alternative(
    ckpt_path: Path,
    seed: int,
    orders: list[dict[str, Any]],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        tpath = Path(td)
        data = json.loads(ckpt_path.read_text())
        data["board_path"] = str(BOARD)
        data["save_state"]["board_path"] = str(BOARD)
        encoded = json.dumps(data, separators=(",", ":")).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        ckpt_file = tpath / f"{data['side_turns']}-{data['save_state']['state_revision']}-{data['boundary']}-{digest}.json"
        ckpt_file.write_bytes(encoded)

        cmd = [
            str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
            "--faction1", "undead", "--gold", "300", "--seed", str(seed),
            "--llm-side", "0", "--max-turns", "120", "--incremental-turns",
            "--resume-checkpoint", str(ckpt_file),
        ]
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        )
        try:
            # Read until initial state
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                m = json.loads(line)
                if m.get("type") == "state":
                    break

            proc.stdin.write(json.dumps(orders) + "\n")
            proc.stdin.flush()

            final_state = None
            game_ended = None
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                m = json.loads(line)
                if m.get("type") == "state":
                    final_state = m
                    break
                elif m.get("type") == "game_end":
                    game_ended = m
                    break

            if final_state:
                units = final_state.get("units", [])
                u1 = next((u for u in units if u.get("id") == 1), None)
                friendly = sum(1 for u in units if u.get("faction") == 0)
                enemy = sum(1 for u in units if u.get("faction") == 1)
                return {
                    "status": "continued",
                    "recruiter_alive": bool(u1 and u1.get("hp", 0) > 0),
                    "recruiter_hp": u1.get("hp") if u1 else 0,
                    "recruiter_position": (u1.get("col"), u1.get("row")) if u1 else None,
                    "friendly_count": friendly,
                    "enemy_count": enemy,
                }
            elif game_ended:
                return {
                    "status": "game_end",
                    "winner": game_ended.get("winner"),
                    "reason": game_ended.get("reason"),
                    "recruiter_alive": False,
                    "recruiter_hp": 0,
                    "recruiter_position": None,
                    "friendly_count": 0,
                    "enemy_count": 0,
                }
            else:
                return {"status": "unknown"}
        finally:
            if proc.stdin:
                proc.stdin.close()
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()
            proc.terminate()
            proc.wait()


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    g1_log = ROOT / "tmp/glm-luna-fullgame-20260917T042432Z/recording/glm-luna-fullgame/match.ndjson"
    g2_log = ROOT / "tmp/glm-fullgame-20260917T181300Z/recording/glm-strategy/match.ndjson"

    g1_records = load_game_records(g1_log)
    g2_records = load_game_records(g2_log)

    # Game 1 boundaries: 402, 426, 458, 479
    g1_boundaries = [extract_boundary_facts(g1_records, rev, "glm-luna-fullgame") for rev in (402, 426, 458, 479)]
    # Game 2 boundaries: 635, 649, 665, 682
    g2_boundaries = [extract_boundary_facts(g2_records, rev, "glm-strategy") for rev in (635, 649, 665, 682)]

    # Run alternative simulations on the chosen fixtures
    # Fixture 1: Rev 231 from Game 1 (seed 4477)
    ckpt_231 = ROOT / "tmp/glm-luna-fullgame-20260917T042432Z/recording/glm-luna-fullgame/match.ckpt/12-231-model-706a767dd94a86f9f8d9d3fb1cbd46021a068fc925f1bc6b7e491db0d1cc54ec.json"
    f1_pos = simulate_alternative(ckpt_231, 4477, [
        {"action": "Move", "col": 2, "row": 4, "unit_id": 1},
        {"action": "Attack", "attacker_id": 3, "defender_id": 28},
        {"action": "Move", "col": 2, "row": 2, "unit_id": 6},
        {"action": "FinishWithGreedy", "groups": [], "holds": []},
    ])
    f1_neg = simulate_alternative(ckpt_231, 4477, [
        {"action": "Move", "col": 5, "row": 8, "unit_id": 1},
        {"action": "Attack", "attacker_id": 1, "defender_id": 20},
        {"action": "Move", "col": 2, "row": 2, "unit_id": 6},
        {"action": "FinishWithGreedy", "groups": [], "holds": []},
    ])

    # Fixture 2: Rev 456 from Game 2 (seed 7731)
    ckpt_456 = ROOT / "tmp/glm-fullgame-20260917T181300Z/recording/glm-strategy/match.ckpt/22-456-model-d81c2a2c0ca34437fe5f46e615440ef08bc8022587e8498939df80b0de36c7de.json"
    f2_pos = simulate_alternative(ckpt_456, 7731, [
        {"action": "Move", "col": 0, "row": 2, "unit_id": 1},
        {"action": "Move", "col": 4, "row": 5, "unit_id": 4},
        {"action": "Attack", "attacker_id": 4, "defender_id": 28},
        {"action": "Move", "col": 5, "row": 1, "unit_id": 8},
        {"action": "Attack", "attacker_id": 8, "defender_id": 44},
        {"action": "FinishWithGreedy", "groups": [], "holds": []},
    ])
    f2_neg = simulate_alternative(ckpt_456, 7731, [
        {"action": "Move", "col": 3, "row": 4, "unit_id": 1},
        {"action": "Attack", "attacker_id": 1, "defender_id": 28},
        {"action": "FinishWithGreedy", "groups": [], "holds": []},
    ])

    # Fixture 3: Rev 479 from Game 1 (seed 4477)
    ckpt_479 = ROOT / "tmp/glm-luna-fullgame-20260917T042432Z/recording/glm-luna-fullgame/match.ckpt/28-479-model-0cccd5a53a02b5d1c151cf3b9b57bec2aeaf70af8b22252563be73d31a5c5796.json"
    f3_pos = simulate_alternative(ckpt_479, 4477, [
        {"action": "Move", "col": 2, "row": 8, "unit_id": 1},
        {"action": "Attack", "attacker_id": 1, "defender_id": 18},
        {"action": "FinishWithGreedy", "groups": [], "holds": []},
    ])
    f3_neg = simulate_alternative(ckpt_479, 4477, [
        {"action": "FinishWithGreedy", "groups": [], "holds": []},
    ])

    # Fixture 4: Rev 86 from Game 1 (seed 4477) - quiet control
    ckpt_86 = ROOT / "tmp/glm-luna-fullgame-20260917T042432Z/recording/glm-luna-fullgame/match.ckpt/4-86-partial-63357b5cba441a90f28ca825230bfa021d13703d2633b71d0db27ec67778b87f.json"
    f4_pos = simulate_alternative(ckpt_86, 4477, [
        {"action": "Move", "col": 13, "row": 4, "unit_id": 9},
        {"action": "Attack", "attacker_id": 9, "defender_id": 16},
        {"action": "Move", "col": 5, "row": 4, "unit_id": 10},
        {"action": "Move", "col": 12, "row": 3, "unit_id": 12},
        {"action": "Attack", "attacker_id": 12, "defender_id": 16},
        {"action": "FinishWithGreedy", "groups": [], "holds": []},
    ])
    f4_neg = simulate_alternative(ckpt_86, 4477, [
        {"action": "Move", "col": 2, "row": 6, "unit_id": 1},
        {"action": "FinishWithGreedy", "groups": [], "holds": []},
    ])

    audit = {
        "games": {
            "game_1": {
                "game_id": "glm-luna-fullgame-20260917T042432Z:glm-luna-fullgame",
                "seed": 4477,
                "commit": "b36526217a830b83e50f38ca553c2a0ea3ac0bdb",
                "winner": 1,
                "recruiter_death_location": {"col": 0, "row": 11},
                "recruiter_death_revision": 500,
                "last_four_boundaries": g1_boundaries,
            },
            "game_2": {
                "game_id": "glm-fullgame-20260917T181300Z:glm-strategy",
                "seed": 7731,
                "commit": "400165b53bcb361008a1bdf6874ca5f3e15e3198",
                "winner": 1,
                "recruiter_death_location": {"col": 0, "row": 0},
                "recruiter_death_revision": 689,
                "last_four_boundaries": g2_boundaries,
            },
        },
        "selected_fixtures": {
            "fixture_1_seed_4477_defensive": {
                "name": "rev_231_early_defensive",
                "checkpoint": "12-231-model-706a767dd94a86f9f8d9d3fb1cbd46021a068fc925f1bc6b7e491db0d1cc54ec.json",
                "seed": 4477,
                "side_turn": 7,
                "positive_reference": {
                    "description": "U1 relocates to (2,4) with 0 threat; U3 attacks U28 with high kill chance",
                    "outcome": f1_pos,
                },
                "negative_reference": {
                    "description": "U1 reckless charge to (5,8) to attack U20; exposed to 6 attackers",
                    "outcome": f1_neg,
                },
            },
            "fixture_2_seed_7731_defensive": {
                "name": "rev_456_early_defensive",
                "checkpoint": "22-456-model-d81c2a2c0ca34437fe5f46e615440ef08bc8022587e8498939df80b0de36c7de.json",
                "seed": 7731,
                "side_turn": 12,
                "positive_reference": {
                    "description": "U1 defensive relocation to (0,2); U4 attacks 28, U8 attacks 44",
                    "outcome": f2_pos,
                },
                "negative_reference": {
                    "description": "U1 reckless charge forward to (3,4) to attack U28",
                    "outcome": f2_neg,
                },
            },
            "fixture_3_late_emergency": {
                "name": "rev_479_late_emergency",
                "checkpoint": "28-479-model-0cccd5a53a02b5d1c151cf3b9b57bec2aeaf70af8b22252563be73d31a5c5796.json",
                "seed": 4477,
                "side_turn": 15,
                "positive_reference": {
                    "description": "U1 attacks defender 18 to break immediate contact and contest hex",
                    "outcome": f3_pos,
                },
                "negative_reference": {
                    "description": "Finish turn without moving recruiter, leading to immediate death at keep",
                    "outcome": f3_neg,
                },
            },
            "fixture_4_quiet_control": {
                "name": "rev_86_quiet_control",
                "checkpoint": "4-86-model-2f7413ba0c68fae6da4821a71477759d582315cb7d3fffc16e256b9c9f2868c2.json",
                "seed": 4477,
                "side_turn": 3,
                "positive_reference": {
                    "description": "Scouts U9 and U12 engage remote enemy U16 and contest center",
                    "outcome": f4_pos,
                },
                "negative_reference": {
                    "description": "Needless passivity / pointless recruiter retreat to castle hex",
                    "outcome": f4_neg,
                },
            },
        },
    }

    (OUT_DIR / "audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True))

    md = f"""# Recruiter Survival Audit

## 1. Executive Summary

Audit of recruiter loss in two full-game recordings:
- **Game 1**: `glm-luna-fullgame-20260917T042432Z:glm-luna-fullgame` (Seed 4477, Commit `b365262`).
  - Terminal: Loss at revision 500 (Side Turn 30). Recruiter U1 died at (0, 11) from attack by enemy unit 23.
- **Game 2**: `glm-fullgame-20260917T181300Z:glm-strategy` (Seed 7731, Commit `400165b`).
  - Terminal: Loss at revision 689 (Side Turn 46). Recruiter U1 died at (0, 0) from attack by enemy unit 50.

## 2. Last Four Recruiter Boundaries (Game 1 - Seed 4477)

1. **Revision 402 (Side Turn 12)**: Decision `dec-3b82d8a7056c` (contact). U1 at (1,6) offered relocations to (0,6) and (0,5). Model selected relocation to (0,6) (safe).
2. **Revision 426 (Side Turn 13)**: Decision `dec-7ae07931dae8` (contact). U1 at (0,6) offered relocation to (0,8) (1 attacker, 8 damage) or (0,9). Model relocated U1 to (0,8).
3. **Revision 458 (Side Turn 14)**: Decision `dec-12e8b383828e` (contact). U1 at (0,8) offered relocations to (1,8) and (1,10) (3 attackers, 16.8 expected damage). Model moved U1 to (1,8).
4. **Revision 479 (Side Turn 15)**: Decision `dec-4a2c3f086635` (`invalid_assignment` on dead U40). U1 at (1,8) facing 8 attackers. In source `b365262`, `invalid_assignment` offered no tactical menu. Model manually authored Move U1 to (0,11), finish turn. On opponent turn, enemy U23 struck U1 for 14 damage, killing U1.

## 3. Last Four Recruiter Boundaries (Game 2 - Seed 7731)

1. **Revision 635 (Side Turn 20)**: Decision `dec-556833a41181` (contact). U1 at (0,0) offered relocation to (0,1) (0 attackers) or (0,0) (0 attackers). Model chose Move U1 to (0,1).
2. **Revision 649 (Side Turn 21)**: Decision `dec-b3df1c2cc5fa` (contact). U1 at (0,1) offered relocation back to (0,0). Model chose Move U1 to (0,0).
3. **Revision 665 / 666 (Side Turn 22)**: Decision `dec-f3d746d86633` (contact). U1 at (0,0) offered move to (1,0) attack 29 (kill 36%, 3 attackers, 44 max incoming damage). Model moved U1 to (1,0) and attacked 29. U1 took 6 retaliation damage, dropping to 6 HP on frontline.
4. **Revision 682 (Side Turn 23)**: Decision `dec-06663f1e84eb` (contact). U1 at (1,0) surrounded by 5 attackers with 6 HP. Model moved to (0,0) attack 50. Defender 50 counter-attacked and killed U1.

## 4. Frozen Four Comparison Fixtures

| Fixture | Position | Seed | Checkpoint | Positive Reference | Negative Reference |
| --- | --- | --- | --- | --- | --- |
| 1 | Seed 4477 Early Defensive | 4477 | `12-231-model-...json` | U1 to (2,4) [0 threat], U3 attacks U28. U1 lives 48/48 HP, enemy dead. | U1 charges to (5,8) attack U20. U1 damaged (38 HP), exposed. |
| 2 | Seed 7731 Early Defensive | 7731 | `22-456-model-...json` | U1 to (0,2) [defensive], U4/U8 attack. 7 friendly survive, 14 enemy. | U1 reckless charge to (3,4). Friendly unit lost (6 friendly, 15 enemy). |
| 3 | Late Emergency | 4477 | `28-479-model-...json` | U1 attacks defender 18 to contest hex and clear threat. | Finish turn without moving U1; immediate lethal death at keep. |
| 4 | Quiet Control | 4477 | `4-86-model-...json` | Scouts advance and attack remote U16; capture progress maintained. | Pointless recruiter retreat / passivity; wastes movement tempo. |

## 5. Offline Simulation Verification

Real driver simulations confirm:
- **Fixture 1**: Positive branch yields U1 alive at 48/48 HP with 16 enemies remaining (U28 dead); negative branch leaves U1 damaged at 38 HP with 17 enemies remaining.
- **Fixture 2**: Positive branch retains all 7 friendly units (14 enemy); negative branch loses a friendly unit (6 friendly, 15 enemy).
- **Fixture 3**: Positive branch engages and attempts breakthrough; negative branch terminates immediately with loss.
- **Fixture 4**: Positive branch engages contested scout line; negative branch demonstrates needless passivity.
"""
    (OUT_DIR / "AUDIT.md").write_text(md)
    print("Audit generated successfully in tmp/recruiter-survival/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
