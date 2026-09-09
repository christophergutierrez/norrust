-- Read-only recorded-game playback controller and toolbar.
local M = {}

M.SPEEDS = {Slow = 2.0, Medium = 1.0, Fast = 0.5}

-- Toolbar geometry shared between drawing (draw_toolbar) and hit testing
-- (input.lua). Keep in sync: the layout function is the single source of
-- truth for both.
local SIDEBAR_W = 200
local MARGIN = 10
local GAP = 8
local GROUP_GAP = 20
local BTN_PAD = 10
local BTN_H = 20
local SPEED_W = 26
local FALLBACK_CHAR_W = 7

local IDENTITY_Y = 4
local PLAYERS_Y = 17
local PROGRESS_Y = 26
local CONTROLS_ROW1_Y = 40

function M.new(bundle)
    assert(bundle and bundle.frames and #bundle.frames > 0, "replay has no frames")
    return {bundle = bundle, index = 1, playing = false, speed = "Slow", elapsed = 0}
end

function M.state(replay) return replay.bundle.frames[replay.index].state end
function M.at_start(replay) return replay.index == 1 end
function M.at_end(replay) return replay.index == #replay.bundle.frames end
function M.step(replay, delta)
    replay.playing = false
    replay.elapsed = 0
    replay.index = math.max(1, math.min(#replay.bundle.frames, replay.index + delta))
end
function M.restart(replay) replay.index, replay.playing, replay.elapsed = 1, false, 0 end
function M.toggle(replay)
    if M.at_end(replay) then replay.playing = false else replay.playing = not replay.playing end
end
function M.set_speed(replay, speed)
    assert(M.SPEEDS[speed], "unknown replay speed")
    local fraction = replay.elapsed / M.SPEEDS[replay.speed]
    replay.speed = speed
    replay.elapsed = fraction * M.SPEEDS[speed]
end
function M.update(replay, dt)
    if not replay.playing then return false end
    replay.elapsed = replay.elapsed + math.max(0, dt)
    if replay.elapsed < M.SPEEDS[replay.speed] then return false end
    replay.elapsed = 0
    if M.at_end(replay) then replay.playing = false; return false end
    replay.index = replay.index + 1
    if M.at_end(replay) then replay.playing = false end
    return true
end

function M.progress(replay)
    local frame = replay.bundle.frames[replay.index]
    local total = #replay.bundle.frames - 1
    local done = replay.index - 1
    return done, total, frame
end

function M.player_labels(replay)
    local players = replay.bundle.players or {}
    local metadata = replay.bundle.metadata or {}
    local function label(side, faction_key)
        local player = players[side + 1] or {}
        local model = player.model_reported or player.model_requested
        local name = player.display_name or model
        if not name and player.player_kind == "model" then name = "LLM (model unavailable)" end
        name = name or player.backend or "Unknown"
        if player.player_kind == "model" and model and model ~= name then
            name = string.format("%s [%s]", name, model)
        end
        local faction = metadata[faction_key] or "unknown faction"
        return string.format("Side %d: %s (%s)", side, name, faction)
    end
    return label(0, "faction0"), label(1, "faction1")
end

-- ── Turn navigation ──────────────────────────────────────────────────────
-- "Turn" is the existing displayed state.turn round number — not a side
-- turn, and not a fixed count of frames. Anchors are the first *available*
-- frame carrying a given turn number; they are not proof of a true turn
-- start (a gap can hide the real boundary).

--- The turn number of frame `index`, or nil if it isn't a usable number.
function M.turn_of(replay, index)
    local frame = replay.bundle.frames[index]
    local turn = frame and frame.state and frame.state.turn
    if type(turn) == "number" then return turn end
    return nil
end

--- True when every frame carries a usable, non-decreasing turn number.
-- Cached on the replay table: frames never change after construction.
function M.turns_available(replay)
    if replay._turns_ok ~= nil then return replay._turns_ok end
    local ok = true
    local prev
    for i = 1, #replay.bundle.frames do
        local turn = M.turn_of(replay, i)
        if turn == nil then ok = false; break end
        if prev ~= nil and turn < prev then ok = false; break end
        prev = turn
    end
    replay._turns_ok = ok
    return ok
end

--- First frame of the previous recorded turn (or frame 1 if none earlier).
local function first_turn_before(replay, cur)
    local turn = M.turn_of(replay, cur)
    local i = cur
    while i > 1 and M.turn_of(replay, i - 1) == turn do i = i - 1 end
    if i == 1 then return 1 end
    local prev_turn = M.turn_of(replay, i - 1)
    local anchor = i - 1
    while anchor > 1 and M.turn_of(replay, anchor - 1) == prev_turn do anchor = anchor - 1 end
    return anchor
end

--- First frame of the next recorded turn (or the last frame if none later).
local function first_turn_after(replay, cur)
    local turn = M.turn_of(replay, cur)
    local total = #replay.bundle.frames
    for i = cur + 1, total do
        if M.turn_of(replay, i) > turn then return i end
    end
    return total
end

--- Target frame index for a turn step (direction > 0 forward, < 0 back), or
-- nil when turn navigation is unavailable.
function M.turn_target(replay, direction)
    if not M.turns_available(replay) then return nil end
    if direction > 0 then return first_turn_after(replay, replay.index) end
    return first_turn_before(replay, replay.index)
end

--- Move to the first frame of the adjacent recorded turn. A no-op (no pause,
-- no elapsed reset) when turn navigation is unavailable or already at the
-- target — mirroring a disabled button's "do nothing" contract.
function M.step_turn(replay, direction)
    local target = M.turn_target(replay, direction)
    if not target or target == replay.index then return end
    replay.playing = false
    replay.elapsed = 0
    replay.index = target
end

-- ── Toolbar layout ───────────────────────────────────────────────────────
-- The single source of truth for both drawing and hit testing. `ctx` needs
-- only `vp_w` and `fonts` (a real Love2D font table or, in headless tests, a
-- table of fakes exposing :getWidth — or nothing at all, which falls back to
-- a fixed-width estimate).

local function text_width(ctx, size, text)
    local font = ctx.fonts and ctx.fonts[size]
    if font and font.getWidth then return font:getWidth(text) end
    return #text * FALLBACK_CHAR_W
end

local function ellipsize(ctx, size, text, max_w)
    if text_width(ctx, size, text) <= max_w then return text end
    local out = text
    while #out > 0 and text_width(ctx, size, out .. "...") > max_w do
        out = out:sub(1, -2)
    end
    return out .. "..."
end

--- Compute toolbar height and all button rectangles for the current state.
-- Buttons are disabled only when their target equals the current frame, or
-- their required turn information is unavailable.
function M.layout(replay, ctx)
    local vp_w = ctx.vp_w or 1024
    local usable_w = vp_w - SIDEBAR_W

    local function btn_w(text) return text_width(ctx, 11, text) + BTN_PAD * 2 end

    local back_turn_target = M.turn_target(replay, -1)
    local forward_turn_target = M.turn_target(replay, 1)
    local play_w = math.max(btn_w("Play"), btn_w("Pause"))

    local nav = {
        {key = "back_turn", label = "Back Turn", w = btn_w("Back Turn"),
         disabled = back_turn_target == nil or back_turn_target == replay.index},
        {key = "back_frame", label = "Back Frame", w = btn_w("Back Frame"), disabled = M.at_start(replay)},
        {key = "play", label = replay.playing and "Pause" or "Play", w = play_w, disabled = false},
        {key = "forward_frame", label = "Forward Frame", w = btn_w("Forward Frame"), disabled = M.at_end(replay)},
        {key = "forward_turn", label = "Forward Turn", w = btn_w("Forward Turn"),
         disabled = forward_turn_target == nil or forward_turn_target == replay.index},
    }
    local secondary = {
        {key = "restart", label = "Restart", w = btn_w("Restart"), disabled = false},
        {key = "back_to_games", label = "Games", w = btn_w("Games"), disabled = false},
        {key = "speed_Slow", label = "S", w = SPEED_W, disabled = false},
        {key = "speed_Medium", label = "M", w = SPEED_W, disabled = false},
        {key = "speed_Fast", label = "F", w = SPEED_W, disabled = false},
    }

    local function row_width(row)
        local w = 0
        for i, b in ipairs(row) do
            w = w + b.w
            if i < #row then w = w + GAP end
        end
        return w
    end

    local single_row = (MARGIN * 2 + row_width(nav) + GROUP_GAP + row_width(secondary)) <= usable_w
    local controls_row2_y = CONTROLS_ROW1_Y + BTN_H + 6

    local buttons = {}
    local x = MARGIN
    for _, b in ipairs(nav) do
        buttons[b.key] = {x = x, y = CONTROLS_ROW1_Y, w = b.w, h = BTN_H, label = b.label, disabled = b.disabled}
        x = x + b.w + GAP
    end
    local two_rows = not single_row
    if single_row then
        x = x + (GROUP_GAP - GAP)
        for _, b in ipairs(secondary) do
            buttons[b.key] = {x = x, y = CONTROLS_ROW1_Y, w = b.w, h = BTN_H, label = b.label, disabled = b.disabled}
            x = x + b.w + GAP
        end
    else
        x = MARGIN
        for _, b in ipairs(secondary) do
            buttons[b.key] = {x = x, y = controls_row2_y, w = b.w, h = BTN_H, label = b.label, disabled = b.disabled}
            x = x + b.w + GAP
        end
    end

    local last_row_y = two_rows and controls_row2_y or CONTROLS_ROW1_Y
    return {
        height = last_row_y + BTN_H + 6,
        usable_w = usable_w,
        buttons = buttons,
        single_row = single_row,
        identity_y = IDENTITY_Y, players_y = PLAYERS_Y, progress_y = PROGRESS_Y,
    }
end

--- Return the button key at (x, y) in the given layout, or nil.
function M.button_at(layout, x, y)
    for key, b in pairs(layout.buttons) do
        if x >= b.x and x <= b.x + b.w and y >= b.y and y <= b.y + b.h then return key end
    end
    return nil
end

function M.draw_toolbar(replay, ctx)
    local vp_w = ctx.vp_w
    local layout = M.layout(replay, ctx)
    love.graphics.setColor(0.04, 0.04, 0.06, 0.92)
    love.graphics.rectangle("fill", 0, 0, vp_w, layout.height)

    local text_max_w = layout.usable_w - MARGIN
    love.graphics.setFont(ctx.fonts[14])
    love.graphics.setColor(1, 0.85, 0.3, 1)
    love.graphics.print(ellipsize(ctx, 14, "REPLAY  " .. tostring(replay.bundle.game_id), text_max_w),
        10, layout.identity_y)

    local p0, p1 = M.player_labels(replay)
    love.graphics.setFont(ctx.fonts[11])
    love.graphics.print(ellipsize(ctx, 11, p0 .. "   |   " .. p1, text_max_w), 10, layout.players_y)

    local done, total, frame = M.progress(replay)
    local remaining = total - done
    local turn_part
    if M.turns_available(replay) then
        turn_part = "Turn " .. tostring(frame.state.turn or "?")
    else
        turn_part = "Turn navigation unavailable"
    end
    local progress_text = string.format("Frame %d/%d  ·  %s  ·  %d frames remaining  ·  %s", done, total,
        turn_part, remaining, replay.playing and "Playing" or "Paused")
    if replay.bundle.metadata and replay.bundle.metadata.status ~= "complete" then
        progress_text = progress_text .. "  ·  Recording incomplete"
    elseif M.coverage_incomplete(replay) then
        -- The engine result is known, but the recorded timeline has a
        -- reported gap (e.g. a checkpoint-only revision, or an unresolved
        -- turn endpoint). Retain the result; disclose the gap.
        progress_text = progress_text .. "  ·  Replay coverage incomplete"
    end
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.print(ellipsize(ctx, 11, progress_text, text_max_w), 10, layout.progress_y)

    love.graphics.setFont(ctx.fonts[11])
    for key, b in pairs(layout.buttons) do
        love.graphics.setColor(b.disabled and 0.08 or 0.18, b.disabled and 0.09 or 0.2, b.disabled and 0.1 or 0.25, 1)
        love.graphics.rectangle("fill", b.x, b.y, b.w, b.h, 3, 3)
        if key:find("^speed_") and replay.speed == key:sub(7) then
            love.graphics.setColor(0.75, 0.55, 0.15, 1)
            love.graphics.rectangle("fill", b.x, b.y, b.w, b.h, 3, 3)
        end
        love.graphics.setColor(1, 1, 1, 1)
        love.graphics.printf(b.label, b.x, b.y + 4, b.w, "center")
    end
end

-- True only when the timeline itself reports a gap or a missing endpoint,
-- never a guessed completeness ratio.
function M.coverage_incomplete(replay)
    local coverage = replay.bundle.coverage
    if type(coverage) ~= "table" then return false end
    if coverage.opening_present == false or coverage.terminal_present == false then return true end
    return type(coverage.gaps) == "table" and #coverage.gaps > 0
end

return M
