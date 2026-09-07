# Recorded game playback

Status: implementation started and paused for this plan revision; no final
replay smoke tests have run.

## Outcome

`python3 -m tools.replay_game GAME_ID` opens the cataloged recording in Love2D,
paused at its first recorded position. It uses the normal board, sprites, camera,
and inspection panels, with recorded players/factions already selected and a
small replay toolbar. Playback displays saved positions; it never executes game
actions, runs Greedy, calls a model, or rerolls combat.

Build two end-to-end stacks. Each must work from a catalog game ID through the
actual Love2D viewer, pass its focused tests and the full gate, receive review,
and be committed before the next stack starts. The final phase launches Love2D
to replay three existing recordings: one incomplete, one short, and one long.
All three run at Fast speed. No new model games are required.

## Agreed interaction contract

- Controls: Back 1 Turn, Play/Pause, Forward 1 Turn, Restart, and a speed selector
  with Slow / Medium / Fast. No 1 / 5 / 10 / END dropdown.
- A replay turn is two successive side turns in recorded order. Do not assume
  side 0 always moves first. The driver cap is in **side turns**: 50 side turns
  allow at most 25 complete replay turns.
- Show the initial position, then the resulting position after each side acts.
  Do not animate individual movement or combat in this version.
- Slow = 2 seconds per complete turn (1 second per side); Medium = 1 second
  (0.5 per side); Fast = 0.5 seconds (0.25 per side). Start paused at Slow.
- Play continues to the recording's end. Pause freezes the current position and
  its remaining display interval. Resuming continues that interval. A speed
  change retains the elapsed fraction of that interval.
- Back/Forward pause and move two side-boundary positions, clamped to the
  recording's beginning/end. From an intermediate position they preserve the
  point within the turn where possible. Each step resets the display interval.
  Three Back clicks move back six side boundaries; they do not replay actions.
- Restart returns to the recording's first position, paused, with the selected
  speed retained. Play at the end stays at the end; Restart is explicit.
- The toolbar shows Replay, player names/factions, progress, and turns remaining.
  Count the recorded duration, not the configured maximum. Use half-turn values
  where needed: 21 completed side turns are 10.5 replay turns. Clearly label a
  final partial turn and which side last acted. Initial position is turn 0.
- A win, resignation, cap, or incomplete/error ending stays visible alongside
  working replay controls. Do not put a gameplay victory modal over the controls.
- Keep pan, zoom, unit selection, and terrain inspection. Disable move, attack,
  recruit, promotion selection, end-turn, gameplay save/load, debug mutations,
  campaign progression, AI queues, and agent-server commands in replay mode.
- A recording beginning midgame opens at that recorded position and says so.
  Show its original engine turn as context. Do not manufacture its opening or
  automatically stitch unrelated archives together.

## Repository findings and constraints

Read before implementing: `AGENTS.md`, `docs/DEVELOPMENT.md`,
`docs/GAME_HISTORY.md`, and `docs/AGENT_GUIDE.md` for selecting recorded games.

- `tools/game_history.py` resolves a catalog `game_id` to `artifact_path` and
  player metadata. Use `open_history(..., read_only=True)`. A conversation ID
  or seed is not an interchangeable game ID.
- The inspected catalog at
  `tmp/luna-final-20260907/seed-2001/continuation/recovery-history.sqlite`
  has model-side start blobs but no end blobs for those boundaries. The catalog
  alone does not currently provide a complete alternating-side recording.
- Checkpoints in the associated archive provide additional model/postbatch
  states. However, `greedy_driver.rs` can emit `game_end` after Greedy wins or
  reaches the cap before publishing the next model checkpoint. Initial play
  with model side 1 and incremental final batches need explicit coverage too.
  Do not assume a last available checkpoint is the final winning position.
- `SaveState` omits board geometry and static unit properties, reloading them
  from current content. Blindly loading it can make historical inspection show
  current rules. Prefer the driver's full observation snapshot for recordings.
- `norrust_love/draw.lua` already accepts a state table. `main.lua`, HUD, sidebar,
  and input still consult a live engine in places; replay must read the selected
  recorded snapshot consistently and bypass simulation.
