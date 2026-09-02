# Norrust LLM client

`tools/llm_client.py` drives the headless `greedy_driver` through a
provider-neutral `ModelBackend`. The model receives a canonical `state` line,
returns one JSON action array ending in `EndTurn`, and never emits `Query`.

Queries are singleton JSON-lines requests and receive `status` replies. Action
lines receive a `status`, followed by zero or more event envelopes and then a
new boundary `state` or terminal `game_end`. Events are authoritative engine
facts; clients must not simulate them locally.

Example deterministic run:

```bash
python -m tools.llm_client --orders-file orders.jsonl --log match.ndjson
```

The header records the side, faction pair, seed, opponent policy, assistance
mode, cadence, recruiter-loss win rule, and model order/query counts so runs with different
conditions are not compared as one experiment.
