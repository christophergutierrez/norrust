---
phase: 91-save-naming
plan: 01
completed: 2026-03-08
duration: ~15min
---

# Phase 91 Plan 01: Save Naming Summary

**Display name field in save files with rename UI in save management screen. Players label saves with custom names shown as primary text in the save list.**

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Display Name in Save File | Pass | `display_name = ""` serialized in [game] section |
| AC-2: Display Name Shown in Save List | Pass | Primary label with dimmer date/scenario/turn as secondary |
| AC-3: Rename Prompt | Pass | 'R' key opens text input bar at bottom, pre-fills current name |
| AC-4: Text Input and Confirm | Pass | Enter saves, Escape cancels, backspace deletes |

## Accomplishments

- **display_name field** — empty string default in write_save, extracted in list_saves header scan
- **save.update_display_name()** — targeted TOML string replacement without full re-parse
- **Rename UI** — text input bar with blinking cursor, love.textinput callback for character input
- **Two-line save entries** — display_name as primary label, metadata as secondary dimmer line
- **Row height increased** to 32px to accommodate two-line entries

## Files Modified

| File | Change | Purpose |
|------|--------|---------|
| norrust_love/save.lua | Modified | display_name in write_save, list_saves extraction, update_display_name() |
| norrust_love/draw.lua | Modified | Two-line save entries, rename prompt bar, [R] Rename hint |
| norrust_love/input.lua | Modified | R key handler, rename mode key interception (enter/escape/backspace) |
| norrust_love/main.lua | Modified | save_renaming/save_rename_text state, love.textinput callback, ctx pass-through |

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| save_rename_skip flag to eat 'r' from textinput | love.textinput fires after keypressed; the 'r' that triggers rename would otherwise appear in the text |
| Byte-based backspace (not UTF-8 aware) | LuaJIT lacks utf8 library; save names are ASCII-practical |
| Row height 26→32px in save list | Accommodate secondary metadata line under display_name |

## Deviations from Plan

- Added save_rename_skip flag (not in plan) to prevent the triggering 'r' key from appearing in rename text

## Next Phase Readiness

**Ready:**
- Save system complete (list, load, delete, rename) for Phase 92 veteran deployment
- Backlog items added: exit button on game board with save prompt, exit button on main menu

**Blockers:** None

---
*Phase: 91-save-naming, Plan: 01*
*Completed: 2026-03-08*
