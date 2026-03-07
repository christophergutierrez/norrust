---
phase: 63-tcp-agent-server
plan: 01
subsystem: agent-interface
tags: [tcp, socket, python, agent, api, luasocket]

requires:
  - phase: 62-campaign-ux-polish
    provides: Stable game client with campaign UX
provides:
  - TCP agent server exposing JSON action API over localhost
  - Python client library for programmatic game control
  - get_state_raw() FFI wrapper for JSON relay
affects: [64-ai-vs-ai-mode]

tech-stack:
  added: [LuaSocket (bundled with Love2D)]
  patterns: [non-blocking TCP in love.update, line-based protocol, shared table for upvalue overflow]

key-files:
  created: [norrust_love/agent_server.lua, tools/agent_client.py]
  modified: [norrust_love/main.lua, norrust_love/norrust.lua]

key-decisions:
  - "Lua-side TCP server (not Rust) — keeps core pure, avoids threading"
  - "Line-based protocol: command\\n → response\\n"
  - "shared table for agent_mod + agent handle (upvalue consolidation)"
  - "Server survives client disconnects (send error detection)"

patterns-established:
  - "shared table for upvalue overflow beyond combat_state/recruit_state"
  - "Non-blocking TCP via LuaSocket settimeout(0) in love.update"

duration: ~30min
started: 2026-03-06
completed: 2026-03-06
---

# Phase 63 Plan 01: TCP Agent Server Summary

**Non-blocking TCP server in Love2D exposing JSON game API to external Python agents over localhost:9876.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30min |
| Started | 2026-03-06 |
| Completed | 2026-03-06 |
| Tasks | 4 completed (3 auto + 1 checkpoint) |
| Files modified | 4 (2 created, 2 modified) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: TCP server accepts connections and serves state | Pass | get_state returns full JSON, server survives reconnects |
| AC-2: TCP server accepts action commands | Pass | EndTurn returns "0", JSON actions work |
| AC-3: TCP server supports ai_turn command | Pass | ai_turn FACTION triggers built-in AI |
| AC-4: Python client can play a complete turn | Pass | Verified: get_state, EndTurn, get_state round-trip |

## Accomplishments

- agent_server.lua: non-blocking TCP server using LuaSocket in Love2D update loop
- Line-based protocol: get_state, get_faction, check_winner, ai_turn, ActionRequest JSON
- tools/agent_client.py: Python stdlib client with convenience methods (end_turn, move_unit, attack, ai_turn)
- --agent-server CLI flag + P key toggle for runtime control
- Server survives client disconnects, accepts multiple sequential connections

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/agent_server.lua` | Created | Non-blocking TCP server module |
| `tools/agent_client.py` | Created | Python stdlib client library |
| `norrust_love/main.lua` | Modified | --agent-server flag, P key toggle, love.quit cleanup, shared table |
| `norrust_love/norrust.lua` | Modified | get_state_raw() for JSON string relay |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Lua-side TCP (not Rust) | Keeps Rust core pure; no threading; LuaSocket available in Love2D | Simple, no Rust changes |
| Line-based protocol | Simple, debuggable with nc/telnet; newline delimiter | Easy to implement clients |
| Non-blocking in love.update | No threads needed; settimeout(0) on all sockets | ~0 overhead when no clients |
| shared table for upvalue overflow | agent_server + agent_handle pushed love.keypressed over 60 | Reusable pattern |
| Port 9876 | Unlikely to conflict; easy to remember | Hardcoded, could be parameterized later |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 2 | Essential fixes |
| Deferred | 0 | None |

**Total impact:** Two essential fixes during implementation.

### Auto-fixed Issues

**1. LuaJIT 60-upvalue limit in love.keypressed**
- **Found during:** Task 2 (wiring into main.lua)
- **Issue:** agent_server + agent_handle as new locals pushed upvalue count over 60
- **Fix:** Created `shared` table storing agent_mod and agent handle
- **Files:** norrust_love/main.lua

**2. Client disconnect crash**
- **Found during:** Task 4 (human verification)
- **Issue:** send() on closed socket not handled; disconnect detection relied only on receive error
- **Fix:** Added send error detection, moved disconnect check before timeout branch
- **Files:** norrust_love/agent_server.lua

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| get_state returns parsed Lua table, not raw JSON | Added get_state_raw() to norrust.lua |
| Server appeared to stop after client disconnect | Fixed: server was fine, client just closed — improved error handling to be safe |

## Next Phase Readiness

**Ready:**
- TCP server operational, Python client verified
- Foundation for Phase 64: AI vs AI Mode
- ai_turn command already exposed — Phase 64 can drive both factions via Python

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 63-tcp-agent-server, Plan: 01*
*Completed: 2026-03-06*
