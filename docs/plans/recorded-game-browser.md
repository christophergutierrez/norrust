# Recorded games browser in Love2D

Status: partially implemented; the September 8 code review found unmet milestones.
See `docs/experiments/recorded-game-browser-review.md`. The earlier completion
report did not establish this plan's acceptance criteria.

## Outcome and scope

Launch `love norrust_love`, choose **Recorded Games**, select a recent game,
inspect its details, and click **Watch**. Playback opens in the same window.
**Back to games** returns to the same list position and selection, ready to watch
another recording. No game ID, database path, export command, or second client
is needed for this flow.

Implement two cumulative end-to-end stacks. Each stack includes its Python data
access, Love2D interaction, error handling, documentation, automated tests, and
actual Love2D acceptance. Review, fix, test, and commit each stack before starting
the next. A backend-only or UI-only change is not a completed stack.

Keep this a browser for existing cataloged recordings. Do not build a web server,
terminal client, new persistent index, database merger, filesystem watcher,
generic process framework, or new recording system. Do not add search, filters,
analytics, deletion, editing, live-game resumption, or what-if branches. Human
and algorithm players are displayed when their recording supplies that evidence;
this feature does not make normal human games automatically record themselves.
Unimported raw logs remain outside the browser; retain the existing history import
workflow. Do not launch model games to test a recording browser.

## Interaction and data contract

- Add a clickable **Recorded Games** entry to the existing scenario-selection
  menu, with an unused keyboard shortcut. Do not redesign the main menu.
- Show the newest 25 games. Columns: **Played**, **Side 0**, **Side 1**,
  **Result**, and **Turns**. Keep existing side numbering consistent with replay.
  Each side includes player/model and faction. Long labels may truncate in the
  row; the selected-game details must show the full text.
- Single-click selects and displays details below the list. **Watch** opens the
  selection; Enter does the same. Up/Down selects rows; scrolling keeps selection
  visible. Explicit buttons suffice; double-click is unnecessary for v1.
- Details show participants and identity evidence, factions, scenario, seed,
  starting gold, configured cap, completed duration, ending reason, recording
  availability, and game ID. Source catalog/archive and source commit belong in
  details, not mandatory input fields. Missing values say unknown.
- One displayed turn means two completed side turns, in recorded order. Three
  completed side turns display as `1.5`; details explain the final half-turn and
  the cap in side turns. Never count model calls, action batches, or arbitrary
  snapshot frames as completed turns. Missing boundary coverage stays unknown;
  distinguish game duration from available replay duration where they differ.
- Distinguish a valid winner, draw/turn cap, incomplete attempt, model failure,
  and infrastructure failure. Catalog `status = complete` alone is not a valid
  outcome: the importer currently uses it whenever a terminal record exists.
  Missing terminal evidence must not become a draw. A failed attempt may still
  have a watchable partial recording.
- Use recorded runtime model identity when supported; otherwise show the
  requested model with its evidence distinguished in details. Transport names
  such as `command` are not model identities. Unknown model names display as
  `LLM (model unavailable)`. Resolve players by their `side` field, not row order.
- **Refresh** reloads discovery/list data; **Load older** adds 25 rows from the
  current sorted result. Refresh preserves selection by game ID if it remains;
  otherwise select the first row. Ties have a deterministic game-ID ordering.
- Sort by recorded start time, newest first. For missing start times, use source
  archive modification time as an explicitly labeled fallback, then catalog
  modification time if the archive is missing. Never label fallback times as
  known game start times. Copying an archive must not override a known start time.
- Playback starts paused and retains current Back/Forward, Play/Pause, Restart,
  speed, and inspection behavior. Add **Back to games** and Escape to return.
  Returning pauses/releases playback without gameplay actions or saves.
- Empty discovery, missing recordings, corrupt data, helper failure, and failed
  exports appear as readable errors inside the client. Other valid games remain
  usable. Disable Watch when a known availability failure makes replay impossible;
  recheck on Watch because files may have changed after listing.

## Repository findings and implementation boundaries

Read `AGENTS.md`, `docs/DEVELOPMENT.md`, `docs/GAME_HISTORY.md`, and
`docs/REPLAY.md` before coding.

- `tools/game_history.py` already supplies read-only catalog access and the
  `games`, `game_players`, and `side_turns` tables. Reuse that access instead of
  adding SQLite bindings to Lua or duplicating the schema.
- `tools/replay_game.py:build_bundle` already exports a selected game. Reuse it
  for both CLI and GUI. Its current checks require an archive and a provable
  starting snapshot; the browser must not promise playback that this exporter
  rejects. Preserve the existing CLI as a useful independent entry point.
- `tools/match_report.py` contains outcome classification. Share its semantics
  for terminal validity rather than inventing a second result definition. Fetch
  missing archive evidence only as needed; do not decompress prompts/reasoning
  or build replay bundles for every row merely to render the list.
