# MEMORYLESS TACTICAL PLAYBOOK

Apply this deterministic algorithm on every turn:

1. Treat recruiter survival as non-negotiable. Keep your recruiter on or near the keep, behind a screen, and never advance it merely to seek combat. Identify threats to it before choosing actions.
2. Read the authoritative `turn_options` and `recruit_options`. Use the supplied positions and `target_ids` exactly; do not invent coordinates, targets, paths, or legality.
3. Build legal action candidates in this priority order, rejecting any candidate that needlessly exposes your recruiter:
   1. Kill the enemy recruiter when a lethal sequence is available.
   2. Save your threatened recruiter by removing the threat, retreating, or restoring its screen.
   3. Focus-fire a kill instead of spreading damage.
   4. Improve economy and advancement: move non-recruiters off castle hexes to free future placements, spend gold and recruit when legal, then take useful advances or forward positions.
4. Scan every friendly unit for legal attacks and useful moves; do not passively wait. When a reachable destination exposes a desired `target_id`, emit its `Move` immediately followed by the matching `Attack`.
5. Plan against sequential mutation: reserve a unique destination for each move and ensure every later action remains valid after earlier actions execute. Avoid speculative, unreachable, or redundant actions.
6. Emit `EndTurn` only after every unit and the recruitment and advancement options have been considered.
