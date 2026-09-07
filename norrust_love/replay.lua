-- Read-only recorded-game playback controller and toolbar.
local M = {}

M.SPEEDS = {Slow = 2.0, Medium = 1.0, Fast = 0.5}

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
    if replay.elapsed < M.SPEEDS[replay.speed] / 2 then return false end
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
        local name = player.display_name or player.model_requested or player.backend or "Unknown"
        local model = player.model_requested
        if player.player_kind == "model" and model and model ~= name then
            name = string.format("%s [%s]", name, model)
        end
        local faction = metadata[faction_key] or "unknown faction"
        return string.format("Side %d: %s (%s)", side, name, faction)
    end
    return label(0, "faction0"), label(1, "faction1")
end

function M.draw_toolbar(replay, ctx)
    local vp_w = ctx.vp_w
    love.graphics.setColor(0.04, 0.04, 0.06, 0.92)
    love.graphics.rectangle("fill", 0, 0, vp_w, 48)
    love.graphics.setFont(ctx.fonts[14])
    love.graphics.setColor(1, 0.85, 0.3, 1)
    local p0, p1 = M.player_labels(replay)
    love.graphics.print("REPLAY  " .. tostring(replay.bundle.game_id), 10, 4)
    love.graphics.setFont(ctx.fonts[11])
    love.graphics.print(p0 .. "   |   " .. p1, 10, 17)
    local done, total, frame = M.progress(replay)
    love.graphics.setFont(ctx.fonts[11])
    love.graphics.setColor(1, 1, 1, 1)
    local remaining = math.max(0, (total - done) / 2)
    love.graphics.print(string.format("Frame %d/%d  ·  Turn %s  ·  %.1f turns remaining  ·  %s", done, total,
        tostring(frame.state.turn or "?"), remaining, replay.playing and "Playing" or "Paused"), 10, 26)
    local buttons = {
        {key="back", label="◀ Back 1", x=vp_w-390, w=72},
        {key="play", label=replay.playing and "Pause" or "Play", x=vp_w-312, w=56},
        {key="forward", label="Forward 1 ▶", x=vp_w-250, w=88},
        {key="restart", label="Restart", x=vp_w-156, w=62},
    }
    ctx.replay_buttons = {}
    love.graphics.setFont(ctx.fonts[11])
    for _, b in ipairs(buttons) do
        ctx.replay_buttons[b.key] = {x=b.x, y=4, w=b.w, h=20}
        local disabled = (b.key == "back" and M.at_start(replay)) or (b.key == "forward" and M.at_end(replay))
        love.graphics.setColor(disabled and 0.08 or 0.18, disabled and 0.09 or 0.2, disabled and 0.1 or 0.25, 1)
        love.graphics.rectangle("fill", b.x, 4, b.w, 20, 3, 3)
        love.graphics.setColor(1, 1, 1, 1)
        love.graphics.printf(b.label, b.x, 8, b.w, "center")
    end
    local x = vp_w - 88
    for _, speed in ipairs({"Slow", "Medium", "Fast"}) do
        local w = 28
        ctx.replay_buttons["speed_" .. speed] = {x=x, y=27, w=w, h=17}
        if replay.speed == speed then love.graphics.setColor(0.75, 0.55, 0.15, 1)
        else love.graphics.setColor(0.16, 0.17, 0.2, 1) end
        love.graphics.rectangle("fill", x, 27, w, 17)
        love.graphics.setColor(1, 1, 1, 1)
        love.graphics.printf(speed:sub(1, 1), x, 29, w, "center")
        x = x + 30
    end
    if replay.bundle.metadata and replay.bundle.metadata.status ~= "complete" then
        love.graphics.setColor(1, 0.75, 0.3, 1)
        love.graphics.print("Recording incomplete", vp_w - 220, 26)
    end
end

return M