- Ignored `tmp/` archives are investigation evidence, not test fixtures. Commit
  small relocatable fixtures and generate deterministic recordings in tests.

## Scope and implementation choices

Use one Python launcher/exporter, one small Lua replay controller, and the
existing renderer. No new service, database tables, generic event-replay engine,
or background indexing. No what-if branches, action stepping, timeline scrubber,
annotation panel, video export, or recovery-system rewrite.

The launcher takes positional `GAME_ID` and optional `--db`, defaulting to
`.norrust_history/history.sqlite` resolved relative to the repository root. An
explicit relative `--db` resolves relative to the caller. Do not scan every
catalog or pick a game by seed. Invoke Love2D with an argument list, not shell
interpolation, and handle paths with spaces. Document the build prerequisites.

Export a small versioned JSON replay bundle to a temporary directory kept alive
until Love2D exits. Include game/player identity, source provenance, recorded
start offset, final outcome/coverage, and ordered full display snapshots with
explicit boundary identity. Do not include prompts or token histories. Package
the recorded board/roster display data so moving the bundle does not require the
original author's absolute board path. Current visual assets can be reused;
missing sprites use the existing fallback. Never substitute current unit rules
for missing recorded inspection values.

Reuse complete existing snapshot evidence when sufficient. Where coverage is
missing, add a single versioned `replay_frame` driver record containing the
existing full observation payload and explicit boundary metadata. Capture the
initial state before either side acts, every successfully committed side's
result, and a terminal position if it differs from the last recorded frame.
Reuse identical frames rather than duplicating an ending at the same boundary.
Read-only queries, previews, rejected batches, and rolled-back actions never
become frames. Incremental partials are not extra turns; a game ending during a
partial still needs its true final position without inventing an EndTurn.

For older archives, accept only provable positions. Validate checkpoint hashes
and board identity if checkpoints are used to supply display data. Stop playback
at an unfillable gap, label the available contiguous recording as incomplete,
and identify the missing boundary. If no usable starting snapshot exists, fail
before launching Love2D. Do not attempt a general legacy-log reconstruction.

## Stack 1 — Open a faithful recording and step through it

End-to-end milestone: generate/import a deterministic game, launch it by ID,
and inspect its initial, intermediate, and final positions with Back/Forward
and Restart. It opens straight onto the paused board with the recorded players.

Likely files:

- New `tools/replay_game.py`, `tools/test_replay_game.py`, and small fixtures
  under `tools/fixtures/replays/`.
- `norrust_core/src/bin/greedy_driver.rs` and relevant driver protocol tests for
  missing snapshot capture; `tools/llm_client.py` only if needed to durably retain
  those records. Preserve gameplay and checkpoint semantics.
- New `norrust_love/replay.lua` and its Lua tests; targeted integration in
  `main.lua`, `draw.lua`, `draw_hud.lua`, `draw_sidebar.lua`, and input routing.
  Add a separate small replay toolbar module only if it keeps those edits clear.
- `tools/fast_check.py`, `docs/GAME_HISTORY.md`, `docs/DEVELOPMENT.md`, and new
  `docs/REPLAY.md` for launch, controls, and incomplete-recording behavior.

Tasks:

1. Freeze the frame/bundle fields and boundary-count rules in tests. Use one
   definition for completed side turns versus a terminal position reached during
   an unfinished side. Progress must not count that terminal frame as another
   completed side turn.
2. Complete recording coverage at the concrete driver publication points above.
   Preserve all existing authoritative state/RNG/side-turn outcomes.
3. Resolve the exact catalog game read-only; validate and export its frames and
   outcome. Keep runtime model names unknown when telemetry is missing, and
   label requested model names as requested if used in the player display.
4. Add replay startup that bypasses scenario/faction selection. Feed the selected
   snapshot into the existing board and safe inspection views. Wire step and
   restart controls, progress labels, and the visible replay/ending indicator.
5. Route all replay input and updates before normal gameplay paths. Clear stale
   selections when a selected unit disappears on a different frame. Update
   terrain ownership, HP, XP, promotions, gold, and time of day on every seek.

Required tests and measurable acceptance:

