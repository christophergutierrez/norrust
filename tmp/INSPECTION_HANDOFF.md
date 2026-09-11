# Stack 4 inspection handoff

Commit: final stack4 commit with prescribed message
`feat(harness): batch friendly inspections for focused tasks` (hash supplied
with this handoff; the report avoids a self-referential commit hash).

The stack replaces the maintained player-facing singular friendly inspection
request with `inspect_units`, accepting one to eight unique living friendly IDs.
The client validates structure and the authoritative live roster before any
fan-out, rejecting dead, missing, and enemy IDs with no partial result. Each
underlying singular driver query is pinned to the same revision and successful
responses must echo that revision. Choice handles from all inspected units are
registered in normal and pre-submit repair paths. The driver primitive remains
internal and no Rust query framework was added.

Validation completed:

* `python3 -m unittest tools.test_action_choices tools.test_llm_client` — 162 passed.
* `python3 -m unittest tools.test_action_choices_integration tools.test_repair_execution tools.test_task_harness_matrix` — 13 passed.
* `python3 -m unittest tools.test_publish_reply tools.test_decision_annotations` — 27 passed.
* `python3 tools/llm_client.py --help` — passed, confirming direct-script imports.
* `python3 -m tools.fast_check` — passed: 580 Python tests, Rust checks, and
  Lua checks. Durable output is in
  `tmp/glm-efficiency-exec/resume/stack4-full-gate.log`.

No paid model game was launched. The parent prerequisite agenda lifecycle
commit `a77d05be78c79732fac0c2190e626f23573f7e94` was cherry-picked locally as
`134b3e6`; the parent should cherry-pick only the final stack4 commit reported
with this handoff because that prerequisite is already present in its branch.

The maintained prompt cache baseline was regenerated for source label
`342d1b5+glm-stack1+glm-stack4`; cache layout, shared-prefix, and growth
assertions remain enforced. The plan remains intentionally untracked at
`docs/plans/glm-decision-efficiency.md` and was excluded from the stack commit.
