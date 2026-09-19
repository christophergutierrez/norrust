# Tactical alternative comparison

`tools/tactical_comparison.py` runs a small, repeatable offline comparison for
the tracked recruiter-survival fixture. It starts one isolated source-matched
driver for each case, submits the frozen option batch and an empty
`FinishWithGreedy` boundary, and waits for the next model checkpoint. The
boundary therefore includes one actual Greedy opponent turn. It records
recruiter survival and HP, known unit losses, village ownership changes,
committed option IDs, checkpoint RNG/save-state evidence, and the exact
evidence coverage. Values unavailable in the engine evidence are reported as
unknown or omitted according to the result shape.

The fixture is revision 231, side-turn 12, from
`tools/fixtures/recruiter_survival/fixture_1_seed_4477_defensive`. Its source
checkpoint and metadata hashes are recorded in `stack4_reference.json`. The
current routine packet reports occupied-board attacker counts; open-board
counts are unavailable and are not inferred as zero.

Build and run from the repository root:

```sh
cargo build --manifest-path norrust_core/Cargo.toml --bin greedy_driver
NORRUST_TEST_DRIVER="$PWD/norrust_core/target/debug/greedy_driver" \
  python3 -m tools.tactical_comparison \
  --output tmp/tactical-comparison.json
```

The four cases are recruiter relocation plus two known-damage attacks,
pressure from up to three distinct actors, an empty no-sweep boundary, and the
first issued option. Every submitted batch is whole-batch validated, including
the no-sweep boundary, before execution. The helper stops only after Greedy
events and a controlled-faction model checkpoint at side-turn 14. If the
opponent turn produces a real winner terminal first, it reports the embedded
terminal state and winner instead of inventing a later model checkpoint.
