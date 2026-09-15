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
The two cells use different checkpoints, so a single `matched` bakeoff run is
rejected. Launch them as isolated one-cell manifests. Model
`accounts/fireworks/models/glm-5p3-flash`, one controlled turn, 100,000
tokens/cell, eight calls/turn, 500,000 aggregate stop. No baseline pair. Do not
claim a causal improvement.

Run path: `tmp/recruitment-efficiency-live-20260915T160000Z/`
Source: `f880634e6306e59fad64342bb8fb66aabdef0d09`
Driver SHA-256: `5fe667cca5c983477574c38dc0d86c2a72c55bc3dc5ca0613892728b6e1bad3e`
Rates: 2026-09-13 Fireworks GLM-5.3 Flash ($0.15 / $0.03 / $0.50 per million,
`reasoning_included_in_output: true`). Cache-write usage unknown.

| Cell | Calls | Tokens in/out/reason/total | Est. cost | Repairs | Recruiter | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| safe-travel | 1 | 8175 / 6869 / 6729 / 15044 | $0.004661 | 0 | U1 48/48 | 14 `castle_capacity` moves, 16 routine recruits, 0 exceptions. One policy reply freed capacity. |
| scout-replacement | 1 | 7383 / 1889 / 1722 / 9272 | $0.002052 | 0 | U1 48/48 | One initial policy with scout-role recruits; no later replacement, so missing-scout repair was not exercised. |

Both cells: `terminal_class=gameplay`, `reason=max_turns`, exit 0, coverage complete
except cache-write. Aggregate 2 calls, 24,316 tokens, about $0.0067. Under the
500,000-token stop. No combat. This is not a ranking and not a proof that
openings got cheaper.

Catalog IDs:
`recruitment-efficiency-live-recruitment-safe-travel-candidate:recruitment-safe-travel-candidate`
`recruitment-efficiency-live-recruitment-scout-replacement-candidate:recruitment-scout-replacement-candidate`

## Next experiment

Contact-efficiency 8-cell screening remains outstanding. Do not substitute these
openings for that evaluation.