- Replay setup is currently embedded in `norrust_love/main.lua:love.load`.
  Extract one shared replay-entry path used by startup and browser selection,
  plus an explicit exit path. Reset board dimensions, terrain cache, camera,
  factions/controllers, selection, overlays, and animation/AI state as needed.
  Reopening another recording or starting a normal game must not retain replay
  state. Update existing input/draw context references consistently.
- Menu rendering/input live in `draw_screens.lua`, `input_setup.lua`, and the
  `input.lua` dispatcher. Reuse the existing layout and mode conventions.
- Add `tools/recorded_games.py` for browser queries/export dispatch and
  `norrust_love/recorded_games.lua` for browser state and interaction. Keep process
  plumbing local to this feature. Small worker/test files are justified; a
  general browser/backend abstraction is not.
- Use a short-lived Python helper with JSON responses, called from a Love2D
  worker thread so filesystem/SQLite/export work does not block drawing/input.
  Support only list, selected-game details, and selected-game export operations.
  Keep one request in flight; show loading and ignore stale responses after
  leaving the screen. Handle process exit, malformed output, thread failure,
  and a bounded helper timeout without leaving a permanent loading screen.
- Resolve repository paths from the Love2D source location, not the launching
  shell's current directory. Quote process arguments correctly, including spaces
  and shell metacharacters. Use private temporary export paths, publish complete
  bundles before loading, and clean them on success/failure. Never interpolate
  displayed model names into commands. Missing Python is a client error, not a
  crash or a request for the user to run export commands manually.

## Stack 1 — Browse, inspect, watch, and return using the default catalog

Deliver a complete working flow against
`<repository>/.norrust_history/history.sqlite`. Missing default catalog produces
an empty state without creating a database. Add the helper, browser menu/screen,
details, 25-row paging, Refresh, same-window export/load, and return navigation.
Use evidence already supplied by the catalog/archive; missing model identity can
remain explicitly unknown until Stack 2 adds the existing sidecars.

### Measurable acceptance

1. In a fixture catalog containing 27 games, the first view shows exactly 25 in
   the specified order; Load older shows all 27 once. Equal and missing timestamps
   have tested deterministic behavior. Empty catalogs and missing files work.
2. Selecting a row displays the exact corresponding metadata. Fixtures cover
   model, human, and algorithm labels; reversed player row order; side 1 moving
   first; 0, 1, 3, and 50 completed side turns; unknown duration; wins, cap draws,
   incomplete attempts, and failures. No failed attempt is labeled as a draw.
3. Watch loads the selected game ID and correct first state through the real
   exporter. Back returns with selection, scroll position, and loaded row count
   retained. Watch a second recording with different board dimensions/factions
   and verify its first state and labels, with no state left from the first.
4. A missing archive, invalid snapshot payload, or unprovable start produces a
   visible error and leaves navigation/another valid game usable. Selection
   changes or leaving the browser during a request cannot open the wrong replay.
5. A delayed helper leaves the Love2D UI responsive; missing Python, nonzero exit,
   malformed JSON, and timeout all finish loading with an error. Paths containing
   spaces, quotes, and shell metacharacters work without unintended execution.
6. After browser playback, return to the menu and start a normal game. Its normal
   controls work. During replay, gameplay mutations and saves remain disabled.

### Tests, review, and commit gate

- Add `tools/test_recorded_games.py` with isolated temporary catalogs/archives.
  Exercise public helper operations and real bundle output, not just mocks of
  the exporter. Compare exported initial/final state and game ID to fixture
  evidence. Assert catalog/archive contents remain unchanged by browsing.
- Add `norrust_love/test_recorded_games.lua` for state transitions, pagination,
  loading/error recovery, and selection preservation. Extend replay/input tests
  to drive actual registered mouse and keyboard handlers with their initialized
  context. A missing module reference must fail a test before a user clicks it.
- Add a minimal Love2D smoke harness for the real menu → browser → details →
  Watch → return path. Exercise actual update/draw/input callbacks and the real
  Python helper. It must time out/fail nonzero on Lua errors or failed assertions,
  and exit successfully only after the expected states are reached. Do not add a
  generic UI automation framework or a separate imitation of the application.
- Include the new headless Lua suite in `tools.fast_check`. Run focused tests,
  the real Love2D fixture smoke, and `python3 -m tools.fast_check`. Inspect the
  browser visually for clipping, selected-row visibility, and usable controls.
- Update `docs/REPLAY.md` and relevant development test instructions. Review the
  complete diff, fix findings, rerun affected checks, and record test commands and
  outcomes in `docs/experiments/recorded-game-browser-evaluation.md`.
- Commit the stack as `feat: browse and replay recorded games in Love2D`.

## Stack 2 — Discover existing game catalogs and show available model names

