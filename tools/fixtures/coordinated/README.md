# Coordinated gameplay fixtures

`mechanics.json` is the small tracked manifest consumed by
`tools.algorithm_strength --suite mechanics`. Each fixture is launched through
the production `self-play` dispatcher with a frozen seed, side, policies, and
turn cap. Assertions inspect the recorded engine result; a label in the fixture
does not make a mechanism pass.

The first fixture proves a complete terminal game selected and executed by the
coordinated player. Later stacks may add focused legal states and additional
assertion kinds, but they must keep the manifest schema small and provide a
known failing mutation for every new assertion.
