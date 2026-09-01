# Headless Self-Play and Balance Testing

Use the Rust `self-play` binary for reproducible AI-versus-AI simulations. Run
commands from the repository root unless noted otherwise.

## Neutral test board

Use `big_battle_6` for the current large-board baseline. It is a 24×14 board
with row-wise mirrored terrain, mirrored keep coordinates, six legal
recruitment slots per keep, and three villages per side. Its two 1,000-game
greedy mirror batches were empirically near-balanced.

This is not yet a mathematically neutral hex graph. The tile transformation
`(col, row) → (23 - col, row)` does not preserve every adjacency on an odd-r
offset grid. Therefore, always swap factions/algorithms across both board sides
using the four-cell design below. Do not attribute a small side difference to a
faction or algorithm merely because the TOML rows mirror visually. A future
strictly symmetric board should use an adjacency-preserving transformation,
such as a correctly constructed 180-degree rotation, and establish a new
baseline.

Do not use `final_battle` as a neutral balance board. It is the final map of the
`tutorial` campaign and is intentionally asymmetric: the left side has nine
villages while the right side has six, and much of its terrain is not mirrored.
Self-play removes its campaign objective, but it does not remove those map-side
differences.

The scenario validation test protects `big_battle_6`'s dimensions, keeps,
castle slots, village count, and row-wise tile symmetry. Compile that test
surface and run an independent data check before balance simulations:

```bash
cargo check --release --manifest-path norrust_core/Cargo.toml --tests

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
    terrain(col, row) == terrain(width - 1 - col, row)
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

assert keeps == [(2, 7), (21, 7)]
assert len(villages) == 6
assert sum(col < width // 2 for col, _ in villages) == 3
assert all((width - 1 - col, row) in villages for col, row in villages)

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
```

The focused `scenario_validation` integration test currently cannot link
because the package emits colliding `cdylib`, `rlib`, and `self-play` artifacts.
Treat that as a known build-system limitation, not as a passing test. The
compile check and independent structural check above must both pass; do not
silently ignore either failure.

## Canonical fair mirror test

Build once, then time the binary rather than including compilation in the
runtime:

```bash
cargo build --release --manifest-path norrust_core/Cargo.toml --bin self-play

time -p norrust_core/target/release/self-play \
  --scenario big_battle_6 \
  --team1 undead --team2 undead \
  --ai1 greedy --ai2 greedy \
  --games 1000 --seed 1 --threads 4 \
  --gold 300 --second-gold 0 --first coin-flip
```

The fairness options are intentionally explicit:

- `--gold 300` gives both sides equal starting gold.
- `--second-gold 0` disables second-player compensation. The CLI default is
  currently five, so omitting this option changes the experiment.
- `--first coin-flip` uses the deterministic initiative stream. The CLI default
  is Team 1 first.
- `--seed 1` makes the batch reproducible.

Self-play uses symmetric elimination victory. Campaign objectives and
attacker/defender timeout victories are disabled. `--max-turns N` controls a
workload safety loop of `2*N+2` faction turns; it is not an exact “draw at round
N” rule, and an unresolved game can report a turn greater than N. Games that
exhaust this loop without elimination are recorded as draws.

For an independent repeat, use a non-overlapping input-index range:

```bash
time -p norrust_core/target/release/self-play \
  --scenario big_battle_6 \
  --team1 undead --team2 undead \
  --ai1 greedy --ai2 greedy \
  --games 1000 --seed 1001 --threads 4 \
  --gold 300 --second-gold 0 --first coin-flip
```

`--seed S --games N` uses input indices `S` through `S+N-1`. The `seed` column
printed by `--verbose` is the mixed internal game seed, not an input accepted
for direct replay. To replay game number `k` from a batch beginning at S, use
`--seed S+k-1 --games 1` with every other option unchanged. Do not call a
deterministic rerun with the same input-index range an independent replication:
it should reproduce the same games exactly.

## Reading the summary

Team identity and initiative are separate measurements:

- Team 1 always starts at the left keep; Team 2 starts at the right keep.
- “First-player wins” follows the initiative assignment, regardless of team.
- Team 1 and Team 2 wins measure board side plus the selected faction/AI.
- Draws are games that reached the safety cap without elimination.
- Turn statistics are minimum, Q1, median, Q3, and maximum.
- Winning material advantage is the surviving unit-cost difference.
- Starting gold, ending gold, and recruit counts help detect recruitment or
  bonus-allocation bugs.

Use `--verbose` to print a CSV header and one row per game. Use `--compact` for
one comma-separated batch summary. These modes are mutually exclusive.

Always preserve the exact command, input-index range, game count, runtime, and
code revision with reported results. For at least 1,000 games, a result a few
percentage points from 50% can still be sampling noise; repeat with disjoint
input-index ranges before diagnosing a bias.

## Comparing factions or algorithms

A single A-versus-B batch confounds algorithm/faction strength, board side, and
initiative. Run the full four-cell design with the same input-index range and
no gold bonus:

| Cell | Team 1 / left | Team 2 / right | First mover |
| --- | --- | --- | --- |
| 1 | A | B | Team 1 |
| 2 | A | B | Team 2 |
| 3 | B | A | Team 1 |
| 4 | B | A | Team 2 |

Replace A and B with factions while keeping the AI fixed, or with AI algorithms
while keeping the faction fixed. Aggregate A's wins over all four cells, then
also report results split by side and initiative. If runtime permits, repeat
the four cells with a disjoint input-index range.

Available algorithms are `greedy`, `greedy-look-ahead`, and `random`.
Look-ahead is substantially slower than greedy, so use a few behavior-inspection
games first and estimate runtime before selecting the final sample size. Do not
present a tiny behavior check as balance evidence.

## Big Battle 6 baseline

The following baseline was recorded on 2026-09-01 with Undead versus Undead,
greedy versus greedy, 300 gold each, no second-player bonus, and deterministic
coin-flip initiative:

| Input-index range | Games | First wins | Team 2/right wins | Turns min/Q1/median/Q3/max | Runtime |
| --- | ---: | ---: | ---: | --- | ---: |
| 1–1000 | 1,000 | 52.1% | 52.6% | 11 / 14 / 15 / 18 / 30 | 96.6 s |
| 1001–2000 | 1,000 | 51.1% | 50.9% | 11 / 14 / 15 / 18 / 33 | 94.1 s |
| Combined | 2,000 | 51.6% | 51.75% | median 15, IQR 14–18 | — |

Both batches had zero draws and averaged exactly 20.0 recruits per side. The
combined initiative and side results are consistent with 50/50; use median 15
turns and IQR 14–18 as the comparison baseline for other symmetric Big Battle
boards.

## CLI reference

Print the current options rather than relying on copied documentation. The
current explicit help path prints successfully but exits with status 2, so the
following form remains safe in a shell using `set -e`:

```bash
norrust_core/target/release/self-play --help || [ "$?" -eq 2 ]
```

The source of truth for argument parsing and summary fields is
`norrust_core/src/bin/self_play.rs`.
