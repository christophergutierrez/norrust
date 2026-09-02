# Domain glossary

- **Model-controlled side**: The faction whose actions are selected by a model through the LLM client. The client must never submit actions for another faction.
- **Greedy opponent turn**: One transactional opponent side-turn comprising driver recruitment, greedy movement and combat, and a successful turn boundary.
- **Side-turn safety cap**: The maximum number of completed faction turns accepted by the driver. It is distinct from the engine's displayed round number and scenario turn limit.
- **Model prompt contract**: The complete instructions and data delivered to a memoryless model for one decision. It must be sufficient to encode legal actions without consulting repository documentation.
- **Infrastructure failure**: A driver, client, query, or opponent-execution failure that invalidates a match result. It is never recorded as a draw, loss, or completed side turn.
