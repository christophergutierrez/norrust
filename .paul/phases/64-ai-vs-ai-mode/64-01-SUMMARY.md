---
phase: 64-ai-vs-ai-mode
plan: 01
subsystem: agent-interface
tags: [ai, automation, tcp, python, testing]

requires:
  - phase: 63-tcp-agent-server
    provides: TCP agent server + Python client library
provides:
  - Python AI vs AI script for automated game testing
  - Love2D --ai-vs-ai built-in mode for visual automated play
affects: []

tech-stack:
  added: []
  patterns: [timer-based AI loop in love.update, shared table for AI state]

key-files:
  created: [tools/ai_vs_ai.py]
  modified: [norrust_love/main.lua, norrust_love/agent_server.lua]

key-decisions:
  - "AI vs AI uses ai_take_turn (no end_turn needed — AI calls EndTurn internally)"
  - "--ai-vs-ai also starts agent server for external observation"
  - "Animation guard: skip AI turn while move/combat animations playing"

patterns-established:
  - "Timer-gated AI loop in love.update with animation guards"

duration: ~20min
started: 2026-03-06
completed: 2026-03-06
---

# Phase 64 Plan 01: AI vs AI Mode Summary

**Python script and Love2D built-in mode for automated AI vs AI games — both factions play via greedy AI with turn-by-turn output.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~20min |
| Started | 2026-03-06 |
| Completed | 2026-03-06 |
| Tasks | 3 completed (2 auto + 1 checkpoint) |
| Files modified | 3 (1 created, 2 modified) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Python AI vs AI plays complete game | Pass | Faction 1 wins in 6 rounds on Crossing |
| AC-2: Love2D --ai-vs-ai auto-plays both factions | Pass | User confirmed visual mode works |
| AC-3: Turn delay configurable | Pass | --ai-delay flag parsed; default 0.5s in Love2D, 0.0 in Python |

## Accomplishments

- tools/ai_vs_ai.py: Python script loops ai_turn for both factions over TCP, prints per-turn stats, declares winner
- Love2D --ai-vs-ai mode: timer-based AI loop in love.update with animation guards and configurable delay
- --ai-vs-ai also starts agent server automatically for external observation

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `tools/ai_vs_ai.py` | Created | Python AI vs AI automation script |
| `norrust_love/main.lua` | Modified | --ai-vs-ai + --ai-delay CLI flags, AI loop in love.update |
| `norrust_love/agent_server.lua` | Modified | Fix empty string → "{}" for get_state before scenario load |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| ai_take_turn only (no explicit end_turn) | AI's ai_take_turn already calls EndTurn internally | Simpler loop |
| --ai-vs-ai auto-starts agent server | Allows external tools to observe while AI plays | Dual-use |
| Animation guards before AI turn | Prevents AI acting during visual transitions | Clean visuals |
| AI state in shared table | Avoids LuaJIT 60-upvalue pressure | Consistent pattern |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Essential fix |
| Deferred | 0 | None |

**Total impact:** One essential fix to agent_server.

### Auto-fixed Issues

**1. Empty state JSON from agent_server before scenario load**
- **Found during:** Task 3 (human verification)
- **Issue:** get_state_raw() returns empty string "" before a scenario is loaded; `or "{}"` only catches nil
- **Fix:** Added explicit `state_json == ""` check in agent_server.lua process_command
- **Files:** norrust_love/agent_server.lua

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Python client crashed on empty JSON before scenario selected | Fixed agent_server to return "{}" for empty state |

## Next Phase Readiness

**Ready:**
- v2.2 AI & Agents milestone complete (all 3 phases done)
- Claude can now test games directly via Python or observe via Love2D

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 64-ai-vs-ai-mode, Plan: 01*
*Completed: 2026-03-06*