- [ ] Real-driver deterministic recordings include the opening and both sides'
  results for model sides 0 and 1. Cover win by either side, odd/even caps,
  resignation without an extra completed turn, incremental partials, and an
  interrupted log. Assert final capture occurs before the terminal is lost.
- [ ] Assert frame roster/positions/HP/XP/types, gold, village ownership, turn,
  and revision match independent live driver/checkpoint evidence at the same
  boundaries. Assert rejected and hypothetical results never appear. A terminal
  winning-move fixture must show the defeated recruiter gone, not the prior board.
- [ ] A fresh temporary catalog import produces an ID that the real exporter
  resolves; exported boundaries have correct order and coverage. Reimport is
  idempotent; integrity and foreign-key checks pass. Hash the archive before and
  after viewing and verify that neither it nor the catalog was modified.
- [ ] Unknown ID, missing DB, missing archive, corrupt snapshot/checkpoint,
  truncated final log line, missing middle boundary, and unsupported bundle
  version produce explicit failures or documented incomplete prefixes. Never
  claim an incomplete prefix is a full game or fabricate missing frames.
- [ ] Lua tests prove Back/Forward move exactly two boundaries, clamp correctly,
  and three clicks back move six; odd-length and midgame recordings work.
  Terminal partials follow the tested boundary rule. Restart resets to index 0.
- [ ] Real Love2D launch from GAME_ID (including a path with spaces) opens the
  paused normal-looking board, correct players, and visible replay controls.
  Exercise step, restart, pan/zoom, and unit inspection. Verify representative
  gameplay clicks/keys cannot mutate any frame or start AI/backend activity.
- [ ] Run focused regressions, `python3 -m tools.fast_check`, and
  `git diff --check`. Include new Lua tests in the gate; real-driver tests must
  use the freshly built driver without skips. Review the diff, fix defects,
  and commit code/tests/docs as one working stack. Record hash and test counts.

Suggested commit: `Add recorded-game launcher and read-only turn stepping`.

## Stack 2 — Continuous playback with pause and speed

End-to-end milestone: the same GAME_ID launcher now provides the complete agreed
toolbar, and a recording can play from start to finish at each speed, pause for
inspection, step backward/forward, and restart without changing recorded data.

Tasks:

1. Extend the replay controller with a playing flag, selected speed, and elapsed
   interval. Drive it from Love2D `dt`; no sleeps or per-side timers/processes.
2. Add Play/Pause and Slow / Medium / Fast using the existing UI conventions.
   Keep the toolbar available at the end and during incomplete-recording notices.
3. Reset the interval on steps/restart, preserve its fraction on speed changes,
   and preserve remaining time on pause. Prevent a large rendering stall from
   skipping several unseen positions: advance at most one boundary per update
   and discard excessive elapsed time. Actual playback may slow during a stall.
4. Keep progress/remaining labels correct at each half-turn and terminal partial.
   Disable step buttons only at their relevant endpoints. Update help/docs.

Required tests and measurable acceptance:

- [ ] Controlled-dt Lua tests: no transition before 1 / 0.5 / 0.25 seconds at
  Slow / Medium / Fast; exactly one transition at the threshold. Two boundaries
  take 2 / 1 / 0.5 seconds under normal updates. Test fractional accumulation.
- [ ] Pause causes zero frame changes across arbitrary updates. Resume uses the
  remaining interval. Speed changes preserve elapsed fraction. Step while playing
  pauses and moves two boundaries. Restart resets position/time and stays paused.
- [ ] End-of-recording automatically pauses without wrapping. Repeated Play at
  the end does nothing. Large-dt tests cannot skip through multiple frames.
- [ ] Run the real Love2D UI at all three speeds. Pause midturn, inspect a unit,
  click Back three times and Forward three times away from endpoints, and verify
  return to the exact same recorded position. Confirm toolbar hitboxes at normal
  and resized windows and that the board/pan/zoom remain usable.
- [ ] Run full `tools.fast_check`, new timing/UI checks, and `git diff --check`.
  Headless controller tests do not replace the actual Love2D acceptance. If no
  display is available, arrange a virtual display for launch coverage and leave
  any unobserved visual acceptance explicitly pending. Review/fix, then commit
  this stack with updated documentation and exact test evidence.

