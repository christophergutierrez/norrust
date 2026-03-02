# Bridge API Reference

> **Status: Placeholder** — This document needs to be written.

## Purpose

Complete reference for the GDExtension bridge (`NorRustCore`) exposed by `norrust_core`.
Intended for anyone building against the engine: external AI clients, tool developers, and
contributors adding new bridge methods.

## What this document will cover

### Method reference
Every public `#[func]` on `NorRustCore`, with:
- Signature (GDScript and Rust)
- Parameters and valid ranges
- Return value semantics
- Side effects and preconditions (e.g., "requires create_game() to have been called first")

### Error code table
The full set of integer error codes returned by action methods:

| Code | Meaning |
|------|---------|
| 0 | Success |
| -1 | Unit not found |
| -2 | Not your turn |
| -3 | Destination out of bounds |
| -4 | Destination occupied |
| -5 | Unit already moved |
| -6 | Destination unreachable |
| -7 | Not adjacent (attack) |
| -8 | Advancement not pending |
| -9 | No advancement target |
| -10 | Advancement target not in registry |
| -99 | JSON parse error (apply_action_json only) |

### JSON schemas
Annotated schemas for:
- `StateSnapshot` — the full game state as returned by `get_state_json()`
- `ActionRequest` — all action variants with field descriptions and examples

### Startup sequence
The required call order: `load_data()` → `create_game()` → `generate_map()` → `place_unit_at()` × N

### Coordinate conventions
How offset (col, row) coordinates map to the board, and where the cubic hex conversion happens.
