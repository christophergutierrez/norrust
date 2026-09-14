# Strategy trial exact-progress benchmark

This is a read-only benchmark of the trial 3 turn-3 checkpoint. It uses the
original source and binaries from `ed6b765e24fb9e519751c8c8f723b59c1896cdd3`
and makes no model or provider calls.

The checkpoint is
`tmp/glm-strategy-20260914T213554Z/recording/glm-strategy/match.ckpt/4-84-model-702b5c92a8ec920e9f2ca3a1e35d288c4bac315b24ac1e9e507b8587b8a45fb2.json`.
The catalog and archive establish revision 84 as the start of controlled
turn 3. The installed policy is the `pol-f9e7f4ac4721` installation and its
committed progress is the empty applied-step ledger with scout IDs 3, 4 and 5.
The exact canonical payloads used by the query have these SHA-256 values:

| Evidence | SHA-256 |
| --- | --- |
| source commit | `ed6b765e24fb9e519751c8c8f723b59c1896cdd3` |
| policy | `ecb650e927541aee9da0b7a0b8c6e6531d4b57f9f9667c458cb96e66ef948fcf` |
| committed progress | `3aac9238b808934bc728fcec2232a17a1f8d036ff5ab6ac23a509fa904965cfe` |
| `routine_next` request | `9038fbe0e0a6f52294e1ee5e5a5050a7d5e9959349a190a272a00c698a93a232` |
| checkpoint file | `702b5c92a8ec920e9f2ca3a1e35d288c4bac315b24ac1e9e507b8587b8a45fb2` |
| initial state line | `d8d4fc5a49892b06220c85140df4e8c367814c4fa0b27e595d0598412257ba0e` |

The reusable query API is the driver protocol's read-only request:

```json
{
  "action": "Query",
  "what": "routine_next",
  "state_revision": 84,
  "policy": {
    "holds": [1],
    "rally": {"col": 10, "row": 6},
    "recruits": [],
    "reserve_gold": 30,
    "scouts": [3, 4, 5],
    "villages": [
      {"col": 2, "row": 4}, {"col": 5, "row": 3},
      {"col": 6, "row": 11}, {"col": 17, "row": 2}
    ]
  },
  "progress": {
    "recruited": [], "scout_assignments": [],
    "completed_villages": [], "scout_ids": [3, 4, 5],
    "installation_id": "pol-f9e7f4ac4721", "policy_complete": false
  }
}
```

The reusable runner is
`tools/benchmark_exact_routine_query.py`; its raw two-query output, including
the complete response bodies, is preserved in
`strategy-trial-followup-exact-progress-2026-09-14.raw.json`. It sends both
queries through one live driver process. Both replies reported revision 84 and
had the same full-body digest
`c253b9201d78a7adeb1631f76a1d30c8c48aff0664d9182f3cfe51730cd407b4`, while the
process stayed alive. This same-process equality and the unchanged checkpoint
are the direct query-purity/no-mutation checks.

The original release binary is
`ef5b81b70b75f11a9f0d66aacd293a14cb3d4738d6aa24f536900ae753fb74af`.
Five independent process starts all returned revision 84 in a median 4,278.7
ms (maximum 4,322.1 ms). Every result was the same complete routine action:
`Move(unit_id=6, col=8, row=7)`, reason `rally`, with no progress effects;
the independent-move pre and post tactical hashes were both
`1e98d6f02a187eb25efea7efb336484adc2a9c42fcdcc0c08a6146dfa60939db`.
The process remained alive after each reply, the initial state hash was stable
across all five runs, and the checkpoint hash was unchanged before and after
the benchmark. These are the no-mutation checks.

The original debug binary is
`974f99068c8893d2cba5090f5bbb54794ad0584019f427d26ec86ab7834c7e94`.
It reached the same revision-84 state in 91 ms, but did not answer the same
query within the 15,000 ms measurement bound and was terminated. This exceeds
the prior ten-second query target for the debug build. The release result is
within that target; the observed difference is consistent with the debug
binary's unoptimized routine computation. This is a benchmark failure to keep
visible before any paid launch, not an approximate replay or a widened budget.
