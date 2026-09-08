# Recorded-game browser evaluation

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

The Python catalog tests cover newest-first paging, missing catalogs, scattered
catalog discovery, duplicate IDs, and requested model identity from both
catalogs and adjacent sidecars. Replay exports were generated through the same
`tools.replay_game` exporter used by the browser.

The real Love2D client was launched on the desktop display with
`--smoke-replay`; this flag runs the normal replay initialization and exits after
the first update so a Lua startup error cannot be mistaken for a timeout.

| Recording | Game ID | Catalog | Status | Side turns in catalog | Replay frames | Love2D smoke |
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
