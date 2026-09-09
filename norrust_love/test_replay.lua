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
-- Exercise the actual controls with irregular snapshots: the old +2 binding
-- jumped straight from frame 0 / turn 0 to frame 2 / turn 3.
local input = require("input")
local sparse = replay.new({frames = {
    {state = {turn = 0}}, {state = {turn = 1}}, {state = {turn = 3}},
}})
local shared = {replay = sparse, buttons = {}}
input.init({vars = {game_mode = 4}, shared = shared, mods = {},
    MODES = {PLAYING = 4, RECORDED_GAMES = 7}, replay_mod = replay,
    screen_to_game = function(x, y) return x / 2, y / 2 end})
local drawn = {}
love = {graphics = setmetatable({
    print = function(text) drawn[#drawn + 1] = text end,
}, {__index = function() return function() end end})}
local ctx = {vp_w = 1024, fonts = {}}
replay.draw_toolbar(sparse, ctx)
shared.buttons.replay_buttons = ctx.replay_buttons
assert(table.concat(drawn, "\n"):find("Frame 0/2  ·  Turn 0  ·  2 frames remaining", 1, true))
local function click(key)
    local rect = ctx.replay_buttons[key]
    input.mousepressed((rect.x + 4) * 2, (rect.y + 4) * 2, 1)
end
click("forward")
assert(sparse.index == 2 and replay.state(sparse).turn == 1)
click("forward")
assert(sparse.index == 3 and replay.state(sparse).turn == 3)
click("forward"); assert(replay.at_end(sparse))
click("back"); assert(sparse.index == 2)
click("back"); click("back"); assert(replay.at_start(sparse))
for _, keys in ipairs({{"right", "left"}, {"d", "a"}}) do
    replay.toggle(sparse)
    input.keypressed(keys[1]); assert(sparse.index == 2 and not sparse.playing)
    input.keypressed(keys[2]); assert(replay.at_start(sparse))
end
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
os.remove(db)

print("replay tests passed")
