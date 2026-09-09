package.path = "norrust_love/?.lua;" .. package.path
local replay = require("replay")
local norrust = require("norrust")

local frames = {}
for i = 1, 7 do frames[i] = {state = {turn = math.ceil(i / 2)}} end
local r = replay.new({game_id = "fixture", frames = frames})
local labeled = replay.new({players = {
    {player_kind = "model", display_name = "Claude", model_requested = "claude"},
    {player_kind = "algorithm", display_name = "Greedy"}},
    metadata = {faction0 = "undead", faction1 = "undead"}, frames = frames})
local p0, p1 = replay.player_labels(labeled)
assert(p0 == "Side 0: Claude [claude] (undead)" and p1 == "Side 1: Greedy (undead)")
local unknown = replay.new({players = {{player_kind = "model", backend = "model-command"}, {}},
    metadata = {faction0 = "undead", faction1 = "undead"}, frames = frames})
local unknown0 = replay.player_labels(unknown)
assert(unknown0 == "Side 0: LLM (model unavailable) (undead)")
assert(replay.at_start(r) and not replay.at_end(r))
replay.step(r, 2); assert(r.index == 3)
replay.step(r, 2); assert(r.index == 5)
replay.step(r, -6); assert(r.index == 1)
replay.step(r, -2); assert(r.index == 1)
replay.step(r, 20); assert(r.index == 7 and replay.at_end(r))
replay.restart(r); assert(r.index == 1 and not r.playing)
replay.toggle(r); assert(r.playing)
assert(not replay.update(r, 1.99)); assert(replay.update(r, 0.02)); assert(r.index == 2)
replay.toggle(r); assert(not r.playing)
replay.set_speed(r, "Fast"); replay.toggle(r)
assert(not replay.update(r, 0.49)); assert(replay.update(r, 0.02)); assert(r.index == 3)
replay.restart(r); replay.set_speed(r, "Slow"); replay.toggle(r); assert(not replay.update(r, 0.4))
replay.set_speed(r, "Fast"); assert(not replay.update(r, 0.39)); assert(replay.update(r, 0.02)); assert(r.index == 2)
replay.update(r, 10); assert(r.index == 3) -- a stall advances one frame only
replay.step(r, 20); replay.toggle(r); replay.update(r, 1); assert(r.index == 7 and not r.playing)

-- ── Turn navigation: the plan's worked fixture table ────────────────────
-- Frame  0 1 2 3 4 5 6
-- Turn   1 1 1 2 2 3 3   (Lua index = frame + 1)
local function turn_frames(turns)
    local f = {}
    for i, t in ipairs(turns) do f[i] = {state = {turn = t}} end
    return f
end
local fixture = replay.new({frames = turn_frames({1, 1, 1, 2, 2, 3, 3})})
assert(replay.turns_available(fixture))

local function goto_frame(rep, lua_index) rep.index = lua_index end

-- From frame 1 (lua index 2): Forward Frame -> 2, Forward Turn -> 3, Back Turn -> 0.
goto_frame(fixture, 2)
assert(replay.turn_target(fixture, 1) == 4, "forward turn from frame1 must land on frame3")
assert(replay.turn_target(fixture, -1) == 1, "back turn from frame1 must land on frame0")
replay.step(fixture, 1); assert(fixture.index == 3) -- Forward Frame -> frame2

-- From frame 4 (lua index 5): Back Frame -> 3, Back Turn -> 0, Forward Turn -> 5.
goto_frame(fixture, 5)
assert(replay.turn_target(fixture, -1) == 1, "back turn from frame4 must land on frame0")
assert(replay.turn_target(fixture, 1) == 6, "forward turn from frame4 must land on frame5")
replay.step(fixture, -1); assert(fixture.index == 4) -- Back Frame -> frame3

-- From frame 5 (lua index 6): Forward Turn -> 6 (terminal edge, no turn 4 exists).
goto_frame(fixture, 6)
assert(replay.turn_target(fixture, 1) == 7, "forward turn from frame5 must land on the last frame")

