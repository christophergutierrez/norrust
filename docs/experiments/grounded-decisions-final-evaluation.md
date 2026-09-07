# Grounded decisions final cohort

The selected clean revision was `a6c368f58890bf2e2de2b2edf66046e192f7e31b`
(variant A). It was built with the release `greedy_driver`; all three games used
`big_battle_6`, Undead versus Undead, 300 gold, side 0, single-batch turns, and
a 50-side-turn cap. Each game had its own log, checkpoint directory, native
request artifacts, and Codex session sidecar. The requested native settings were
Luna with high reasoning effort.

The SQLite-first import contains three complete games, six players, 31 side
turns, 98 model requests, 33 submitted batches, and 107 authored actions.
`verify_history` reports integrity `ok` and zero foreign-key errors. Runtime
model and reasoning confirmation remain unknown where the native adapter does
not report them; the requested settings are recorded separately.

| Seed | Result for model side 0 | Terminal reason | Model calls | Queries | Batches / actions | Wall time |
|---:|---|---|---:|---:|---:|---:|
| 2001 | Loss (side 1 won) | resignation | 36 | 44 | 12 / 27 | 20.4 min |
| 2002 | Loss (side 1 won) | resignation | 29 | 38 | 10 / 36 | 12.9 min |
| 2003 | Win (side 0) | winner (recruiter killed) | 33 | 46 | 11 / 44 | 13.8 min |

The call counts include inspection follow-ups, review, and repair responses.
The original table counted only initial decision calls (12/10/11). Seed 2003
killed recruiter U2; it did not win through a scenario objective.

The cohort is therefore 1–2 (33% wins). The two losses were explicit model
resignations, not infrastructure failures; seed 2003 reached a gameplay win.
The result shows the grounding changes preserve a valid execution path and can
support a win, but they do not by themselves solve tactical consistency. The
next useful work is targeted review of the resignation turns and their live
versus projected evidence, rather than broad prompt expansion.
