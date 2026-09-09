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
complete turn (two recorded side boundaries), `Play`/`Pause` follows the
recording, and `Restart` returns to the first frame. Playback speeds are Slow
(2 seconds per complete turn), Medium (1 second), and Fast (0.5 seconds).

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
the browser. The manual launcher remains useful for diagnostics.

For a headless startup check of an exported bundle, append `--smoke-replay` to
the Love2D arguments. The client initializes the normal viewer and exits after
its first update; this is used by the recorded-game browser smoke evaluation.
