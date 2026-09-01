# Headless Self-Play and Balance Testing

Use the Rust `self-play` binary for reproducible AI-versus-AI games. Run
commands from the repository root.

## Start here

```bash
# 1. Structural check of the balance board (must pass)
python3 - <<'PY'
import tomllib

with open("scenarios/big_battle_6/board.toml", "rb") as source:
    board = tomllib.load(source)

width, height = board["width"], board["height"]
tiles = board["tiles"]
terrain = lambda col, row: tiles[row * width + col]

assert (width, height) == (24, 14)
assert len(tiles) == width * height
assert all(
    terrain(col, row) == terrain(width - 1 - col, height - 1 - row)
    for row in range(height)
    for col in range(width)
)

keeps = [
    (col, row)
    for row in range(height)
    for col in range(width)
    if terrain(col, row) == "keep"
]
villages = [
    (col, row)
    for row in range(height)
    for col in range(width)
    if terrain(col, row) == "village"
]

assert sorted(keeps) == [(2, 7), (21, 6)]
assert len(villages) == 6
assert sum(col < width // 2 for col, _ in villages) == 3
assert all((width - 1 - col, height - 1 - row) in villages for col, row in villages)

directions = [(1, -1, 0), (1, 0, -1), (0, 1, -1),
              (-1, 1, 0), (-1, 0, 1), (0, -1, 1)]

def adjacent_offsets(col, row):
    x = col - (row - (row & 1)) // 2
    y = -x - row
    for dx, dy, dz in directions:
        nx, nz = x + dx, row + dz
        yield nx + (nz - (nz & 1)) // 2, nz

for keep in keeps:
    castle_count = sum(
        0 <= col < width
        and 0 <= row < height
        and terrain(col, row) == "castle"
        for col, row in adjacent_offsets(*keep)
    )
    assert castle_count == 6, (keep, castle_count)

print("big_battle_6 structure: ok")
PY

# 2. Build once; time the binary, not compilation
cargo build --release --manifest-path norrust_core/Cargo.toml --bin self-play

# 3. Smoke run
norrust_core/target/release/self-play \
  --scenario big_battle_6 --team1 undead --team2 undead \
  --ai1 greedy --ai2 greedy --games 10 --seed 1 --threads 4 \
  --gold 300 --second-gold 0 --first team1
```

`--help` prints options and exits 2:

```bash
norrust_core/target/release/self-play --help || [ "$?" -eq 2 ]
```

## Board and clock

`big_battle_6` is the balance map: 24×14, keeps at `(2, 7)` and `(21, 6)`, six
castle slots per keep, three village pairs. Tiles are 180-degree hex-symmetric:
`(col, row) → (23 - col, 13 - row)`. That rotation preserves adjacency on
odd-r. A same-row left/right flip does **not**.

Do not use `final_battle` as a neutral board. It is an asymmetric campaign map
(nine villages on the left, six on the right).

Time of day follows the round number. The turn counter advances after **both**
factions have acted, so left-first and right-first share the same ToD schedule.

Team 1 is always the left keep; Team 2 is the right keep. `--first team1` or
`--first team2` sets who moves first. `--first coin-flip` mixes initiative and
is the wrong tool when you want to measure first-player advantage.

Self-play wins by elimination only. Campaign objectives and timeout victories
are off. `--max-turns N` is a safety cap of `2*N+2` faction turns, not “draw at
round N”.

The `scenario_validation` integration test may fail to link (`cdylib` / `rlib` /
`self-play` collision). Use the Python check above; do not treat a link failure
as a passing board test.

## Fairness flags

Always pass these unless the experiment is specifically about changing them:

| Flag | Why |
| --- | --- |
| `--gold 300` | Equal starting gold |
| `--second-gold 0` | CLI default is **5**. Omitting this flag is a different experiment. Not yet calibrated to cancel first-player advantage. |
| `--first team1` or `--first team2` | Measure initiative in separate cells |
| `--seed S` | Reproducible input-index range `S` .. `S+N-1` |

`--verbose` prints one CSV row per game. `--compact` prints one summary line.
They cannot be combined. The `seed` column in verbose output is a mixed
internal seed, not `S`. Replay game `k` of a batch with `--seed S+k-1 --games 1`.

