# Recorded-game browser code review — September 8

Reviewed the implementation through `50ca0c4` against
[`recorded-game-browser.md`](../plans/recorded-game-browser.md). The implementation
is partial. Its earlier completion claim and descriptions of test coverage were
too strong. This review fixes local defects and leaves the following larger work
explicitly outstanding.

## Larger issues requiring follow-up

1. **P1: helper calls block the application.** `recorded_games.lua:request` uses
   `io.popen` and reads to EOF inside input handling. Loading, refreshing, and
   exporting can freeze rendering and event handling; there is no timeout or
   worker. The `loading` field does not provide asynchronous behavior. Implement
   the planned worker/response lifecycle with bounded execution and tests for
   delayed, failed, and stale responses.

2. **P1: recording duration and coverage are not established.** The catalog
   importer builds `side_turns` from accepted model `turn_boundary` records.
   Counting those rows does not count both sides' completed turns. The exporter
   reads only those stored snapshots, skips missing blobs, and considers sequence
   1 a starting-position proof. The viewer then treats each frame as half a turn.
   Missing opponent boundaries or an opening after earlier actions therefore
   produce misleading duration/stepping and potentially missing opening/end
   positions. The browser now calls the count *indexed boundaries* and labels
   duration unverified. Repair the catalog/export coverage path and derive
   duration from actual boundary/terminal evidence; do not reconstruct by playing.

3. **P1: browser and replay disagree about metadata and availability.** The list
   resolves requested models from sidecars, but export reads only catalog player
   fields. Desktop inspection confirmed a named Luna row becomes `LLM (model
   unavailable)` in replay. The subsequent quick fix now renders catalog win,
   resignation, and turn-limit outcomes rather than completion status. Missing
   terminal/error classification still needs the shared metadata path.
   Duplicate selection uses only indexed row count, so
   a stale or missing archive can beat a usable copy. Introduce one small shared
   game projection for identity evidence, ending, coverage, and source choice,
   used by list/details/export. Preserve uncertainty and never invent runtime
   model identity from a requested name.

4. **P1: final acceptance was not performed.** `--smoke-replay` opens paused and
   quits after 0.2 seconds. It never advances to the end or checks three returns
   in one process. The old desktop script only sent keys and checked for error
   text. Add the planned bounded actual-client harness that asserts selected ID,
   first/last state, playback progression, and return state. The old 223-test
   count was the whole Python suite; only three tests covered the new browser.

Additional unfinished plan items: Load older should append instead of replacing
the current page; start-time sorting needs parsed timestamps and documented
fallbacks; availability errors should disable Watch before export; complete
source/identity evidence belongs in details. These are still absent, rather than
being implied by a clean worktree or successful startup.

## Local fixes made during review

- Shared drawing/click rectangles, a visible row window that follows selection,
  clipped columns, aligned headers, working Watch/Refresh/page/menu buttons, and
  mouse-wheel selection. The old click origin was 70 while drawing began at 86;
  buttons used hard-coded y=430 while rendering used viewport height, and rows
  intercepted those clicks before the buttons.
- Escape/Games from a direct CLI replay returns to the menu without dereferencing
  a nonexistent browser. Returning to an existing browser preserves selection
  without requerying it. Pages clamp at their ends and Refresh retains a selected
  ID when it remains on the current page.
- Browser replay entry resets the camera and inspection/overlay state. It uses
  recorded visibility rather than the live engine's stale fog mask. Initial
  bundle validation happens before switching replay state.
- Temporary exports use the actual allocated temporary path and are removed on
  success or load failure. Load failures become browser errors. JSON responses
  are decoded whole, so braces inside model names cannot truncate them.
- Malformed sidecars no longer remove all games in a catalog. Sidecars must
  supply a string model and integer model-controlled side; supplied game/config
  identifiers must match. Unknown names and catalog-identity overrides are
  rejected. Missing player records retain the known faction. Model labels prefer
  recorded model fields over a transport display name. Catalog connections close
  on query failure, and discovery diagnostics are visible.
- Removed the redundant T8 sentences added merely to satisfy stale prose tests;
  the regression checks the existing concise tactical rule instead.
- Corrected the plan status, replay documentation, and prior evaluation claims.

## Verification

- `python3 -m unittest discover -s tools -t .`: 225 tests passed.
- `NORRUST_LIB=norrust_core/target/debug/libnorrust_core.so luajit
  norrust_love/test_recorded_games.lua`: new regression suite exercises the actual
  input dispatcher, shared geometry, selection, page bounds, malformed JSON
  shape handling, export cleanup, and return from direct/browser replay.
- Existing replay tests pass. The new Lua suite is registered in `tools.fast_check`
  and its gate test checks the suite is included. Rust sources were not changed.
- Desktop check: open the browser, select Watch, inspect the centered replay,
  play/pause, step forward/back, return to browser/menu, and exit with code 0;
  screenshots inspected and no Lua error/traceback in the process log. This is a
  local-fix check, not the plan's three-complete-recording acceptance.

Larger issues above remain open. No new games were played and no historical
catalogs, logs, or identity sidecars were edited.
