# Norrust task routing

For a request to play headless Norrust games, read `docs/LLM_CLIENT.md` first.
Use its client-generated prompt and supported backend examples. The player does
not need to explore the repository or read `.paul`, bridge documentation, or
temporary backend scripts unless a concrete setup failure requires it.

For recorded-game analysis, read `docs/AGENT_GUIDE.md` and `docs/GAME_HISTORY.md`,
then inspect the SQLite catalog before individual archives. Treat missing usage,
reasoning, prompt, and boundary data as unknown.

For engine or workflow development, consult the relevant source and development
documentation. `.paul` contains development history and is relevant only when the
task explicitly concerns that workflow.

When asked to run several model games, isolate each game's log, checkpoint,
request journal, and session sidecar. Preserve the canonical prompt unchanged
through any file backend, and report the source commit and evidence coverage.
