# Recorded game playback evaluation

The exporter and replay controller passed the headless checks. Three existing
cataloged recordings were selected and exported by exact `game_id`:

| Category | Game ID | Recording | Frames | Endpoint | Love2D smoke |
|---|---|---|---:|---:|---|
| Incomplete | `164dd80b13fc184a312acae7a5fdf1b3` | seed 2001 continuation source | 5 | revision 246 | blocked: no SDL display |
| Short | `09a878b50c61b28765b0c42dff08e64b` | Sonnet seed 2036 | 16 | revision 634 | blocked: no SDL display |
| Long | `f2913cc275de8f4c60b587b5edcb311e` | Luna consequential seed 2033 | 25 | revision 410 | blocked: no SDL display |

Bundles were exported to `tmp/replay-smoke/`. Each real Love2D launch was
attempted with `love norrust_love -- --replay-bundle BUNDLE`; all three failed at
startup with `Could not initialize SDL video subsystem (No available video
device)`. This is an environment limitation, not a replay result, so GUI
acceptance remains pending until a display or virtual OpenGL display is
available. No source archives or catalogs were modified.

Validation completed:

- `python3 -m unittest tools.test_replay_game tools.test_game_history -q`: 11 passed.
- `luajit norrust_love/test_replay.lua`: passed.
- `python3 -m tools.fast_check`: 218 tests passed, Rust suites passed, both Lua
  smoke tests passed, and `git diff --check` passed.

Implementation commits are `81a3bb1` and `48b3aed`, with follow-up fixes in
`8e5e0e6` and `77657bb`. The three exported bundles and launch logs are retained
under `tmp/replay-smoke/` for rerunning on a graphical host.