Same `--seed S --games N` is a replay, not an independent replicate. For a
new sample, use a disjoint range (for example `S+N`).

## Algorithms

| `--ai1` / `--ai2` | Role |
| --- | --- |
| `greedy` | Fast baseline: every reachable hex, expected-damage combat, ID order |
| `greedy-look-ahead` | Slower: structured beam (keep, attacks, villages, defense, march), skip bad melee terrain trades, expected-damage scoring plus a local opponent reply, sit on keep/village instead of a losing trade. Leader fights unless this plan actually recruited. |
| `random` | Legal-move uniform random |

Look-ahead is ~40–50× slower than greedy on this map. Time 10 games before
choosing a large `N`.

## Recipes

Greedy mirror, first-player cells (fast; ~90 s per 1,000 games here):

```bash
norrust_core/target/release/self-play \
  --scenario big_battle_6 --team1 undead --team2 undead \
  --ai1 greedy --ai2 greedy --games 1000 --seed 14001 --threads 4 \
  --gold 300 --second-gold 0 --first team1

norrust_core/target/release/self-play \
  --scenario big_battle_6 --team1 undead --team2 undead \
  --ai1 greedy --ai2 greedy --games 1000 --seed 15001 --threads 4 \
  --gold 300 --second-gold 0 --first team2
```

Look-ahead versus greedy, initiative cells (Team 1 = look-ahead, Team 2 = greedy).
About 4–6 minutes per 100 games here:

```bash
norrust_core/target/release/self-play \
  --scenario big_battle_6 --team1 undead --team2 undead \
  --ai1 greedy-look-ahead --ai2 greedy --games 100 --seed 17001 --threads 4 \
  --gold 300 --second-gold 0 --first team1

norrust_core/target/release/self-play \
  --scenario big_battle_6 --team1 undead --team2 undead \
  --ai1 greedy-look-ahead --ai2 greedy --games 100 --seed 17101 --threads 4 \
  --gold 300 --second-gold 0 --first team2
```

On this board, side is fair, so two initiative cells with A on the left and B
on the right are enough for an algorithm comparison. If you change the map or
factions, use the four-cell design (swap sides **and** swap who moves first).

## Reading the summary

- **First-player wins** follow `--first`, not board side.
- **Team 1 / Team 2 wins** are left keep vs right keep (plus whatever AI you
  assigned there).
- Draws are safety-cap games.
- Recruits and ending gold catch recruitment or bonus bugs.

Record the exact command, seed range, `N`, wall-clock time, and git revision
with any reported numbers.

## Current baselines (Undead vs Undead, `big_battle_6`, 300g, `--second-gold 0`)

After 180-degree board symmetry and the shared ToD clock. Do not compare these
to older coin-flip numbers from the same-row-flip map.

**Greedy vs greedy** (1,000 games per initiative cell):

| First | First-player WR | Left | Right |
| --- | ---: | ---: | ---: |
| Left (`--seed 14001`) | 62.3% | 62.3% | 37.7% |
| Right (`--seed 15001`) | 61.1% | 38.9% | 61.1% |
| Combined | 61.7% | 50.6% | 49.4% |

Side is 50/50. First player has about a 12-point edge. Zero draws. ~20 recruits
per side. ~94 s per 1,000 games.

**Look-ahead vs greedy** (100 games per initiative cell; look-ahead on the left):

| First | Look-ahead | Greedy |
| --- | ---: | ---: |
| Look-ahead (`--seed 17001`) | 73 | 27 |
| Greedy (`--seed 17101`) | 80 | 20 |
| Pooled | **153 (76.5%)** | **47 (23.5%)** |

Look-ahead is stronger. It also won more often as **second** player (80/20)
than as first (73/27) in this sample. That is the opposite of the greedy-mirror
first-player edge; treat it as a real algorithm effect to re-check at larger
`N`, not as a board or clock bug.

Second-player gold to flatten greedy-mirror to 50/50 has **not** been tuned
yet. Default `--second-gold 5` is not that compensation.

## Implementation notes

- Binary: `norrust_core/src/bin/self_play.rs`
- Look-ahead planner: `norrust_core/src/ai.rs` (`ai_take_turn_greedy_lookahead`)
- Round clock: `GameState.sides_acted_this_round`; `turn` increments after both
  sides end a turn
- Board: `scenarios/big_battle_6/board.toml`
