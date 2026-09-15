# Strategy trial follow-up acceptance — 2026-09-14

The integrated candidate is `5d1a7b88d83be6391533cfc685fa6441d90c64db`.
The architectural comparison baseline is `cb9a85bb932b57964c123ccbf9d3728ddbdbc492`.
This compares the full decision-controller change against the earlier strategy implementation; it does not isolate the effect of the latest small fixes.

## Offline acceptance

Luna High workers implemented action-state facts and atomic rejection feedback,
controlled-boundary attribution, threat estimate correction, and release runbook
updates. The integration owner added treatment-neutral scoring and corrected
an impossible withdrawal fixture before any paid outcomes were observed.

`python3 -m tools.fast_check` passed: 1,073 Python tests, all Rust suites, and
three Lua checks. The earlier mutable integration run had one transient
comparison-provenance assertion failure; focused checks and the complete
frozen-source rerun passed without weakening validation.

The trial-4 archive now reports three controlled and three opponent end turns,
zero unknown boundaries and no accounting mismatch. Original archives were
preserved. Exact trial-3 progress was reconstructed by adopting its recorded
batch proof; two candidate release queries returned identical revision-84
results in 5.025 and 4.972 seconds with the checkpoint unchanged.

Eight one-turn offline preflight cells passed with real drivers and fake
transports. These prove execution/scoring plumbing, not model quality.

## Predeclared screening

Sixteen cells: four positions, baseline/candidate, two repetitions; release
binaries, fixed seeds/settings/checkpoints, sequential launches. Each cell has
75,000 soft total tokens and a 15-minute wall deadline. New launches stop at
1.2 million measured aggregate tokens or missing usage/provider availability.
The dated Fireworks rates estimate a conservative exposure of $1.124288 after
allowing one final context-sized in-flight overshoot; this is not a hard bill cap.
The frozen packet and all evidence are under `tmp/strategy-trial-followup/`.

Useful actions are scored from committed driver events and resulting state,
not from the presence of a choose response. Invalid/missing decision ownership
cannot silently meet the zero-invalid-policy target. Failed cells count in
medians. Only a complete passing screen permits the opening comparison pair.

## Results

The full screen completed and failed its efficiency gate. Both arms scored
6/8 useful actions; candidate median total tokens were 43,264.5 versus
41,210.5 baseline (4.98% higher, against a target of 25% lower). All other
machine-scored targets passed. No additional opening games were launched.

| Treatment | Successes | Calls | Input | Output | Reasoning (inside output) | Total | Estimated USD |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 6/8 | 25 | 193,857 | 149,560 | 146,258 | 343,417 | $0.10164671 |
| Candidate | 6/8 | 25 | 207,931 | 149,059 | 146,346 | 356,990 | $0.10350731 |

Combined: 50 physical calls, 700,407 measured tokens, estimated $0.20515402.
Both treatments recorded 18,432 cached input tokens. The additional candidate
usage is mainly input; total reasoning differs by only 88 tokens. These
numbers do not show a material reasoning reduction from the controller.


## Per-cell outcomes

| Position | Repetition | Treatment | Useful target | Total tokens | Estimated USD |
|---|---:|---|---|---:|---:|
| favorable-tactical-attack | 1 | baseline | met | 25,771 | $0.007614 |
| favorable-tactical-attack | 1 | candidate | met | 68,381 | $0.021303 |
| withdrawal | 1 | baseline | missed | 63,111 | $0.016671 |
| withdrawal | 1 | candidate | missed | 30,807 | $0.009805 |
| independent-scout-movement | 1 | baseline | met | 35,995 | $0.009797 |
| independent-scout-movement | 1 | candidate | met | 58,961 | $0.016965 |
| repeated-current-contact | 1 | baseline | met | 28,816 | $0.009124 |
| repeated-current-contact | 1 | candidate | met | 34,081 | $0.008518 |
| favorable-tactical-attack | 2 | baseline | met | 46,426 | $0.014385 |
| favorable-tactical-attack | 2 | candidate | met | 49,042 | $0.015655 |
| withdrawal | 2 | baseline | missed | 70,676 | $0.024627 |
| withdrawal | 2 | candidate | missed | 29,189 | $0.008997 |
| independent-scout-movement | 2 | baseline | met | 22,138 | $0.005707 |
| independent-scout-movement | 2 | candidate | met | 45,499 | $0.010281 |
| repeated-current-contact | 2 | baseline | met | 50,484 | $0.013721 |
| repeated-current-contact | 2 | candidate | met | 41,030 | $0.011984 |

## Accounting and evidence

Input, output, reasoning, cached-input and total usage are fully measured.
Cache-write input remains UNKNOWN for all 50 calls. Unassigned calls: 0;
aggregate-only request IDs: 0. Reasoning is already included in output and
is not charged twice. Estimated cost uses the packet's dated Fireworks rates;
it is not an invoice and excludes coding/orchestrator inference.

Every cell is imported into its local catalog and the default catalog under
cohort `strategy-screen-20260914T233929Z`; full game IDs append `:` and the
cell ID listed in `screening-runs/summary.json`. These are one-turn positions,
not wins in complete games against Greedy. The source and binary hashes,
predeclared cases, rates and settings are frozen in `screening-packet.json`.

The withdrawal fixture admits a lower-exposure retreat but begins with a
full-health recruiter (48/48), 300 gold, and a keep. A retreat target miss
alone does not establish bad strategy; holding/recruiting may be defensible.
The scorer's precomputed exposure proof also requires other actors not to
change. Post-run review must distinguish target misses from proof gaps and
bad play. No outcomes or fixtures were retuned after paid dispatch.

## Post-run review and limits

Luna's bounded review found no runner, parsing, rejected-action, stale-action,
duplicate-action, budget or engine failures. All cells ended at `max_turns`
with their recruiters alive. Candidate had zero unknown or forbidden policy
installations. Baseline had 15 installations without decision-packet evidence;
those remain unknown, not proof of invalid behavior.

All four withdrawal misses were six recruits followed by a selective finish
with empty groups: the recruiter held its keep and no retreat was attempted.
No valid retreat was rejected by the scorer. The candidate withdrawal packets
had four options: two attacks and two zero-exposure relocations. The two
relocations were equivalent on recorded exposure/cost, but this targeted review
does not support blaming a large redundant menu for the withdrawal result.

The no-progress, parser-recovery and stale/duplicate rejection paths did not
trigger here. Their negative-path evidence remains the offline tests. This
screen supplies no additional live validation of those guards. Nor does a
one-turn screen establish a full-game win rate against Greedy.

The implementation fixes are accepted; the hoped-for efficiency improvement
is not established. No opening pair was run. Before another experiment, define
whether withdrawal measures an explicitly requested retreat or broader safe
play, and freeze that distinction before outcomes. Do not reinterpret these
misses as evidence that legal recruitment was wrong, or retune this cohort.

Detailed bounded per-call review: `tmp/strategy-trial-followup/SCREENING_FINDINGS.md`.
Authoritative default-catalog CLI reports for all 16 games: `usage-cli/` under
the same task directory. Full gate log: `frozen-gate.log`.
