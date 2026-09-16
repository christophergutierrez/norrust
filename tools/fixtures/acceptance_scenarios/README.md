# Strategy Quality Acceptance Scenarios

This directory contains deterministic real-driver fixtures for the 3 acceptance
scenarios in Stack 6:

1. **initial_allocation**:
   - Initial 300-gold allocation on `big_battle_6`, seed 4477, side 0 (Undead vs Undead).
   - Expected evaluation checks cover requested spending, reserve intent, feasible scout
     coverage, and army adequacy.
   - Screening predicate: Authorizes at least 200 gold of affordable recruitment in this
     300-gold opening with reserve_gold <= 100 and feasible scout/army composition.

2. **completed_queue**:
   - Boundary at engine side turn 2 where the initial small recruitment queue has
     completed and idle gold remains above reserve with remote contact present.
   - Checkpoint: `checkpoint.json` (boundary: `model`, side_turns: 2).
   - Companion journal: `journal.ndjson` (pre-decision trajectory).
   - Screening predicate: Valid replenishment reaches actual routine recruit commits
     (behavior: `replenished`, passed: true), or explicit deliberate saving is reported
     as a behavioral choice (behavior: `saved`, passed: false).

3. **precharge_recruiter**:
   - Boundary at turn 6 (side turns 10, state revision 184) where the recruiter (Unit 1)
     is at (2,7) facing contact with advancing enemy Dark Adepts.
   - Checkpoint: `checkpoint.json` (boundary: `model`, side_turns: 10).
   - Companion journal: `journal.ndjson` (pre-decision trajectory).
   - Screening predicate: Chosen action retains recruiter survival through the frozen
     opponent continuation. A legal but losing advance (such as charging into (6,6))
     fails this quality predicate.
