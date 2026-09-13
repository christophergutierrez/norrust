# Fix the watchdog failures exposed by the GLM run

Baseline: `d441582`. Implementation authorized: Luna High workers, orchestrated
by Astra. Preserve historical evidence. No new full player game in this task.

Implementation record (2026-09-12): recorder stack `d4e4e7f`; observer stack
integrated as `c093edb`, with validation documentation in `165c8c8`. Both Luna
workers passed their stack gates. The final integration result is recorded in
`tmp/watchdog-live-fixes-exec/HANDOFF.md`.

Live observer validation used 32 Fireworks requests and approximately $0.008419:
two calibration calls plus preflight and the 12 labelled cases. All responses
were usable. There were zero false stops and four missed loops: three direct
stop recommendations failed controller prerequisites, while one case received
continue decisions. The JSON protocol is verified; enforce quality is not.
Follow-up: align observer instructions and status with the controller's required
inspection/confirmation contract, then reevaluate without weakening guards.

## Evidence and outcome

The GLM run `tmp/glm-watchdog-test-nWAKkD` completed 12 side-turns before its
token budget stopped it. Its source NDJSON contains no malformed JSON, but 20
records exceed 64 KiB (largest 560,049 bytes). The watchdog splits such records
into fragments and loses progress observations. Both Nemotron observer calls
used 512 output tokens on prose, returned no verdict, and disabled observation.
Maintained examples also confuse backend model selection with player identity.

Fix those three issues. High GLM reasoning usage is a measurement, not a reason
to change tactics, player reasoning settings, game budgets or output escalation.
Keep recording/observe mode until an independent semantic quality gate passes.

## Execution and ownership

Two independent end-to-end stacks can run in parallel. Worker A owns recorder
source/tests in the main checkout. Worker B owns observer/profile/evaluation
source/tests and launch documentation in an isolated worktree from the plan
commit. Neither edits the other's files. Each runs focused tests and
`python3 -m tools.fast_check` against frozen tracked files, then commits its
complete stack. Astra reviews each diff, integrates B by cherry-pick after A,
and runs the combined full gate. Do not edit tracked files during a full gate.

Read AGENTS.md, docs/DEVELOPMENT.md, and relevant maintained source. Use existing
accounting and evaluation paths; no new agent framework, provider registry,
compatibility aliases, telemetry ledger, or runtime model fallback. Record
commands, results, commits and remaining limitations in
`tmp/watchdog-live-fixes-exec/HANDOFF.md` (Astra owns the combined handoff).

## Stack 1 — Faithful bounded recording

Owner A: `tools/run_watchdog.py` and recorder/supervisor regression tests.

Separate the 64 KiB I/O chunk from a named record-size safety limit (4 MiB is
adequate for the observed records). Parse complete NDJSON records only. Consume
records incrementally instead of accumulating the entire unread tail in a list.
Keep only the compact recent fields required by status construction, rather
than retaining hundreds of complete query/model payloads.

For an oversized record, bound retained memory, skip through its newline, report
an explicit coverage gap, and resume on the next record. Do not call fragments
malformed JSON. Preserve immutable source-byte evidence ranges and their
integrity checks. Persist enough cursor/discard state for partial writes and
restart; reset it correctly on truncation. Do not build a streaming JSON parser.

Acceptance:

1. Generated 70 KiB, 560 KiB and adjacent large valid records update progress and
   index correct original byte ranges with no false invalid-record warning.
2. Partial writes across polls/restarts, boundary-sized records, oversized lines
   with/without a newline, following valid records, truncation, and genuinely
   malformed JSON have explicit tests. Retained buffers and recent summaries
   remain bounded; a large source record is never emitted as partial JSON.
3. Real-client/fake-transport supervisor regression still reaches terminal state
   with accurate progress/usage and unchanged stop fences.
4. Read-only retrospective verification of the GLM source, using an isolated
   recorder output directory/copy, removes false parse gaps and recognizes its
   terminal state. Verify source hash unchanged; do not overwrite its old review.
5. Focused tests and full gate pass, then commit this stack.

## Stack 2 — A verified Fireworks observer and correct launch examples

Owner B: observer/profile/evaluation code and tests, docs/LLM_CLIENT.md and
maintained observer manifests. Do not change the player gameplay policy.

Keep strict JSON validation, 512 output tokens, the 30-second deadline, bounded
input, role-separated usage/cost receipts, failure caps and inspect/stop fences.
Fix the protocol failure through a model-specific setting/profile, not by
silently expanding output budgets or treating prose as a verdict.

Consult official Fireworks documentation. Generic `reasoning_effort=none` is a
documented API parameter but Nemotron support is unproven. A small explicitly
recorded probe may test it. If Nemotron still fails, the permitted alternate is
`accounts/fireworks/models/deepseek-v4-flash-0731` with `reasoning_effort=none`,
whose disabled-reasoning setting Fireworks documents. Select one demonstrated
profile; no automatic runtime fallback. Keep unverified settings distinguished
from verified model behavior. Preserve unknown reasoning usage as unknown.

Bounded live validation is part of this authorized fix, Fireworks only:

- At most four calibration calls total, each at most 512 output tokens and the
  existing 4096 estimated-input cap, 30 seconds, no retries. Require valid,
  nontruncated schema decisions on both a healthy packet and a nontrivial
  evidence packet before calling a profile protocol-ready.
- Only after that, run the existing preflight plus 12-case evaluation once,
  at most 37 additional calls. Maximum 41 physical calls overall; operational
  spend bound $0.10. Verify current rates first. With the permitted alternate's
  last checked $0.22/M input and $0.66/M output, the nominal no-cache envelope
  is about $0.051; input token estimation is not an exact tokenizer guarantee.
- Stop on credit/auth/config failure or any bound. No top-ups, extra candidates,
  unbounded retry loops, or full player game. Retain exact sanitized payloads,
  receipts, normalized usage/settings/source commit, and dated cost evidence for
  failures as well as successes. Reuse the existing ledger/evaluation machinery.
- A protocol pass is not a semantic-quality pass. Keep fixture labels and
  scoring unchanged; report missing judgments honestly. If both profiles fail,
  retain observe/record-only behavior and report the concrete unresolved block.

Correct maintained launch commands: provider selection is backend `--model`;
client `--player-model` records identity/expectation. Put the intended model in
both places. Remove erroneous client `--model` examples; do not add an alias.

Acceptance:

1. Fake HTTP tests cover exact profile payload, malformed/prose/truncated
   responses, errors and measured/unknown usage; preserve existing honest
   partial/failed evaluation reporting and distinct physical failure counts.
2. A launch-path fake transport test proves the selected GLM model reaches the
   actual backend payload and recorded identity. Document observer profile and
   actual quality status separately from player settings.
3. Focused tests and full gate pass, then commit the stack. Freeze the tested
   implementation before live validation; record the exact commit of each call.
   If live evidence requires a profile correction, test and commit that before
   rerunning within the same overall bound.
4. Report actual protocol and semantic results, per-role tokens/cost, physical
   request counts, coverage and failures. Never imply unrun cases passed.

## Final integration acceptance

Both stack commits are integrated and the combined full gate passes. The
handoff includes source commits, focused/full test counts, retrospective source
hash check, live observer receipts and quality limits, corrected launch example,
and any remaining issues. Point older active handoffs at it without rewriting
historical reports. A successful task fixes recording and launch selection and
demonstrates a bounded usable observer profile; an external failure is reported
as incomplete live acceptance, not disguised as completion.
