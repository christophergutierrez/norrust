# choice_recovery fixtures

Checkpoints are CONTENT-ADDRESSED: each file must be named
`checkpoint-<sha256 of its exact bytes>.json`, or the driver refuses to resume it with
`game_end invalid_checkpoint` ("checkpoint digest mismatch"). Never edit a file in place
without renaming it to the new digest.

## checkpoint-469f81c0...json - ARCHIVE
Revision 219 of the recorded game `glm-luna-fullgame-20260917T000424Z`, copied verbatim.
This is the position where the model selected two attacks on U24 (20 HP); the first attack
killed it, and the engine rejected the whole batch at the second attack with
`UnitNotFound`: "target U24 was killed by earlier proposed action index 1 (zero-based);
batch replay is sequential".

## checkpoint-567f9b13...json - SYNTHETIC
The same revision 219 board with exactly ONE field changed: enemy U23's `hp` raised from
28 to 60. It is NOT a reproduction of a played position and must never be described as one.

Why it exists: the shared-target work must be shown not to outlaw LEGAL multi-attacks on a
target that survives. On the unmodified board no such proof is constructible - every pair of
attackers that can reach a shared target from distinct hexes deals combined maximum damage
greater than or equal to that target's HP, so the target may die and the batch's legality
would depend on combat rolls rather than on the rule under test. Raising one defender's HP
makes the survival deterministic: U11 (max 21) plus U13 (max 24) is 45 against 60 HP.

## checkpoint-d98880...json - ARCHIVE
Revision 377 of the same recorded game, copied verbatim. This is the position that ended that
run: U42 (6/31 HP) at (4,9) was ordered to (4,7), which the engine rejects as
`DestinationUnreachable`, and the single repair guessed (3,9), which is `DestinationOccupied`
by U34. The unit has exactly two legal endpoints, (5,8) and (5,10).

These are exercised by tools/test_strategy_validated_selections.py and
tools/test_strategy_movement_repair.py, which re-derive every number from the engine itself
rather than trusting these notes.
