# Decision annotations: implementation and evaluation plan

## Goal and scope

Record the model's stated rule, expected effect, and risk for its decisions,
linked to the exact response, engine revision, and submitted action indices.
Measure explanation coverage and compare claims with observed play. These are
model self-reports, not private chain of thought or proof of good tactics.

Use one end-to-end implementation stack: guide/prompt → model response → client
log → SQLite catalog → match report. Then run and review three games.
Commit this plan first; commit the fully tested implementation as one unit;
commit the evaluation report after the games. Do not commit unfinished layers.

KISS/YAGNI limits:

- Keep existing engine action JSON and game rules. No chess notation, new engine
  action fields, UI, evaluator framework, tactical scoring model, or extra calls
  solely to repair explanations.
- Keep the guide's current tactical advice for this first experiment. Add stable
  IDs and a short annotation instruction. Do not simultaneously rewrite strategy
  based on guesses. Later guide condensation is outside this execution plan.
- Ask models for annotations on every action response. Continue legal play when
  annotations are absent or malformed, but count that as missing/invalid evidence.
- Group related actions into one explanation; do not require prose per primitive.
- Preserve historical archives. Never populate missing explanations by inference.

## Fixed contract for implementation

The existing actions/intent/agenda envelope additionally accepts `decisions`:

```json
{
  "actions": [{"action":"Move","unit_id":12,"col":4,"row":6},
              {"action":"DoneWithImportantMoves"}],
  "decisions": [
    {"orders":[0],"rules":["S1","T1"],
     "expected":"Retreat U12 behind the screen.","risk":"Give up its attack."},
    {"orders":[1],"rules":["T7"],
     "expected":"Delegate remaining routine units; preserve the recruiter.",
     "risk":"Delegated destinations may expose units."}
  ]
}
```

- `orders` are zero-based indices into the submitted **authored** action array,
  before Engage expansion or generated greedy actions. Cover every action exactly
  once, including the finish or resignation. One group can cover many actions.
- An additional group with empty `orders` explains a consequential omission:
  holding healthy units, saving affordable recruitment, or declining an attack.
  Identify the units/resource in `expected`; a citation alone is insufficient.
- At most 16 groups, 256 total action references, 1–4 unique known rule IDs per
  group. `expected` and `risk` are nonempty strings, each at most 240 UTF-8 bytes.
  Reject invalid indices, booleans as indices, duplicate coverage, unknown keys,
  unknown IDs, excess length, and incomplete coverage as annotation errors.
- Keep guide policy paragraphs; label the old priority 0 as S1, old priority 7 as
  S2; priorities 1–6 as T1–T6, their four priority-3 subitems as T3.1–T3.4;
  priority 8 as T7; resignation as T8. Guide version is `tactics-v1`. Store its
  SHA-256 with each annotation record. Do not invent semantic rule aliases.
- Tool-only responses have annotation status `not_applicable`.
- Every completed `model_request` record stores the exact `prompt`, `raw_output`,
  `state_revision`, and `decision_annotation` object:
  `{status, guide_version, guide_hash, decisions, error}`. Status is `valid`,
  `missing`, `invalid`, or `not_applicable`; errors are bounded strings or null.
  Valid decisions are the validated list; other statuses use an empty list.
- Each `forwarded_orders` record carries an explicit `request_id`,
  `state_revision`, and the annotation belonging to **that exact final response**.
  A revised/repaired response replaces its draft annotation. Never attach a
  previous explanation to changed orders. Generated fallback orders use null
  request_id and `not_applicable` annotation status.
- SQLite keeps exact prompt/response blobs, valid annotation JSON in
  `reasoning_blob` (compressed UTF-8), `reasoning_kind=decision_annotation_v1`,
  `reasoning_source=model_response`, and explicit `annotation_status` and
  `state_revision` columns in model_requests. Non-valid reasoning blobs stay NULL.
  Populate existing request_id/before_revision fields on action_batches, and
  request_id on actions. Use explicit identities, never positional joins.
- Match report adds `decision_annotations` with `submitted_batches`,
  `valid_batches`, `missing_batches`, `invalid_batches`, `coverage` (valid / all
  applicable submitted batches, null for zero denominator), and `rule_counts`.
  Count the final submitted annotations, not discarded drafts or tool requests.
  This is explanation coverage, never tactical compliance or reasoning quality.

## Phase 0 — Reviewable plan

- [x] Commit this plan before starting implementation agents.
- Acceptance: plan states exact fields, ownership, test cases, commit gates, and
  final game conditions. No implementation changes in the planning commit.

## Phase 1 — One tested end-to-end stack

Start three Luna subagents at **medium** reasoning effort with disjoint ownership:

