# Seed 2001 revision 286

This fixture freezes the final seed-2001 model boundary before the historical
preview failure. It is a model-boundary checkpoint at state revision `286`
after ten completed side turns, with controlled side `0`; dead unit `U21` is
absent from the checkpoint. The archived draft in `failed-response.json`
still delegates `U21`, which makes the driver's `preview_batch` contract return
`unauthorized_unit`.

Source evidence:

- Log: `tmp/luna-final-20260907/seed-2001/match.ndjson`
- Source request: `e501a94e8c5f4c9087c15ac1c0f9751e:request:24`
- Source commit: `3c630e133f3c9ecc49a3579eaa2ef6364c43ea11`
- Source prompt hash: `247c51c60e9673465fb13a9aee10c979b0f5386fd880e9724f0ef5d94ba6e6b1`
- Source response SHA-256: `99361c7ac000bcfe0438ce473576bc7da8a3348bd9a658a4c2daaf865f717223`
- Checkpoint SHA-256: `85e1e79beca194a4db8c663604536ea34d1c128fe7f549990acabda084ec83fe`
- Board SHA-256: `26366c43a231ef9f7244b24fb74fe5343792c2c26bc0366941a097ce3c7c4207`

The checkpoint contains the historical absolute board path. To relocate it,
copy `checkpoint.json` to a temporary checkpoint directory and replace only
the `board_path` fields in the checkpoint envelope and nested `save_state`
with the absolute path to this checkout's
`scenarios/big_battle_6/board.toml`. Recompute the checkpoint file digest after
that relocation and pass the relocated file with `--resume-checkpoint`; the
driver verifies the board hash and match identity.
