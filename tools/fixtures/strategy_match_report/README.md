# Primary match report portability fixture

`primary_reduced.ndjson` is the tracked, relocatable input for the primary
archive regression in `tools/test_match_report.py`. It retains the model
request and strategy linkage records, the checkpoint references needed for
decisive decisions, and the recruiter state and events needed to prove the
final death location. Large prompts, transcripts, unrelated driver state, and
other archive-only records are omitted.

Provenance:

- Source archive:
  `tmp/glm-luna-fullgame-20260917T042432Z/recording/glm-luna-fullgame/match.ndjson`
- Original archive SHA-256:
  `fd771d5c4bfd163cbe4592fe1c761ac8a9fa14b570ff7fb81a07b65ae114b5e8`
- Reduced fixture SHA-256:
  `2745a3ee212865b42ad49f868009b98bf89c427178927af2def0598128f316e6`

The test reads this fixture from the repository checkout and does not require
the ignored source archive or any paid backend call.