Suggested commit: `Add replay play-pause and three playback speeds`.

## Final phase — Three existing recordings in real Love2D

Only start after both stacks are reviewed, tested, and committed. This is a
smoke test of the real client playing recordings, not a model-performance test.
Run sequentially for simple window/input handling; parallel subagents and native
model calls are unnecessary.

1. Read the recorded-game guidance and inspect existing SQLite catalogs before
   individual archives. Select three distinct recorded games:
   - Incomplete: an interrupted/error recording with a usable contiguous prefix
     containing at least one transition; playback must visibly end as incomplete.
   - Short: a completed recording, preferably 1–10 completed side turns.
   - Long: a completed recording, preferably at least 30 completed side turns.
   Use actual available lengths and record them. If a preferred range is absent,
   choose the shortest/longest suitable existing recording and explain the choice.
   Do not start new games or simulate missing historical positions. A missing
   playable category remains an explicit unmet milestone.
2. Resolve each game by its catalog ID and preserve the source catalog/archive.
   Use a temporary catalog only when an existing recording requires import;
   record that resulting ID. Keep each smoke test's stdout/stderr and completion
   evidence in its own directory, separate from original game evidence.
3. Launch the actual Love2D app through `tools.replay_game GAME_ID --db PATH` for
   each selection. Use the real renderer and update loop with a display or virtual
   display. Select Fast (0.25 seconds per side) and press Play, then let it reach
   the last available recorded position. Do not substitute exporter-only checks,
   mocked Love2D calls, or headless Lua controller tests for these three launches.
4. Automate only what is necessary to make the smoke result reliable: a small
   test harness may select Fast/Play, observe the rendered final frame and stopped
   playback, capture a screenshot/result, and close the window. Keep this out of
   the normal product controls. Give each launch a finite deadline based on its
   frame count (nominal Fast duration plus a documented startup/rendering margin).
5. Fail the smoke test on a launch failure, Lua traceback/Love error screen,
   nonzero exit, timeout, premature close, or failure to reach/render the expected
   endpoint. A zero exit alone is not success. Require evidence of intermediate
   progress and a final rendered frame/revision matching the selected archive.
   For the incomplete game, its expected incomplete-ending notice is success;
   a software exception or refusal to display a usable prefix is failure.
6. Verify the final UI shows the right game/players and ending. Hash-check that
   viewing changes no source catalog/log/checkpoints. Detailed stepping, timing,
   pause/resume, and resizing tests remain in the preceding stacks; this phase
   simply proves three representative recordings play through the real client.
7. Fix replay bugs found, rerun the relevant checks and full gate after code
   changes, and rerun failed smoke cases on the same recordings. Preserve failure
   output. Do not replace a failing recording to obtain a passing result.

Final acceptance and report:

- [ ] One incomplete, one short, and one long existing recording each launch by
  game ID in real Love2D and play at Fast speed to the expected endpoint.
- [ ] All three smoke cases have intermediate and final render evidence, explicit
  pass/fail results, and captured error output. The incomplete case displays its
  expected notice; both complete cases display their recorded endings.
- [ ] No new games or model requests were started for smoke testing, and all
  original catalogs and game evidence remain unchanged.
- [ ] Commit `docs/experiments/recorded-game-playback-evaluation.md` with a table:
  category, game ID/catalog, recorded outcome, available side turns/frames,
  expected/observed final revision, smoke duration, pass/fail, and evidence path.
  Include exact launch commands, source archive hashes, playback source commit,
  both stack commits, and any unavailable recording coverage. Token/usage and
  model-performance analysis are not required for this playback smoke test.
- [ ] Update this plan with actual commands, test counts, GUI evidence, commit
  hashes, and remaining limitations. Check off only milestones with observed
  evidence. All required milestones must pass before claiming completion.

## Execution record

- Plan: written and reviewed against the current catalog, driver capture paths,
  and Love2D renderer; committed separately before implementation.
- Stack 1 implementation: started; review/tests/commit pending.
- Stack 2 implementation/review/tests/commit: pending.
- Three recorded-game Love2D smoke tests/report commit: pending.
