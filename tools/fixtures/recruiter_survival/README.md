# Recruiter Survival Fixtures

Tracked, relocatable test fixtures for the four frozen recruiter survival evaluation positions.

Each fixture contains:
- `checkpoint.json`: The complete engine checkpoint, with `board_path` set to `__SCENARIO_BOARD__`.
- `metadata.json`: Provenance, scenario configuration, installed policy, progress, and historical state revision.

## Fixtures

1. **`fixture_1_seed_4477_defensive`**:
   - **Historical source**: Seed 4477, revision 231 (Side Turn 7).
   - **Situation**: Early tactical contact with enemy advance. Recruiter U1 is forward.
   - **Positive reference**: U1 retreats to safe village/hex (2,4) with 0 threat; U3 attacks enemy U28 with high kill chance and 0 retaliation. Recruiter remains 48/48 HP; U28 is eliminated.
   - **Negative reference**: U1 makes a reckless charge to (5,8) to attack enemy U20; suffers retaliation damage (down to 38 HP) and stays exposed to 6 distinct attackers.
   - **Stack 4 reference**: `stack4_reference.json` freezes the current revision-231
     contact option IDs and the two bounded candidate selections. The archived
     option exposure rows provide occupied-board counts; open-board counts are
     explicitly unknown for this packet and are never treated as zero.

2. **`fixture_2_seed_7731_defensive`**:
   - **Historical source**: Seed 7731, revision 456 (Side Turn 12).
   - **Situation**: Frontline engagement. Recruiter U1 is supported by 6 friendly units.
   - **Positive reference**: U1 moves defensively to (0,2); U4 and U8 execute attacks on enemy units 28 and 44. All 7 friendly units survive through the opponent turn; enemy forces are reduced to 14.
   - **Negative reference**: U1 charges forward to (3,4) to attack U28, drawing focus from 7 attackers; friendly forces lose a unit (6 friendly survive).

3. **`fixture_3_late_emergency`**:
   - **Historical source**: Seed 4477, revision 479 (Side Turn 15).
   - **Situation**: Recruiter U1 is at the keep (2,7) surrounded by 8 enemy attackers, facing 112 max incoming damage. Stale policy assignment on dead unit 40.
   - **Positive reference**: Model selects a tactical action (e.g. attack defender 18 or relocate) attempting break-out.
   - **Negative reference**: Stand still / finish turn without moving recruiter; recruiter is killed on the immediate opponent turn.

4. **`fixture_4_quiet_control`**:
   - **Historical source**: Seed 4477, revision 86 (Side Turn 3).
   - **Situation**: Scouts U9, U10, U12 make remote contact with enemy scout U16 near center.
   - **Positive reference**: Scouts advance and engage enemy scout, securing map presence.
   - **Negative reference**: Needless passivity / recruiter panic retreat, wasting tempo and movement.
