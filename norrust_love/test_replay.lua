package.path = "norrust_love/?.lua;" .. package.path
local replay = require("replay")

local frames = {}
for i = 1, 7 do frames[i] = {state = {turn = math.ceil(i / 2)}} end
local r = replay.new({game_id = "fixture", frames = frames})
local labeled = replay.new({players = {
    {player_kind = "model", display_name = "Claude", model_requested = "claude"},
    {player_kind = "algorithm", display_name = "Greedy"}},
    metadata = {faction0 = "undead", faction1 = "undead"}, frames = frames})
local p0, p1 = replay.player_labels(labeled)
assert(p0 == "Side 0: Claude [claude] (undead)" and p1 == "Side 1: Greedy (undead)")
assert(replay.at_start(r) and not replay.at_end(r))
replay.step(r, 2); assert(r.index == 3)
replay.step(r, 2); assert(r.index == 5)
replay.step(r, -6); assert(r.index == 1)
replay.step(r, -2); assert(r.index == 1)
replay.step(r, 20); assert(r.index == 7 and replay.at_end(r))
replay.restart(r); assert(r.index == 1 and not r.playing)
replay.toggle(r); assert(r.playing)
assert(not replay.update(r, 0.99)); assert(replay.update(r, 0.02)); assert(r.index == 2)
replay.toggle(r); assert(not r.playing)
replay.set_speed(r, "Fast"); replay.toggle(r)
assert(not replay.update(r, 0.24)); assert(replay.update(r, 0.02)); assert(r.index == 3)
replay.restart(r); replay.set_speed(r, "Slow"); replay.toggle(r); assert(not replay.update(r, 0.4))
replay.set_speed(r, "Fast"); assert(replay.update(r, 0.16)); assert(r.index == 2)
replay.update(r, 10); assert(r.index == 3) -- a stall advances one boundary only
replay.step(r, 20); replay.toggle(r); replay.update(r, 1); assert(r.index == 7 and not r.playing)
print("replay tests passed")