1. Client/contract agent: `tools/decision_annotations.py`, `tools/llm_client.py`,
   `tools/codex_backend.py` if its envelope instructions need changing,
   `tools/turn_agenda.py` if its envelope parser needs updating,
   `tools/test_decision_annotations.py`, `tools/test_llm_client.py`, and
   `docs/LLM_TACTICAL_PLAYBOOK.md`. Implement strict bounded annotation parsing,
   stable rule IDs, prompt guidance, and exact response-to-submission linkage.
2. Persistence/report agent: `tools/game_history.py`, `tools/match_report.py`,
   their existing test files, and `docs/GAME_HISTORY.md`. Add import, rationale
   storage, request linkage, idempotence, and honest coverage reporting using the
   fixed contract above. Existing approved rationale export should work with the
   stored annotation; no new export format.
3. Integration-test/documentation agent: new
   `tools/test_decision_annotations_integration.py`, `docs/LLM_CLIENT.md`,
   `docs/DEVELOPMENT.md`, `docs/TRAINING_DATA.md`. Build real-driver fixtures that
   exercise the complete stack, not merely parser mocks. No changes to files
   owned by other agents; coordinate through messages.

The parent reviews all code, fixes defects, and makes the stack commit. Agents
must not commit independent unfinished layers or launch games.

Measurable acceptance:

- [x] Parsing tests cover valid groups, omissions, invalid IDs/indices/UTF-8
  bounds, duplicate/missing coverage, malformed fields, and tool-only responses.
- [x] Valid orders execute unchanged even when annotation status is missing or
  invalid. No annotation fields reach the Rust driver. No explanation-only retry.
- [x] Draft confirmation, changed draft, malformed-review repair, action repair,
  tool follow-up, resignation, and generated fallback preserve the correct source
  annotation or explicitly record missing/not-applicable. Test these paths.
- [x] A real-driver annotated fixture records nonempty prompt/response payloads,
  valid rule IDs and guide hash, correct revision and request ID, and unchanged
  orders all the way into SQLite. Reimport twice; row counts and payloads remain
  unchanged. Verify the foreign-key graph and approved rationale export.
- [x] A negative fixture with missing/invalid annotations still plays legally,
  reports less than 100% coverage, and never invents rationale in the catalog.
- [x] Coverage excludes tools, discarded drafts, and generated fallback, and
  handles zero eligible batches without dividing by zero.
- [x] Run `python3 -m tools.fast_check` to completion. All Rust library/binary/
  non-balance integration tests, Python tests, and LuaJIT bridge smoke pass.
  `git diff --check` passes. Record commands/results in an ignored validation log.
- [x] Parent reviews the final diff and fixes issues. Commit the whole stack;
  verify the working tree is clean before games. Update this plan's checklist.

Validation completed: `python3 -m tools.fast_check` passed 234 Rust tests,
174 Python tests, the LuaJIT bridge smoke, and `git diff --check`. Log:
`tmp/decision-annotations-fast-check.log`. Parent review added response-linkage
regressions and fixed fallback attribution, conflicting response instructions,
parser edge cases, and historical hash preservation.

## Phase 2 — Three parallel Luna games and evidence review

- [ ] Read `docs/LLM_CLIENT.md`; build the release greedy_driver from the reviewed
  clean commit. Record the source commit and driver path in launch manifests.
- [ ] Start exactly three parallel Luna subagents, each supervising one isolated
  native Luna/high game using `tools.codex_backend`. Seeds 2001, 2002, 2003;
  big_battle_6; Undead vs Undead; 300 gold; model side 0; single-batch turns;
  max 50 completed side-turns (25 turns per player); resignation enabled.
  Use the same settings as the earlier three-game cohort where possible.
- [ ] Separate each log, checkpoint directory, session sidecar, request journal,
  prompt/result archive, stdout/stderr, and launch/exit record. Preserve the full
  canonical prompt. No replacement runs silently substituted for failed games.
- [ ] Supervise all three to terminal completion or a documented concrete failure.
  Do not count cap results, resignations, or infrastructure failures as wins.
- [ ] Import completed games into a cohort SQLite catalog, check integrity, and
  inspect the catalog before raw archives. Verify annotation and payload coverage
  against source logs. Requested model/effort are separate from runtime evidence.
- [ ] Review specific decisions using their stated rule, expected effect and risk,
  and engine observations. Distinguish unsupported belief, questionable tradeoff,
  missing explanation, and unfavorable sampled outcome. Do not claim that a rule
  citation proves compliance or that these three seeds establish causal improvement.
- [ ] Write and commit `docs/experiments/decision-annotations-evaluation.md` with
  a performance table: seed, outcome, completed model turns, model calls, wall
  time, annotation coverage, and an evidence-backed finding per game. Include
  source commit, evidence paths, missing data, and comparison limits. Raw archives
  remain ignored. Update this checklist and present the table to the user.

The plan is complete only when the reviewed implementation is committed, all
three attempts are accounted for, and the evidence-based evaluation is committed
and reported. A model's failure to supply annotations is a measured result, not
permission to manufacture explanations or keep rerunning until coverage improves.
