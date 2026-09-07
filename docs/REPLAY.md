# Recorded game playback

Export and open a cataloged recording by its exact `game_id`:

```bash
python3 -m tools.replay_game GAME_ID --db .norrust_history/history.sqlite
```

The viewer starts paused at the first recorded snapshot. The toolbar identifies
both participants explicitly as `Side 0` and `Side 1`, including each player's
name, requested LLM model when applicable, and faction. It uses the normal board
renderer and inspection panel, while
all gameplay actions and saves are disabled. `Back 1` and `Forward 1` move one
complete turn (two recorded side boundaries), `Play`/`Pause` follows the
recording, and `Restart` returns to the first frame. Playback speeds are Slow
(2 seconds per complete turn), Medium (1 second), and Fast (0.5 seconds).

The launcher accepts `--export PATH` to inspect the generated relocatable JSON
bundle without opening Love2D. Missing or incomplete snapshots are reported;
the exporter never reconstructs a state by running the game or rerolling
combat.