-- From frame 6 (lua index 7, the last frame): Back Turn -> 3.
goto_frame(fixture, 7)
assert(replay.turn_target(fixture, -1) == 4, "back turn from frame6 must land on frame3")
-- Already at the last frame: Forward Turn has nowhere to go (target == current).
assert(replay.turn_target(fixture, 1) == 7)

-- step_turn actually moves, pauses playback, and clears the elapsed timer;
-- it is a no-op when the target equals the current frame.
goto_frame(fixture, 2); fixture.playing = true; fixture.elapsed = 1.5
replay.step_turn(fixture, 1)
assert(fixture.index == 4 and not fixture.playing and fixture.elapsed == 0)
fixture.playing = true; fixture.elapsed = 1.5
replay.step_turn(fixture, -1) -- frame3 -> frame0: no earlier turn
assert(fixture.index == 1 and not fixture.playing and fixture.elapsed == 0)
fixture.playing = true; fixture.elapsed = 1.5
replay.step_turn(fixture, -1) -- already at frame0: no-op, no pause/clear
assert(fixture.index == 1 and fixture.playing and fixture.elapsed == 1.5)

-- Single-frame recording: both turn directions are no-ops at the only frame.
local one_frame = replay.new({frames = turn_frames({5})})
assert(replay.turn_target(one_frame, 1) == 1 and replay.turn_target(one_frame, -1) == 1)
assert(replay.at_start(one_frame) and replay.at_end(one_frame))

-- Single turn, multiple frames: Forward Turn goes to the last frame (no
-- later turn exists); Back Turn goes to the first (no earlier turn exists).
local single_turn = replay.new({frames = turn_frames({4, 4, 4, 4})})
goto_frame(single_turn, 2)
assert(replay.turn_target(single_turn, 1) == 4, "no later turn: forward turn reaches the last frame")
assert(replay.turn_target(single_turn, -1) == 1, "no earlier turn: back turn reaches the first frame")
goto_frame(single_turn, 1)
assert(replay.turn_target(single_turn, -1) == 1) -- already there: no-op target
goto_frame(single_turn, 4)
assert(replay.turn_target(single_turn, 1) == 4) -- already there: no-op target

-- Skipped turn (3 -> 5): the anchor is the first available turn-5 frame;
-- turn 4 is never fabricated.
local skipped = replay.new({frames = turn_frames({3, 3, 5, 5})})
goto_frame(skipped, 1)
assert(replay.turn_target(skipped, 1) == 3, "forward turn must land on the first available turn 5 frame")
goto_frame(skipped, 4)
assert(replay.turn_target(skipped, -1) == 1, "back turn from turn 5 must land on the first turn 3 frame")

-- Missing turn number on some frame: turn navigation is disabled entirely,
-- even though frame stepping is unaffected.
local missing = replay.new({frames = {{state = {turn = 1}}, {state = {}}, {state = {turn = 2}}}})
assert(not replay.turns_available(missing))
assert(replay.turn_target(missing, 1) == nil and replay.turn_target(missing, -1) == nil)
missing.playing, missing.elapsed = true, 1.0
replay.step_turn(missing, 1)
assert(missing.index == 1 and missing.playing and missing.elapsed == 1.0, "unavailable turn nav must be a true no-op")

-- Decreasing turn numbers without a resolved timeline: also disabled.
local decreasing = replay.new({frames = turn_frames({1, 2, 1})})
assert(not replay.turns_available(decreasing))

-- Mid-turn victory: the final frame shares its turn with the frame before
-- it (the game ended partway through the turn), not a fresh anchor.
local mid_turn_victory = replay.new({frames = turn_frames({1, 2, 2, 2})})
goto_frame(mid_turn_victory, 3)
assert(replay.turn_target(mid_turn_victory, 1) == 4, "forward turn reaches the winning partial frame")
goto_frame(mid_turn_victory, 4)
assert(replay.turn_target(mid_turn_victory, 1) == 4) -- already at the end: no-op target
assert(replay.turn_target(mid_turn_victory, -1) == 1)

