# Promotion choices and purposeful handoffs

## Scope and evidence

Implement the concrete findings from the September 6 grounded-decisions games:
seed 2003 deferred U13's promotion because the compact prompt omitted the
engine's `advances_to`; seed 2001 revision 270 delegated its recruiter while
claiming it would stay on the keep; losing players repeatedly froze ranged
support and healthy armies under generic formation reasons.

Keep this small: existing action/annotation/agenda schemas, driver rules,
request budgets, and SQLite tables stay in place. Add factual prompt fields and
replace ambiguous guide wording. Do not infer safety from prose, automatically
rewrite orders, enforce attack quotas, or add another model review call.

This task implements and verifies code using Luna coding subagents. It does not
run paid model games or claim tactical improvement from deterministic tests.
The previous opening-only A/B experiment did not test midgame holds; retain its
archives and document that limitation rather than treating it as a valid policy
comparison.

## Phase 0 — Plan

- [x] Write this plan before implementation.
- [x] Commit the plan; assign bounded work to Luna at medium reasoning effort.
      Plan commit: `4bbdecc`.

## Stack 1 — Promotion facts reach executable actions

Files: `tools/llm_client.py`, focused client tests, a real-driver integration
test/fixture, and `docs/LLM_CLIENT.md` / `docs/DEVELOPMENT.md`.

1. Include pending friendly units' engine-supplied promotion choices in the
   compact board. Preserve exact definition spelling and original zero-based
   index order; distinguish a missing choice list from a supplied empty list.
   Never invent a target or suggest that a non-pending unit may advance now.
2. Show complete valid Advance examples using exactly one of `target_index`
   or `def_id`. Explain pending state and refer to the supplied choices.
3. Create a small reproducible fixture from the archived promotion boundary.
   Record source game/revision and source checkpoint hash. Tests must run from
   a clean checkout without ignored archives or a native model backend.

Acceptance:

- [x] Generated compact prompts retain exact ordered choices, pending state,
      and both valid action forms. Missing/empty/multiple choices and the
      non-pending case have meaningful coverage; diagnostic state is retained.
- [x] A real client/driver test restores the fixture, reads the promotion choice
      from the canonical prompt, submits Advance, and verifies the resulting
      unit type/level, pending state, and revision using actual engine state.
- [x] The fixture's exact delivered prompt, response, submitted action, request
      link, and revision survive NDJSON and a temporary SQLite import.
- [x] Parent reviews the diff and fixes defects; `python3 -m tools.fast_check`
      executes the new real-driver test without skips and passes; `git diff
      --check` passes. Commit this complete stack and record its hash below.

Stack 1: `271f857`. Full gate passed (191 Python tests, Rust suites, LuaJIT).
The restored single-batch fixture advances U13 from revision 383 to a promoted
Bone Shooter at revision 385 after Advance and selective finish. Source archive
dependencies are replaced by a relocatable committed checkpoint, with provenance
and board hash retained. Parent review corrected the selector instructions,
added side-1/diagnostic coverage, and verified final-response linkage.

## Stack 2 — Explicit handoff facts and coordinated support

Build on stack 1. Files: existing handoff audit/review rendering in
`tools/llm_client.py`, focused/integration tests, tactical guide and client docs.

1. Extend the existing draft handoff summary with factual selective boundary
   categories: explicit delegated IDs, explicit held IDs, omitted friendly IDs,
   and explicitly delegated recruiter IDs. Label the categories as boundary
   instructions, not predictions of final positions or a safety certificate.
   Do not label automatic finish eligibility as explicit delegation. Earlier
   authored actions, recruitment vacates, and opponent effects remain possible.
2. Place those facts in the existing review request, preserving final live-state
   reminder placement, exact prompt logging, and existing call/query budgets.
   Existing records should retain the final submitted orders and annotations.
3. Replace S1/T4/T7 wording with a concise policy: rescue or guard specific units,
   advance support with the frontline, and let routine healthy units contribute.
   Each consequential hold should name its current job, action/pressure forgone,
   and a release condition using existing reason/expected/risk fields. A useful
   attack need not independently kill; compare coordinated attacks and enemy
   response. Retain justified guards and avoid mandatory sweeping.
4. Clarify T8: material disadvantage alone does not establish hopelessness;
   explain why recovery fails using live facts. Keep immediate resignation legal
   with no extra call or parser evaluating tactical prose.

Acceptance:

- [x] A selective example with a recruiter in groups, a separate held unit, and
      an omitted unit renders all categories correctly despite contradictory
      intent/agenda text. Automatic and partial boundaries are labeled honestly.
- [x] A restored real midgame fixture verifies that explicit recruiter
      delegation can move it, whereas holding it retains its finish position;
      a distinct delegated healthy unit and a distinct omitted/held guard obey
      the submitted boundary. Check model-side events before opponent effects.
- [x] Existing review flow delivers the summary; response revisions update it
      where applicable, and final annotations/order links survive NDJSON/SQLite.
      No new explanation-only call or automatic order alteration is introduced.
- [x] Maintained JSON examples validate through actual action/annotation/agenda
      parsers. Guide UTF-8 size is at most the pre-change 11,019 bytes; stable
      tactic IDs and all budgets remain unchanged.
- [x] Parent reviews the complete diff and fixes defects; full fast check and
      diff check pass. Commit this stack with docs and tests together.

Stack 2 verification: full gate passed (202 Python tests, Rust suites, LuaJIT),
including both real-driver fixture tests without skips. The guide is 10,908
UTF-8 bytes. The seed 2001 fixture receives exactly two model requests in each
branch (draft and existing review); delegating U1 moves it from (2,7) to (2,5),
while holding it retains (2,7). U5 attacks in both branches; held U6 and omitted
U4 remain in place through the boundary, before any opponent actions.

Parent review added final-order audits to both submission paths, corrected the
original-candidate digest, strengthened execution and SQLite assertions, parsed
the maintained documentation examples, and updated old guide wording checks.
All three Luna coding assignments were reviewed. These deterministic backends
verify delivery and execution, not whether Luna follows the guide or wins more.

## Completion

- [x] Report commits, verification counts, and any behavioral limitations.
- [x] Correct prior evaluation call counts (36/29/33) and describe seed 2003's
      recruiter-kill win accurately. Do not claim model improvements were tested.

Future behavioral evaluation, if requested, must restore and verify actual
midgame checkpoints before freezing cases. Repeated revision-0 openings cannot
assess promotion decisions, broad holds, recruiter safety, or resignation.
