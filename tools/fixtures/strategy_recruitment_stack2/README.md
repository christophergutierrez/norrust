# Stack 2 recruitment portability fixture

`revision_18/checkpoint.json` is the minimal tracked extraction for the two
historical Stack 2 recruitment-capacity checks in
`tools/test_strategy_recruitment_stack2.py`. It preserves the complete
revision-18 board state needed by `routine_next`; the tests materialize the
`__SCENARIO_BOARD__` placeholder against the checked-out board after verifying
its SHA-256, then give the temporary checkpoint the digest-named filename
required by `greedy_driver`.

Provenance:

- Source archive checkpoint:
  `tmp/glm-strategy-release-20260915T132431Z/recording/glm-strategy/match.ckpt/0-18-partial-e72c444810fa8158c2c2368e9b8cb3d5c180d7efa314f23c440e12bd93531cb8.json`
- Source checkpoint SHA-256: `e72c444810fa8158c2c2368e9b8cb3d5c180d7efa314f23c440e12bd93531cb8`
- Source match archive SHA-256:
  `72e734f5cb0543d54ba1d0de1667e14fdf7b8441bddf0da000973b371ebc2636`
- Source run commit: `bcbdba5287455b2d0f3cd10fe9b57ba5e6243dd8`
- Tracked fixture SHA-256: `91af56db4d4753000833633f1c70b61c54538a4ae5af968d358397a854d6cda8`

The tracked extraction preserves the source checkpoint fields, including
`advancement_pending` on every unit. Only the board path is replaced with the
checked-out `board.toml` at test runtime after the recorded board hash is
verified. No ignored transcript or paid-game artifact is copied.