Extend the same flow to the existing scattered catalogs. On browser open/Refresh,
discover the default catalog and `*.sqlite` catalogs recursively under repository
`tmp/`. Do not follow directory symlinks, scan the user's whole home directory,
or include explicitly named backup databases. Validate candidates as Norrust
catalogs. Unsupported, busy, or corrupt catalogs contribute a concise diagnostic
without hiding other games. Bound SQLite waits and keep discovery off the UI
thread. No persistent index or changes to historical catalogs are needed.

Combine metadata in memory and deduplicate by exact game ID; do not merge games
by seed/model or stitch resumed games together. Prefer a source with usable replay
evidence, then more recorded completed boundaries, then the default catalog, then
lexical absolute path. Show the chosen source in details; surface conflicting
identity/outcome evidence instead of silently combining it. Keep the same source
for a row's details and export. A refresh may select a newly usable source.

Read a selected archive's adjacent `identity.json` only for explicit missing
identity fields. Support the two observed structures deliberately: flat
`model_requested`/`llm_side`, and nested
`requested.llm_player_model`/`requested.llm_side`. Validate the side association
and any supplied game/config identifiers against the catalog. Sidecar identity
is requested evidence, not runtime confirmation; strings such as `unknown` are
not model names. Catalog identity takes precedence; malformed, mismatched, or
unrecognized sidecars leave identity unknown. Apply the same resolved player
labels to list, details, and exported replay without modifying historical files.

### Measurable acceptance

1. A synthetic repository with at least three catalogs and 60 distinct games,
   duplicate IDs, a named backup, an unrelated SQLite file, and a corrupt catalog
   shows exactly the 25 newest distinct games. Paging reaches all 60 once, with
   deterministic source choice and diagnostics for unusable sources.
2. A game added to a nested run catalog after the browser opens appears after
   Refresh. Normal refresh/load-older operations do not rewrite catalogs or logs
   and do not export/decompress all recordings. A broken source cannot prevent
   valid games from loading.
3. Both observed identity formats display the requested model on the correct
   side in all three views. Tests cover missing/malformed sidecars, unknown model
   strings, side/config mismatch, conflicting catalog identity, and arbitrary
   player/model text. No requested value populates a reported-runtime field.
4. Starting Love2D from outside the repository still discovers the same catalogs
   and opens the correct selected recording. Browser interaction remains
   responsive during a deliberately delayed discovery/export.

### Tests, final replay acceptance, and commit gate

- Extend the Python and Lua suites and the real Love2D smoke harness for multiple
  catalogs, duplicate resolution, model evidence, refresh, and partial failures.
  Fixtures must be committed or generated deterministically; ignored `tmp/`
  recordings must not be required by automated tests.
- Follow `docs/AGENT_GUIDE.md` and `docs/GAME_HISTORY.md` when selecting real
  recordings. Inspect catalogs first and select **three existing recordings**:
  one incomplete but watchable, one short, and one long. Do not play new games.
- Launch the actual Love2D client and use the browser to replay all three at
  Fast speed, returning to the browser between games in the same process. For
  each, verify the selected ID, full player labels, initial recorded position,
  progress to the last available frame, ending label, and working return path.
  Check pause and Back/Forward on at least one recording. An incomplete recording
  must finish at its available end and remain labeled incomplete/failed as
  appropriate, rather than claiming a full game outcome.
- Capture process exit status, stdout/stderr, and assertions for these runs.
  Zero Lua errors, zero wrong-game loads, and successful return after all three
  are required. A window staying open or a screenshot alone is insufficient.
  Use a real desktop display or a virtual display that initializes SDL; an SDL
  startup failure is a failed smoke test, not replay success.
- Record a three-row evidence table in the evaluation document: game ID, chosen
  catalog, recording category, participants/model evidence, completed side turns,
  available replay frames, initial/final checks, ending label, return check, and
  process result. Include source commit and any coverage limitations. Record
  initial discovery/selected-export timings on the actual repository to expose
  unexpected full-archive work; investigate visible UI freezes or runaway work.
- Finish `docs/REPLAY.md`, `docs/GAME_HISTORY.md`, and development instructions:
  document the menu flow, discovery roots, cataloged-only coverage, identity
  precedence, failure messages, and smoke command. Keep manual export/launch
  documentation as an optional diagnostic workflow.
- Run focused checks, the three replay smokes, and `python3 -m tools.fast_check`.
  Review the diff for duplicated replay setup, evidence fabrication, main-thread
  blocking, stale context references, and unnecessary abstractions. Fix issues
  and rerun affected checks before committing.
- Commit as `feat: discover recorded games across local catalogs`. Mark this
  plan complete only when both stack commits and their test evidence exist.

## Definition of done

From a normal Love2D launch, the user can find recent cataloged games across the
existing run directories, identify the players and outcome, inspect details,
watch three different recordings, and return to browse again without entering
an ID, path, or export command. Both stacks are reviewed, tested, documented,
and committed. The three actual-client replay checks pass. No model games or
historical evidence changes are part of completion.