-- ── Toolbar layout: single source of truth for drawing and hit testing ──
for _, vp_w in ipairs({768, 1024}) do
    local layout = replay.layout(fixture, {vp_w = vp_w})
    local rects = {}
    for key, b in pairs(layout.buttons) do
        assert(b.w > 0 and b.h > 0, key .. " must have positive size")
        assert(b.x >= 0 and b.x + b.w <= vp_w - 200, key .. " must fit the usable width at vp_w=" .. vp_w)
        rects[#rects + 1] = {key = key, x = b.x, y = b.y, w = b.w, h = b.h}
    end
    for i = 1, #rects do
        for j = i + 1, #rects do
            local a, c = rects[i], rects[j]
            local overlap = a.x < c.x + c.w and c.x < a.x + a.w and a.y < c.y + c.h and c.y < a.y + a.h
            assert(not overlap, "buttons " .. a.key .. " and " .. c.key .. " overlap at vp_w=" .. vp_w)
        end
    end
    -- Progress/identity rows sit strictly above the first control row.
    for _, b in ipairs(rects) do
        assert(b.y >= layout.progress_y + 8, "controls must not sit above the progress row")
    end
    assert(layout.height > layout.progress_y, "toolbar height must enclose the progress row")
end

-- A fake font with real (if approximate) per-character metrics exercises the
-- "actual font and label widths" sizing path, not just the headless fallback.
local fake_font = {getWidth = function(_, text) return #text * 6 end}
local font_layout = replay.layout(fixture, {vp_w = 1024, fonts = {[11] = fake_font, [14] = fake_font}})
assert(font_layout.buttons.back_turn.w > 0)

print("replay turn-navigation and layout tests passed")

-- ── Exercise the actual controls through input.lua ──────────────────────
-- Mouse and keyboard must select identical frames, disabled controls must do
-- nothing, and the toolbar must consume every click in its band (including
-- empty space) so it can never inspect or select an underlying unit.
local input = require("input")
local sparse = replay.new({frames = {
    {state = {turn = 0}}, {state = {turn = 1}}, {state = {turn = 3}},
}})
local shared = {replay = sparse, buttons = {}}
input.init({vars = {game_mode = 4}, shared = shared, mods = {hex = {from_pixel = function() return -1, -1 end}},
    MODES = {PLAYING = 4, RECORDED_GAMES = 7}, replay_mod = replay,
    int = function(v) return math.floor(v) end,
    fonts = {}, camera = {origin_x = 0, origin_y = 0, zoom = 1, offset_x = 0, offset_y = 0},
    get_viewport = function() return 1024, 576 end,
    screen_to_game = function(x, y) return x / 2, y / 2 end})
local drawn = {}
love = {graphics = setmetatable({
    print = function(text) drawn[#drawn + 1] = text end,
}, {__index = function() return function() end end})}
local ctx = {vp_w = 1024, fonts = {}}
replay.draw_toolbar(sparse, ctx)
local layout = replay.layout(sparse, ctx)
assert(table.concat(drawn, "\n"):find("Frame 0/2", 1, true))

local function click(key)
    local rect = layout.buttons[key]
    input.mousepressed((rect.x + rect.w / 2) * 2, (rect.y + rect.h / 2) * 2, 1)
    layout = replay.layout(sparse, ctx)
end

-- back_turn and back_frame are both disabled at frame 0: clicking does nothing.
assert(layout.buttons.back_turn.disabled and layout.buttons.back_frame.disabled)
click("back_turn"); assert(sparse.index == 1)
click("back_frame"); assert(sparse.index == 1)

click("forward_frame")
assert(sparse.index == 2 and replay.state(sparse).turn == 1)
click("forward_frame")
assert(sparse.index == 3 and replay.state(sparse).turn == 3)
click("forward_frame"); assert(replay.at_end(sparse)) -- clamped, forward_frame now disabled
assert(layout.buttons.forward_frame.disabled)
click("back_frame"); assert(sparse.index == 2)
click("back_turn"); assert(sparse.index == 1) -- first turn-0 anchor
assert(replay.at_start(sparse))

-- Turn buttons jump straight to the anchor frame (not one frame at a time).
click("forward_turn"); assert(sparse.index == 2 and replay.state(sparse).turn == 1)
click("forward_turn"); assert(sparse.index == 3 and replay.state(sparse).turn == 3)
click("back_turn"); assert(sparse.index == 2 and replay.state(sparse).turn == 1) -- previous turn's anchor

-- Keyboard: Left/A and Right/D step frames; Page Up/Down step turns; both
-- input methods must land on identical frames.
replay.restart(sparse)
for _, keys in ipairs({{"right", "left"}, {"d", "a"}}) do
    replay.toggle(sparse)
    input.keypressed(keys[1]); assert(sparse.index == 2 and not sparse.playing)
    input.keypressed(keys[2]); assert(replay.at_start(sparse))
end
input.keypressed("pagedown"); assert(sparse.index == 2 and replay.state(sparse).turn == 1)
input.keypressed("pagedown"); assert(sparse.index == 3 and replay.state(sparse).turn == 3)
input.keypressed("pageup"); assert(sparse.index == 2 and replay.state(sparse).turn == 1)

-- All manual navigation pauses playback and clears the elapsed timer, even
-- mid-Play.
replay.toggle(sparse); sparse.elapsed = 1.0
input.keypressed("d")
assert(not sparse.playing and sparse.elapsed == 0)
replay.restart(sparse); replay.toggle(sparse); sparse.elapsed = 1.0
layout = replay.layout(sparse, ctx)
click("forward_turn")
assert(not sparse.playing and sparse.elapsed == 0)
replay.restart(sparse)

-- Toolbar background clicks (inside its band, not on any button) must be
-- consumed and never reach unit inspection; a click below the toolbar must
-- still inspect the board normally.
local board_replay = replay.new({frames = {{state = {units = {{id = 42, col = 0, row = 0}}}}}})
shared.replay = board_replay
shared.sel = {unit_id = -1, inspect_id = -1}
input.init({vars = {game_mode = 4}, shared = shared, sel = shared.sel,
    mods = {hex = {from_pixel = function() return 0, 0 end}},
    MODES = {PLAYING = 4, RECORDED_GAMES = 7}, replay_mod = replay,
    int = function(v) return math.floor(v) end,
    fonts = {}, camera = {origin_x = 0, origin_y = 0, zoom = 1, offset_x = 0, offset_y = 0},
    get_viewport = function() return 1024, 576 end,
    screen_to_game = function(x, y) return x / 2, y / 2 end})
local board_layout = replay.layout(board_replay, ctx)
-- A point inside the toolbar band but not on any button.
local empty_x, empty_y = 5, board_layout.height - 1
local hit_something = false
for _, b in pairs(board_layout.buttons) do
    if empty_x >= b.x and empty_x <= b.x + b.w and empty_y >= b.y and empty_y <= b.y + b.h then hit_something = true end
end
assert(not hit_something, "test point must actually be empty toolbar space")
input.mousepressed(empty_x * 2, empty_y * 2, 1)
assert(shared.sel.inspect_id == -1, "empty toolbar space must not select a unit")
-- A click below the toolbar still inspects the board normally.
input.mousepressed(5 * 2, (board_layout.height + 20) * 2, 1)
assert(shared.sel.inspect_id == 42, "a click below the toolbar must still inspect the board")

love = nil

-- Coverage gaps are disclosed even when the engine result is known.
local complete_bundle = {game_id = "c", metadata = {status = "complete"},
    coverage = {opening_present = true, terminal_present = true, gaps = {}}, frames = frames}
assert(not replay.coverage_incomplete(replay.new(complete_bundle)))
local gapped_bundle = {game_id = "g", metadata = {status = "complete"},
    coverage = {opening_present = true, terminal_present = false, gaps = {"terminal_state_unresolved"}},
    frames = frames}
local gapped = replay.new(gapped_bundle)
assert(replay.coverage_incomplete(gapped))
local gap_drawn = {}
love = {graphics = setmetatable({
    print = function(text) gap_drawn[#gap_drawn + 1] = text end,
}, {__index = function() return function() end end})}
replay.draw_toolbar(gapped, {vp_w = 1024, fonts = {}})
assert(table.concat(gap_drawn, "\n"):find("Replay coverage incomplete", 1, true))
love = nil

-- Turn navigation unavailable is disclosed the same way.
local unresolved = replay.new({frames = {{state = {turn = 1}}, {state = {}}}})
local unresolved_drawn = {}
love = {graphics = setmetatable({
    print = function(text) unresolved_drawn[#unresolved_drawn + 1] = text end,
}, {__index = function() return function() end end})}
replay.draw_toolbar(unresolved, {vp_w = 1024, fonts = {}})
local unresolved_layout = replay.layout(unresolved, {vp_w = 1024, fonts = {}})
assert(table.concat(unresolved_drawn, "\n"):find("Turn navigation unavailable", 1, true))
assert(unresolved_layout.buttons.back_turn.disabled and unresolved_layout.buttons.forward_turn.disabled)
love = nil

-- CLI import/export of the tracked S1 fixture, traversed to the terminal
-- frame: proves the exported bundle is distinct/ordered end to end, not
-- just that startup succeeds (the separate --smoke-replay check only
-- covers the latter).
local db = os.tmpname()
os.remove(db)
local bundle_path = os.tmpname()
local import_pipe = io.popen(
    "python3 -m tools.game_history import --db " .. db .. " tools/fixtures/s1_sample_game 2>&1")
local game_id = norrust.json_decode(import_pipe:read("*a"))
import_pipe:close()
assert(type(game_id) == "string" and #game_id > 0, "fixture import must return a game id")
local export_pipe = io.popen("python3 -m tools.replay_game " .. game_id ..
    " --db " .. db .. " --export " .. bundle_path .. " 2>&1")
local export_output = export_pipe:read("*a")
export_pipe:close()
local file = io.open(bundle_path, "rb")
assert(file, "export must produce a bundle file: " .. tostring(export_output))
local bundle = norrust.json_decode(file:read("*a"))
file:close()
os.remove(bundle_path)
local fixture_replay = replay.new(bundle)
local notes, revisions = {}, {}
while true do
    local frame = replay.state(fixture_replay)
    notes[#notes + 1] = frame.note
    revisions[#revisions + 1] = frame.state_revision
    if replay.at_end(fixture_replay) then break end
    replay.step(fixture_replay, 1)
end
assert(table.concat(notes, ",") ==
    "opening,recruitment_partial,model_end,greedy_mid_turn,greedy_reply,winning_partial",
    table.concat(notes, ","))
for i = 1, #revisions do assert(revisions[i] == i - 1, "frames must be revision-ordered") end
assert(bundle.coverage.opening_present and bundle.coverage.terminal_present)

-- Turn stepping over the real exported bundle must stay in bounds in both
-- directions. If this fixture's turn numbers aren't fully resolved, turn
-- navigation is disabled rather than guessing, and frame stepping alone
-- proves the bundle traverses cleanly (already checked above).
replay.restart(fixture_replay)
if replay.turns_available(fixture_replay) then
    local hops = 0
    while not replay.at_end(fixture_replay) and hops < #bundle.frames do
        replay.step_turn(fixture_replay, 1)
        hops = hops + 1
    end
    assert(replay.at_end(fixture_replay), "forward turn stepping must reach the terminal frame")
    hops = 0
    while not replay.at_start(fixture_replay) and hops < #bundle.frames do
        replay.step_turn(fixture_replay, -1)
        hops = hops + 1
    end
    assert(replay.at_start(fixture_replay), "back turn stepping must reach the opening frame")
end
os.remove(db)

print("replay tests passed")
