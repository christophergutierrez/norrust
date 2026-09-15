# Strategy recruitment efficiency

Candidate-only evaluation after Stacks 1–2. Stack 3 was skipped. Contact-efficiency
screening remains outstanding.

## Implementation

| Slice | Commit | Gate |
| --- | --- | --- |
| Stack 1: effective scouts and policy coordinates | `f274ad8e8ca328be5602ffc7f5b24a17d1706e45` | `python3 -m tools.fast_check` 1102 Python tests |
| Stack 2: capacity_relief and jammed-path travel | `869a063955c027648bdcb52fe25f06943dfc3dae` | `python3 -m tools.fast_check` 1110 Python tests |
| Stack 3: model-owned castle displacement | skipped (YAGNI) | Trial 7 rev 18/74 resolve via ordinary rally travel after the route fix |
| Stack 4 offline fixtures | this commit | fake-transport predicates; synthetic usage |

Trial 7 archives were not rewritten. Diagnosis: `tmp/recruitment-efficiency-exec/DIAGNOSIS.md`.
Observed blocked-recruitment cause was `no_route_endpoint` from a jammed shortest
path, not `rally_unreachable`. Release `routine_next` on those frozen checkpoints
returns `castle_capacity` (rev 18 max 0.055s, rev 74 max 1.328s, three samples).

## Offline fixtures

`tools/fixtures/recruitment_efficiency/`. Fake-transport usage is synthetic.
Corrupt finish cannot be scored as travel success. No-relief is not scored as
an impossible recruit.

## Live screen

Template: `tools/fixtures/recruitment_efficiency/fireworks_candidate_manifest.json`.
Two candidate-only cells, `accounts/fireworks/models/glm-5p3-flash`, one
controlled turn, 100,000 tokens/cell, eight calls/turn, 500,000 aggregate stop.
No baseline pair. Do not claim a causal improvement.

Live result: not yet run when this file was first committed.
