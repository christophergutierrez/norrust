# GLM decision efficiency stack evidence

## Stack 4 — batched friendly inspections

Source before this stack: `c2e2118` (`docs(tactics): bound routine deliberation
and simplify hold guidance`). The agenda lifecycle prerequisite was integrated
from `a77d05be78c79732fac0c2190e626f23573f7e94` before the final gate.

The player-facing friendly inspection request is now
`{"tool":"inspect_units","unit_ids":[...]}`. Structural and live-roster
membership checks happen before fan-out. Dead, missing, and enemy IDs fail the
whole request without returning earlier results. Successful underlying driver
queries must all echo the same state revision. Choice handles from every
inspected unit are registered at that revision in both normal and repair paths.
The existing singular driver query remains an internal primitive; no Rust query
framework or second movement representation was added.

Evidence commands:

* `python3 -m unittest tools.test_action_choices tools.test_llm_client.ClientValidationTests.test_inspect_units_request_is_exact_and_revision_pinned tools.test_llm_client.ClientValidationTests.test_preview_round_trip_forwards_model_selected_candidate` — passed.
* `python3 -m unittest tools.test_action_choices_integration.ActionChoicesIntegrationTests.test_inspect_units_group_in_one_response tools.test_repair_execution.RepairExecutionIntegrationTests.test_engine_validation_repair_can_inspect_units_before_corrected_batch` — passed; eight friendly IDs used one player tool allowance and eight underlying queries in each real-driver fixture.
* `python3 tools/llm_client.py --help` — passed, confirming direct-script imports.
* `python3 -m py_compile tools/action_choices.py tools/llm_client.py` and `git diff --check` — passed.
* `python3 -m tools.fast_check` — passed: 580 Python tests, Rust checks, and
  Lua checks; durable output is in
  `tmp/glm-efficiency-exec/resume/stack4-full-gate.log`.

No paid model game was launched. No gameplay balance or engine query code was
changed. The maintained prompt cache baseline was regenerated for the grouped
inspection contract with source label `342d1b5+glm-stack1+glm-stack4`; its
cache layout, shared-prefix, and growth assertions remain covered by the full
gate.

## Stack 5 — nonfinal group movement

This stack adds the nonfinal `MoveGroupToward` action. It accepts one to eight
unique living friendly IDs and an in-bounds rally coordinate, attempts one legal
move per ID in submitted order, and returns moved or skipped results. The rally
is a direction and may be occupied; the action never attacks, recruits,
promotes, sweeps, ends the turn, or runs the opponent. Generated engine moves
retain delegated provenance and their authored macro index.

The real-driver fixture in `tools/test_movement_integration.py` runs the
recruit → nonfinal group movement (including a no-progress skip) → recruit →
movement → explicit finish sequence with both coordinate actions and choices
mode coordinate fallback. It verifies no opponent or unintended attack/end
events, decision annotations, SQLite import and reimport idempotence, action
rows, delegated source, and `delegated_order_index`. The next canonical prompt
contains the committed `skipped=U3:no_improving_destination` continuity fact.

Focused commands:

```text
cargo test --bin greedy_driver --manifest-path norrust_core/Cargo.toml
cargo test --test driver_protocol --manifest-path norrust_core/Cargo.toml
python3 -m unittest tools.test_llm_client tools.test_movement_integration tools.test_handoff_guide tools.test_prompt_cache_acceptance
```

The worker passed the full `python3 -m tools.fast_check` gate (560 Python
tests plus Rust and Lua). The combined stack-4/5 integration gate passed
583 Python tests plus Rust and Lua; its output is recorded in `tmp/glm-efficiency-exec/resume/stack45-full-gate.log`. The static prompt
contract was shortened to preserve the 16,500-byte cap: the largest minimal
fixture is 16,485 bytes. The stored cache fixture cases and historical prefix
ratchet are unchanged; expected contract bytes were regenerated for stacks
1+4+5. Cached input remains potentially billable.

Remaining limits: geometric progress is not a safety or route guarantee, and
the action does not plan around blockers. No paid model evaluation was run.
