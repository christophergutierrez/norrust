# Strategy and routine execution: implementation and opening pilot

The implementation and bounded pilot were executed using Luna High workers.
Routine code can recruit, capture selected villages, and travel across turns
without another model call. The live pilot did **not** establish that the new
strategy interface improves GLM's efficiency or playing strength. Keep the
existing default mode unchanged.

## Implementation acceptance

| Slice | Accepted source / commit | Full gate |
| --- | --- | --- |
| Stack 2: committed progress, villages and rally | `8a7c060` / `c410ef2` | 969 Python tests, selected Rust suites, Lua checks |
| Stack 3: compact strategy and tactical interface | `68047d1` / `308d932` | 984 Python tests, selected Rust suites, Lua checks |
| Stack 4: comparison runner, accounting and offline matrix | `d177820` / `df17914` | 1,005 Python tests, selected Rust suites, Lua checks |
| Post-pilot: durable budget stop and explicit pricing semantics | `7f32c17` | 1,008 Python tests, selected Rust suites, Lua checks |

Gate logs are under `tmp/strategy-exec/`: `stack-2/luna-full-gate-2.log`,
`stack-3-full-gate.log`, `stack-4-full-gate.log`, and
`post-pilot-full-gate.log`. The standalone `stack-4-matrix-report.json`
passed all four offline cases. It proves actual village ownership, movement
across turns, changed recruitment/spending from different policies, deterministic
events for identical policy/seed, typed blocked/contact pauses without a hidden
Greedy fallback, and equal per-game table counts/hashes after repeated import.
GUI interaction was not manually tested; replay/browser headless checks passed.

## Frozen pilot

Source `df1791460271f5e4ed7c857463d4e2ed2278add9`; driver SHA-256
`5a3f4b12786c5e76eadd958be180a04601f57fc3bd778f4a6bca06c6db64f84f`.
Cohort and directory: `tmp/strategy-exec/pilot-20260913T234758Z/`.
The operator used tool session `19098`. Exactly three trials ran, including
two paid Fireworks model games. There was no paid observer, model
substitution, replacement game or post-failure rescue game.

Both paid cells used `accounts/fireworks/models/glm-5p3-flash`, provider-default
reasoning/temperature, `big_battle_6`, seed 2038, undead mirror, 300 gold, and
side 0 against Greedy. Caps: six engine side-turns (three controlled turns),
200,000 cumulative player tokens, eight logical model responses per controlled
turn, initial output 131072 with the existing exhaustion policy, model 900s,
turn 2100s, query 300s and automatic wall 2700s. Recording-only supervision had
zero restarts and durable five-minute heartbeats. A cumulative token cap permits
one in-flight overshoot; the final finished focused turn needed no further call.

| Treatment | Completed controlled turns | Physical calls | Input | Cached input (subset) | Output | Reasoning (subset) | Total tokens | Estimated cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Fixed strategy | 1 | 0 | N/A | N/A | N/A | N/A | N/A | $0 |
| GLM strategy | 2 | 8 | 81,854 | 10,240 | 133,730 | 132,993 | 215,584 | $0.07791430 |
| GLM focused | 3 | 7 | 93,864 | 36,864 | 130,224 | 125,567 | 224,088 | $0.07476792 |

The fixed policy requested three Skeleton army recruits, with no villages or
rally. It stopped with `fixed_policy_exception` at `objectives_complete`; that
is an expected refusal to invent new orders, not a gameplay defeat. It is a
small executor control, not an optimized opening policy.

Strategy GLM completed two controlled turns and made additional partial progress
before its next model dispatch hit the token ceiling. The live client raised
an uncaught exception, leaving no terminal marker. The original catalog still
correctly calls this archive incomplete. Its last renderable snapshot shows
side 0 owning `(2,4)`, `(5,3)`, `(6,11)` and both recruiters alive. These are
last-observed facts, not a terminal result. It executed 16 routine recruits and
17 routine moves. The client recorded nine logical request identities; only
eight reached physical inference, and the ninth was blocked by the budget.

Focused GLM completed three controlled turns at `max_turns`. Its terminal state
shows the same three side-0 villages and both recruiters alive. It executed 19
model-attributed recruits and 19 moves. Neither paid trial records a winner.
The comparison is censored because only focused completed the scheduled opening;
there is no valid percentage efficiency improvement or win-rate claim.

All three games exist under identical explicit IDs in both
`.norrust_history/history.sqlite` and the run-local `catalog.sqlite`:
`pilot-20260913T234758Z:strategy-opening-` followed by `strategy_fixed`,
`strategy_glm`, or `focused_glm`. Input/output/cache/reasoning/total usage is
measured for all 15 paid physical calls. Aggregate-only request IDs and
unassigned calls are empty. Cache-write usage remains unknown. Operator host
spending was not measured and is separate from these player costs.

## What the pilot exposed

1. **Fixed afterward:** strategy mode did not catch the pre-dispatch cumulative
   token-limit exception. It now writes the existing durable budget interruption
   and terminal record, exits 3, retains the open turn/request identity, and does
   not dispatch another provider call. A real-driver regression reproduces the
   installed-policy exception path; a second test covers typed provider failure.
   This changes future runs; it does not fabricate an ending for the pilot.
2. **Fixed afterward:** the dated rate configuration omitted
   `reasoning_included_in_output: true`. The generic cost calculator therefore
   correctly returned unknown. The configuration and regression are corrected;
   missing cache-write usage is not replaced with zero. Original reports and
   manifests remain historical evidence; `DERIVED_COST_SUPPLEMENT.md` records
   the corrected derivation from physical-call rows.
3. **Still a finding:** the routine screen produced four `unsafe_route`, one
   `no_executable_orders`, and two `contact` exceptions. Those pauses fit the
   deliberately conservative rules; this trial does not prove an engine defect.
   They still required expensive model reconsideration. The <=50,000 reasoning
   screening target was missed, and the completed-opening efficiency target was
   not met. There is no basis to weaken the threat checks silently.
4. **Small follow-up candidate:** one inspection response used a 237-character
   purpose against the existing 120-character limit and triggered repair. Make
   that bound clearer or reconsider whether this prose is needed in strategy
   mode. Do not rerun the pilot to hide the failure.

Estimated paid total: **$0.15268222**, using dated input/cached-input/output
rates of $0.15/$0.03/$0.50 per million and reasoning already included in output.
The calculation charges `(input - cached_input)` at the ordinary rate and cached
input once at its discounted rate. Fireworks documents these billing dimensions
in its [serverless pricing documentation](https://docs.fireworks.ai/serverless/pricing).
This is a reproducible estimate, not an invoice. The prelaunch conservative
two-cell ceiling estimate was $0.8815744, below the authorized $1 scope.

## Evidence and next decision

Read `tmp/strategy-exec/HANDOFF.md` for exact branches/commits and the current
resume state. Pilot evidence includes `launch.json`, `manifest.json`,
`RESULTS.md`, `pilot-findings.json`, `strategy-report.json`, usage sidecars,
supervisor heartbeats, catalogs and the derived cost supplement. The original
`RESULTS.md` attribution of unknown cost to cache-write usage was incorrect;
the derived supplement and this experiment record supersede that explanation.

No further paid trial is part of this execution. The next design decision is
whether to reduce avoidable exception/inspection response work, while retaining
authoritative safety checks. A larger full-game comparison needs its own scope;
three capped openings do not establish combat strength.
