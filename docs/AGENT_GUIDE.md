# AI Agent Guide

> **Status: Placeholder** — This document needs to be written.

## Purpose

A practical guide for building an agent that plays NorRust. Written from the perspective of
something that wants to *play* the game well, not understand its internals. Assumes the reader
has read `BRIDGE_API.md` for the raw API contract.

## What this document will cover

### Turn lifecycle
How a full game loop works: active_faction, what EndTurn does, when healing happens,
how time of day advances, and the win condition.

### Reading the state
A field-by-field walkthrough of the `StateSnapshot` JSON — what `moved`, `attacked`,
`advancement_pending`, `xp`/`xp_needed` mean in practice, and which fields matter most
for decision-making.

### Legal moves
What makes an action valid: movement budget, ZOC (Zone of Control) and how it constrains
movement near enemies, adjacency requirement for attacks, the one-move-one-attack-per-turn rule.

### Action reference
Every action variant with concrete examples, common rejection reasons, and the corresponding
error codes to handle.

### Terrain and its effects
How terrain affects movement cost and combat defense. The terrain types currently
on the default map (flat, forest, hills, mountains, village, castle, keep) and their practical impact.

### Combat math
How hit probability, time-of-day modifiers, and resistances interact. What information
is available to an agent before committing to an attack (expected damage is calculable
from the state).

### The baseline AI
What the built-in greedy AI does (`ai_take_turn`): N=0 lookahead, expected-damage scoring,
kill bonus x3. Its known weaknesses — no positional awareness, ignores terrain defense,
doesn't block — which a better agent should exploit or avoid replicating.

### Advancement
When `advancement_pending` is true, how to trigger it and what changes on the unit.

### Integration
How to connect an external agent to the C ABI bridge — either directly via FFI from any
language with C interop, or via a future TCP/socket transport layer.
