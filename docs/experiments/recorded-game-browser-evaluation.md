# Recorded-game browser evaluation

Review correction (September 8): this is startup evidence, not completion of the
browser plan. The three runs below stayed paused and exited after 0.2 seconds;
they did not play to the end or verify return navigation between all recordings.
See [the code review](recorded-game-browser-review.md) for outstanding work.

The browser implementation was tested from commits `0722f00` and `e04213d`,
with the final replay-startup fix and smoke flag in `c89eaad` plus the current
working change. The headless gate passed after the prompt-contract wording fix:

```text
python3 -m tools.fast_check
Ran 223 tests ... OK
LLM bridge smoke: OK
replay tests passed
git diff --check
```

At this evaluation's source commits, the three Python catalog tests covered
two-row newest-first sorting, a missing catalog, and one nested sidecar format.
They did not cover paging or duplicate resolution. Replay exports used the same
`tools.replay_game` exporter used by the browser.

The real Love2D client was launched on the desktop display with
`--smoke-replay`; this flag runs the normal replay initialization and exits after
the first 0.2 seconds of updates. Lua errors can still leave an error window open;
an external timeout is not success.

| Recording | Game ID | Catalog | Status | Indexed model boundaries (not total side turns) | Replay frames | Love2D smoke |
|---|---|---|---|---:|---:|---|
| Incomplete | `ac395ef512b2b0dbae4a468655da8a45` | `tmp/quick-play-r6ryuNbb/history.sqlite` | incomplete | 12 | 12 | exit 0 |
| Short | `340b46360167b3822680427ff158cfc0` | `tmp/quick-play-AgbUzir8/history.sqlite` | complete | 6 | 6 | exit 0 |
| Long | `45d999b48fd7614a25fdadbf995302ee` | `tmp/quick-play-6BE3aOgy/history.sqlite` | complete | 21 | 21 | exit 0 |

The three recordings exported and loaded without modifying their catalogs or
archives. The smoke flag verifies client startup and bundle loading; interactive
selection and return navigation were also exercised on the desktop with xdotool:
the client launched, `V` opened the browser, Enter opened the selected replay,
Escape returned to the browser and then the menu, and the process log contained
no Love2D error or traceback. Pause and stepping remain manual visual checks.
