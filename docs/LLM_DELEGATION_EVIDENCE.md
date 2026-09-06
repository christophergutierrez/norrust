# LLM delegation evidence evaluations

The client gives the model authoritative board, threat, economy, and review facts.
`DoneWithImportantMoves` and `EndTurn` invoke an eligibility-based greedy sweep;
eligibility does not establish tactical safety. `FinishWithGreedy` groups and holds
let the model preserve a chosen position. The client can run one fixed-seed,
isolated bounded review of a candidate finish plus one greedy opponent response.
That result is an illustration with explicit policy and coverage labels, not a
probability or strategic recommendation.

The verified corrected Luna cohort is archived under
`tmp/llm_delegation_evidence_final2/`, with SQLite catalog
`tmp/llm_delegation_evidence_final2/history.sqlite`. It contains three gameplay-valid
matches from source commit `5e235eec88ad18e888c04b908416bc1c5fbe2399` and no
infrastructure failures. Per-game reports and `REVIEW.md` are beside the logs.

When analyzing these games, read the SQLite catalog first, then the original
NDJSON/checkpoints for prompt and request evidence. Historical model summaries may
omit review context; absence in a summary is unknown. Do not infer tactical quality
from a winner, action count, or a single bounded rollout.
