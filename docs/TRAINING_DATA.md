# Training data workflow

The history database is the source of truth. Evaluation runs add assessments;
they do not rewrite games, requests, or actions. A training export selects
decision records by pinned evaluation-run IDs and writes a manifest with the
selection rule, renderer version, source IDs, split policy, and output hash.

Mechanical validity means that the recorded response was available, parseable,
owned by the correct side, and accepted by the engine when that evidence exists.
It does not mean the move was strategically good. The initial action dataset
therefore requires an explicit review approval in addition to mechanical validity.
Unknown evidence remains unknown.

Generated greedy actions stay attributed to the algorithm. A model-authored
handoff remains the target when the action-only dataset includes handoffs.
Optional rationale data is exported only when it was actually recorded and
approved. The exporter does not invent hidden chain of thought.

Decision annotations are bounded self-reports attached to the exact model
request and authored action indices. They record cited playbook rules, expected
effect, and stated risk; they are evidence about what the model said, not proof
that its citation was followed or that the move was good. Valid annotations are
stored as `decision_annotation_v1` rationale records. Missing or invalid data
remains unknown and lowers explanation coverage. Tool requests, discarded
drafts, and generated greedy actions are excluded from the eligible denominator.
