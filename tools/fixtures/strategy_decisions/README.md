# Strategy Decision Boundaries Acceptance Matrix Fixtures

This directory contains deterministic real-driver fixtures for the 8 positions in the
Stack 4 Strategy Decision Boundaries acceptance matrix, plus the prepared Fireworks
screening manifest.

## Positions Covered

1. **repeated-current-contact** (`repeated_current_contact.json`):
   - Position: Friendly Skeleton 3 at (10,7), Enemy Skeleton 4 at (11,7).
   - Test: Context-invalid policy loop stops within the shared correction allowance; no policy/action mutation.

2. **proposed-dangerous-route** (`proposed_dangerous_route.json`):
   - Position: Scout 5 at (5,5) faces contact near village (5,3) due to Enemy Skeleton 4 at (5,4).
   - Test: Valid replacement objective (safe village at (2,4) or finish) removes the proposed incident.

3. **favorable-tactical-attack** (`favorable_tactical_attack.json`):
   - Position: Skeleton 3 (HP 34) at (10,7) vs wounded Enemy Skeleton 4 (HP 8) at (11,7).
   - Test: Selected legal attack commits; fixture-defined enemy HP reduction / kill is observed.

4. **withdrawal** (`withdrawal.json`):
   - Position: Recruiter 1 at (2,7) threatened by Enemy Skeleton 3 at (6,7).
   - Test: Selected legal move lowers exposure measure without killing the recruiter.

5. **independent-scout-movement** (`independent_scout_movement.json`):
   - Position: Skeleton 3 vs Skeleton 4 in contact; distant Ghost 5 at (2,5) assigned to safe village (2,4).
   - Test: Scout advances assigned objective before model call; tactical incident remains visible.

6. **blocking-unit** (`blocking_unit.json`):
   - Position: Friendly stationary unit at (2,4) blocks Ghost 5's assigned objective.
   - Test: Automatic move is refused; no hidden Greedy sweep.

7. **scouts-absent** (`scouts_absent.json`):
   - Position: Zero scouts on roster, zero gold in recruit queue.
   - Test: Structurally impossible village policy rejected before installation; state untouched.

8. **resume-at-decision-boundary** (`resume_decision.json`):
   - Position: Mid-turn checkpoint with 1 partial batch committed and pending contact decision.
   - Test: Clean resume; no renewed allowance, stale option execution, or duplicate actions.

## Deterministic Fake Transport

`fake_transport.py` executes canned responses for these matrix positions without contacting
an external LLM provider. Placeholders like `__FROM_PROMPT__` are dynamically resolved from
the stdin prompt.

## Fireworks Screening Manifest

`fireworks_screening_manifest.json` specifies the reviewable 16-cell screening schedule
alternating pre-decision-controller baseline `cb9a85b` against the accepted candidate across the 4 contact positions with
GLM Flash, dated pricing, 75k token caps, and a $1.20 USD conservative ceiling.

The withdrawal fixture was corrected before paid screening: the old adjacent-enemy
position had no lower-exposure endpoint. The replacement keeps the recruiter threatened
and permits withdrawal. The paired scorer in `tools.strategy_screening` measures
committed board effects equally for custom actions and engine-option selections.
