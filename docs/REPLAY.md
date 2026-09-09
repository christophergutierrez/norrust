# Recorded game playback

Export and open a cataloged recording by its exact `game_id`:

```bash
python3 -m tools.replay_game GAME_ID --db .norrust_history/history.sqlite
```

The viewer starts paused at the first recorded snapshot. The toolbar identifies
both participants explicitly as `Side 0` and `Side 1`, including each player's
name, requested LLM model when applicable, and faction. If the archive did not
record the model, it says `LLM (model unavailable)` rather than treating the
backend transport name as a model. It uses the normal board renderer and
inspection panel, while
all gameplay actions and saves are disabled. `Back 1` and `Forward 1` move one
recorded frame, as do Left/A and Right/D. A frame is a saved board snapshot;
snapshots are not necessarily spaced one side-turn or round apart. The toolbar
shows the recorded turn number and the number of frames remaining, so missing
snapshots can still produce gaps in turn numbers. `Play`/`Pause` follows the
recording, and `Restart` returns to frame 0. Playback speeds are Slow
(2 seconds per frame), Medium (1 second), and Fast (0.5 seconds).

The launcher accepts `--export PATH` to inspect the generated relocatable JSON
bundle without opening Love2D. Missing or incomplete snapshots are reported;
the exporter never reconstructs a state by running the game or rerolling
combat. It never resumes a checkpoint through a driver either — resuming can
immediately execute a Greedy turn, which would replay history rather than
show it. A checkpoint-only moment in the timeline can still become a
renderable frame when the read-only `dump_checkpoint` binary is available
(see [GAME_HISTORY.md](GAME_HISTORY.md)): that tool loads the checkpoint and
the current unit/terrain registries and prints the state, without resuming
gameplay or touching Greedy at all. When the tool or a historical resource is
missing, the gap is reported the same as before, not filled in from today's
data.

Frames come from the game's authoritative `snapshots` timeline (see
[GAME_HISTORY.md](GAME_HISTORY.md)), one per renderable snapshot in archive
order; a snapshot with evidence but no renderable state (a standalone
checkpoint) is not exported as a frame, but still counts toward the bundle's
`coverage` gaps. The bundle also carries `coverage` (`opening_present`,
`terminal_present`, `gaps`, `conflicts`), which the toolbar shows as "Replay
coverage incomplete" whenever the recorded engine result is complete but the
timeline itself has a reported gap — distinct from "Recording incomplete",
which reflects the engine's own `status`.

A catalog row whose `importer_version` does not match the current importer
(a pre-snapshot catalog, or one from an interrupted import) cannot be
exported. The launcher and browser report an actionable error naming the
reimport command rather than silently falling back to the old per-side-turn
export.

From the normal Love2D scenario screen, press `V` for **Recorded Games**. The
browser lists the newest cataloged games, shows selected participants and
metadata, and exports the recording internally when **Watch** is selected. Use
Up/Down and Enter, or the on-screen controls; Escape returns from playback to
the browser (or the menu when launched directly from a bundle). Page Up/Down and
Previous/Next switch pages; the mouse wheel moves selection. The manual launcher
remains useful for diagnostics. Browser and replay duration/model labeling still
have known gaps documented in [the browser review](experiments/recorded-game-browser-review.md).

The browser shows timestamps through whole seconds and a compact **Gold/Turns**
column: `50/15` means 50 starting gold and 15 turns played. Turn counts come from
the archived engine ending, including the final round for a win; turn-limit
endings use completed side turns divided by two (so `24.5` means one side
finished the last turn). Missing ending evidence, including incomplete games,
shows `?`; imported model-boundary counts are not used as duration.

Side labels are green for the winner, red for the loser, and both yellow for a
draw. Unknown outcomes stay neutral. Selected-game details retain the written
result, including resignation and turn-limit endings. A finished record without a
known outcome says `Outcome unknown`, not `complete`. These labels use catalog
ending evidence; an unimported error can still appear as `Incomplete` until the
catalog metadata path is corrected.

For a startup check of an exported bundle, append `--smoke-replay` to the Love2D
arguments. This still requires an SDL display. The client initializes the paused
viewer and exits after 0.2 seconds; this does not test playback through the end.
