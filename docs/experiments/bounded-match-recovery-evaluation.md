# Bounded match recovery evaluation

Source implementation commit: `9fb04168a2db96ab2697d82b9f248b8ab9aa9c51`.

The archived seed 2001 attempt stopped at revision 286 after ten completed side
turns when a draft delegated dead U21. The resumed attempt restored that exact
checkpoint and used a separate continuation tree under
`tmp/luna-final-20260907/seed-2001/continuation/`.

| Measure | Result |
|---|---:|
| Scenario / seed | `big_battle_6` / 2001 |
| Model side / opponent | 0 / Greedy with driver recruitment |
| Cap | 50 side turns |
| First restored revision | 286 (10 side turns) |
| Outcome | Luna win (winner 0, recruiter loss rule) |
| Final engine revision | 440 |
| Completed side turns | 21 (11 resumed) |
| Native model calls | 17 |
| Driver queries | 23 |
| Invalid candidate repairs | 1 bounded repair (dead-U21 preview) |
| Draft-review repairs | 1 |
| Committed batches | 6 |
| Process restarts | 0 |
| Checkpoints in continuation | 12 |
| Measured wall time | 715,079 ms |

The first resumed draft reproduced the historical `unauthorized_unit` error;
the client retained the live revision, gave one repair, and executed the
corrected batch. No action involving dead U21 was forwarded. Six forwarded
batches had valid annotations, and the continuation reached a gameplay win
without exceeding the 50-turn cap. Native runtime
model and reasoning telemetry remained unreported by the backend; requested
settings were `gpt-5.6-luna` at high effort.

The full gate passed: 216 Python tests, Rust library tests, Lua bridge smoke,
and `git diff --check`. The real-driver revision-286 repair test and a real
subprocess supervisor signal/restart test are included. Fault windows involving
native crashes during later boundaries were not injected into this live match;
the continuation therefore demonstrates the historical repair and clean
completion, rather than universal crash-recovery coverage.

A fresh catalog import of the original and continuation logs is retained at
`tmp/luna-final-20260907/seed-2001/continuation/recovery-history.sqlite`; it
contains two imported archives and passed SQLite integrity and foreign-key
checks.
