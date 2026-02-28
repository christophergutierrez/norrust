---
phase: 05-ai-hooks
plan: 01
subsystem: api
tags: [json, serde, gdextension, ai-hooks, serialization]

requires:
  - phase: 04-game-loop-polish
    provides: complete GameState with units, board, terrain, turn tracking

provides:
  - StateSnapshot: serializable view of GameState (turn, faction, board dims, terrain, units)
  - ActionRequest: JSON-deserializable action enum (Move/Attack/EndTurn)
  - get_state_json() bridge: GDScript → full JSON game state
  - apply_action_json() bridge: GDScript ← JSON action string → applies to game

affects: future-socket-server

tech-stack:
  added:
    - serde_json = "1"
  patterns:
    - "Snapshot pattern: read-only view struct separate from mutable GameState"
    - "serde(tag=action) internally-tagged enum for action dispatch"
    - "AC-4 sentinel: -99 = JSON parse error (distinct from -1..-7 ActionError codes)"

key-files:
  created:
    - norrust_core/src/snapshot.rs
  modified:
    - norrust_core/Cargo.toml
    - norrust_core/src/lib.rs
    - norrust_core/src/gdext_node.rs

key-decisions:
  - "StateSnapshot as a flat DTO (not Serialize on GameState directly) — avoids HashMap<Hex,_> key issues and RNG serialization"
  - "JSON action uses internally-tagged enum: {\"action\":\"Move\",...} — idiomatic, readable for AI agents"
  - "-99 as parse-error sentinel — distinct from all ActionError codes (-1 through -7)"
  - "board.width/height mapped to cols/rows in JSON — matches GDScript and bridge API terminology"

patterns-established:
  - "All external-facing data goes through snapshot.rs — GameState internals stay opaque"
  - "apply_action_json() reuses apply_action() + action_err_code() — no duplicate logic"

duration: ~10min
started: 2026-02-28T00:00:00Z
completed: 2026-02-28T00:00:00Z
---

# Phase 5 Plan 01: JSON State Export + Action Submission Summary

**JSON serialization layer added: `get_state_json()` and `apply_action_json()` bridge methods expose the full game engine to external AI clients.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~10 min |
| Tasks | 2 auto |
| Files modified | 4 |
| Tests | 36 pass (30 existing + 6 new snapshot tests) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: State JSON Contains All Game Data | Pass | StateSnapshot serializes turn, faction, cols, rows, terrain[], units[] |
| AC-2: EndTurn Action Submitted via JSON | Pass | `{"action":"EndTurn"}` → ActionRequest::EndTurn → Action::EndTurn → apply_action() |
| AC-3: Move Action Submitted via JSON | Pass | `{"action":"Move","unit_id":1,"col":2,"row":2}` round-trip proven in unit tests |
| AC-4: Invalid JSON Returns -99 | Pass | serde_json parse error → return -99; game state unchanged |

## Accomplishments

- Created `snapshot.rs` with `StateSnapshot`, `UnitSnapshot`, `TileSnapshot`, and `ActionRequest` — all with serde derives and 6 unit tests
- Added `serde_json` dependency; snapshot types fully decoupled from GameState internals
- `get_state_json()` and `apply_action_json()` registered as `#[func]` in NorRustCore — callable from GDScript immediately
- 36/36 tests pass; build clean; `.so` deployed to `norrust_client/bin/`

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/snapshot.rs` | Created | StateSnapshot DTO, ActionRequest enum, 6 unit tests |
| `norrust_core/Cargo.toml` | Modified | Added `serde_json = "1"` |
| `norrust_core/src/lib.rs` | Modified | Added `pub mod snapshot;` |
| `norrust_core/src/gdext_node.rs` | Modified | Added `get_state_json()` and `apply_action_json()` #[func] methods |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Flat DTO (StateSnapshot) instead of Serialize on GameState | GameState has HashMap<Hex,_> keys and SmallRng — neither serializes cleanly | Clean JSON output; no derive pollution on internal types |
| `#[serde(tag = "action")]` internally-tagged enum | Idiomatic JSON for discriminated unions; readable by LLMs and Python scripts | `{"action":"Move",...}` format |
| -99 parse error sentinel | Must be distinct from ActionError codes -1..-7 | AI clients can distinguish bad JSON from valid-but-rejected actions |
| board.width/height → cols/rows in JSON | Consistent with bridge API terminology throughout GDScript and gdext_node.rs | External clients use the same coordinate language |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Minor field name correction |
| Scope additions | 0 | — |
| Deferred | 0 | — |

**Total impact:** One trivial fix; no scope creep.

### Auto-fixed Issues

**1. Board field names: width/height not cols/rows**
- **Found during:** Task 1 (reading board.rs before writing snapshot.rs)
- **Issue:** Plan referenced `state.board.cols`/`state.board.rows`; actual fields are `board.width`/`board.height`
- **Fix:** Used `state.board.width`/`state.board.height` in snapshot.rs; JSON output still uses `cols`/`rows` keys for external consistency
- **Files:** `norrust_core/src/snapshot.rs`
- **Verification:** Tests pass with correct field names

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- JSON bridge is live in GDExtension — any GDScript code can call `get_state_json()` and `apply_action_json()` today
- The external API surface is clean: one JSON in, one JSON out
- Socket server (future): a background Rust thread + channel would relay these two calls to TCP clients

**Concerns:**
- Socket server deferred — an external Python agent cannot connect at runtime without it
- The v0.1 success criterion "External Python script can query game state and submit actions via socket" remains partially unmet (JSON layer exists; socket transport does not)

**Blockers:** None for Phase 5 plan 01 as scoped. Socket server is a separate future decision.

---
*Phase: 05-ai-hooks, Plan: 01*
*Completed: 2026-02-28*
