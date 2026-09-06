# Domain glossary

- **Model-controlled side**: The faction whose actions are selected by a model through the LLM client. The client must never submit actions for another faction.
- **Greedy opponent turn**: One transactional opponent side-turn comprising driver recruitment, greedy movement and combat, and a successful turn boundary.
- **Side-turn safety cap**: An external maximum number of completed faction turns accepted by the headless driver. It is distinct from the engine's displayed round number and scenario turn-limit win condition, which the headless `greedy_driver` disables.
- **Model prompt contract**: The complete instructions and data delivered to a memoryless model for one decision. It must be sufficient to encode legal actions without consulting repository documentation.
- **Infrastructure-invalid terminal**: `setup_error`, `timeout`, `eof`, `infrastructure_failure`, or an unknown/malformed terminal reason. The client exits nonzero; it is never recorded as a draw, loss, winner, or completed side turn.
- **Gameplay-valid terminal**: `winner` or `max_turns`. These are valid match outcomes; `max_turns` is the external completed-side-turn safety cap.
- **Infrastructure failure**: A driver, client, query, or opponent-execution failure that invalidates a match result. It is never recorded as a draw, loss, or completed side turn.
