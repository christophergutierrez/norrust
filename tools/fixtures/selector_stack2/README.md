# Coordinated selector Stack 2 fixtures

These four files are compact Rust `SelectorRequest` v1 envelopes captured for
prompt construction tests. They contain candidate summaries only: executable
orders, maps, history, and model reasoning are intentionally absent.

The controlled-side perspective is fixed by `side`; all deltas are measured
from that side. `opponent_response_delta` describes the modeled response after
the candidate's completed turn.
