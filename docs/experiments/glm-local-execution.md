# Reliable inspection and local execution: execution record

Status: all three implementation stacks tested; paid retest pending source freeze.
Plan: [glm-local-execution](../plans/glm-local-execution.md), committed as
`21c30a0` before three Luna High workers began in isolated worktrees.
Baseline source: `90e35f7`; prior game `acf48862062d7233448b750b762b6216`.

## Implementation and validation

Stack 1 (`7ea0967`) corrects terrain-owner village trends, current-turn readiness,
nullable threat semantics, direct/open exposure scope and coverage, and explicit
selective finishing. The cumulative gate passed 687 Python tests plus the
supported Rust library/binary/integration and Lua checks. A stale test assertion
was corrected to distinguish a supplied nonlethal bound from missing data.
Real-driver tests cover village totals at two boundaries and a held unit moving
on the next turn. Maintained schemas and engine mechanics are unchanged.

Stack 2 (`a598c83`) preserves recognized inspection requests through bounded
syntax repair without executing a JSON prefix, and surfaces a sampled friendly
casualty through the existing review. Its cumulative gate passed 699 Python
tests plus the supported Rust/Lua checks. The real revision-338 fixture has
`exposure=None`, sampled casualty U19, no other audit trigger, and exactly one
review. Confirmation and replacement both commit once from the original live
revision; catalog review links and idempotent import are checked. Repeated
malformed tool output stops without dispatch, and existing final-only and
budget restrictions remain authoritative.

Stack 3 replaces the focused post-inspection dynamic context with selected exact
options, task provenance, current readiness, and compact global guardrails.
Fresh inspection replaces local context; unavailable results clear it; rollback
retains live revision; accepted progress restores objective selection. Preview
and repair results remain visible, and local data retains untrusted framing.
The stable prefix, final live reminder, token accounting, byte cap, and output
retry behavior remain intact. Omitting agenda retains unshown tasks; supplying
it still replaces the full object. The initial cumulative gate exposed an outdated scripted test player: after
inspection it relied on removed global briefing rows and either re-recruited or
re-inspected indefinitely. Its maintained caller now consumes local options, with the existing matrix
objectives and budgets preserved. A stale canonical wording assertion was also
corrected. The final cumulative gate passed 708 Python tests, the supported
Rust library/binary/integration suites, Lua bridge/replay/catalog tests, and
`git diff --check`. All 24 offline matrix cells completed/imported/reported.
No interactive GUI acceptance is claimed.

Independent Luna audits and parent integration caught and corrected fenced-tool
repair regression, stale unavailable-inspection context, discarded preview
results, duplicate or incorrectly scaled guardrails, and dropped readiness.
Audit files and worker handoffs are under `tmp/glm-local-exec/`.

The real-driver byte comparison measures 44,038 bytes for local execution versus
48,424 for the full-context followup with the same inspection byte length and one
budget/live footer: 4,386 fewer bytes (9.06%). This is a structural comparison,
not measured token savings or model reasoning improvement. The largest maintained
small fixture is 18,493 bytes, below the unchanged 18,500-byte ceiling; the playbook
ceiling is unchanged. Evidence: `local-prompt-size-comparison.json` and
`final-prompt-sizes.json` in the execution directory.

## Retest protocol

One fresh maintained streaming Fireworks run, model
`accounts/fireworks/models/glm-5p3-flash`, scenario big_battle_6, seed 771125826,
Northerners/Loyalists, 300 gold, side 0, focused/choices/incremental, 50 side-turn
cap, and 1,000,000 measured total tokens. Provider-default sampling/reasoning and
128k-to-512k output exhaustion policy are unchanged. The between-call game
ceiling may overshoot by the last in-flight response. No automatic extra run.

Freeze source after all code gates and commits. Preserve isolated logs,
checkpoints, journal, sidecar, canonical prompts/payloads and raw SSE receipts.
Baseline hashes cover 710 historical files. Observe reasoning and actions, then
reconcile the terminal archive with SQLite, export replay, and import the normal
replay catalog. Missing evidence remains unknown. Complete usage, cost, game
outcome and request-specific findings will be recorded here after termination.
