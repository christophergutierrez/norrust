# GLM diagnostic corrections: execution and retest

Implementation in progress. The user authorized the
[phased plan](../plans/glm-followup-corrections.md), Luna implementation and one
fresh paid GLM Flash diagnostic. No new paid request has been launched yet.

## Baseline and evidence

Baseline source: `85373d4e0e12e742977967f2284e2ec5a234309c`;
plan-only commit: `14265b3`. The full headless gate passed on that checkout:
609 Python tests, Rust library/binary/named integration suites, and Lua bridge,
replay and recorded-game tests. Interactive GUI acceptance is separate.

Prior game: `d03b99d74969fd764077ae4823c9ea5a`, archive
`tmp/quick-play-glm-efficiency-xbsjhb82/`. Its read-only catalog inspection and
hashes of all 220 original files are saved under `tmp/glm-followup-exec/`.
Historical acceptance operates on a copy and must leave those originals intact.

The previous game stopped on request25 with HTTP504 after600.52 seconds;
neither side won. Five controlled-side turns completed, with a partial sixth.
Known24-call usage: input317522, cached input135168 (input subset), output676392,
reasoning660682 (output subset), total993914. Failed-call usage and cost unknown.
The old catalog leaves17 calls without a turn, despite preserved request contexts.
It also misses the failure outcome and reports misleading complete usage coverage.

## Integrated stacks

Stack 1 integrates Luna contract/repair and rejected-intent corrections:
separate bare-tool/action contracts, a shared bounded repair path, explicit
model-call accounting, committed task context, and readiness flags distinguished
from actual attack coverage. Promotion missing/empty semantics are retained.
The guide grew248bytes (+4.94%). Focused checks and the cumulative gate passed: 622 Python tests plus Rust
and Lua suites (`tmp/glm-followup-exec/stack1-fast-check-pass.log`).

The initial integration checks caught prompt size regressions and stale maintained
cache/promotion fixtures. Luna shortened duplicate protocol text and refreshed
those fixtures without raising size limits or weakening the historical cache
prefix ratchet. Additional review caught unbounded tool-followup model calls and
rejected intents leaking into committed memory; regression tests cover both.

Stacks2–4 remain to be integrated. Their worker handoffs and focused results are
in `tmp/glm-followup-exec/stack2-handoff.md`, `stack3-handoff.md`,
`stack3-review-handoff.md`, and `stack4-handoff.md`.

Historical scratch acceptance already reproduces25requests/25calls,24measured,
all25turnlinks,22renderable snapshots,307events, and zero unattached reviews.
Totals remain input317522/output676392/reasoning660682/total993914. Failure code
is `model_backend_failure`, elapsed7569799ms, final proven revision277, measured
usage partial. Reimporting twice preserves counts/links/totals with clean database
integrity. The original archive and catalog hashes are unchanged.

## Paid diagnostic

Pending completion and validation of all four implementation stacks. One new
game will retain the previous scenario, factions, seed, budgets and provider
sampling/reasoning defaults, using the maintained streaming evidence recorder.
This combined retest is descriptive; it cannot isolate which change caused a
behavioral difference. Raw provider reasoning and decision annotations will be
reported separately, and missing measurements will remain unknown.
