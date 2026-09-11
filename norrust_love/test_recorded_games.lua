package.path = "norrust_love/?.lua;" .. package.path
local norrust = require("norrust")
local recorded = require("recorded_games")
local input = require("input")
local replay = require("replay")

for _, case in ipairs({
    {{status = "complete", termination_reason = "max_turns"}, "Draw (turn limit)"},
    {{status = "complete", termination_reason = "turn_limit"}, "Draw (turn limit)"},
    {{status = "complete", termination_reason = "winner", winner_side = 0}, "Side 0 won"},
    {{status = "complete", termination_reason = "winner", winner_side = 1}, "Side 1 won"},
    {{status = "complete", termination_reason = "resignation", winner_side = 0}, "Side 0 won (resignation)"},
    {{status = "complete", termination_reason = "resignation", winner_side = 1}, "Side 1 won (resignation)"},
    {{status = "complete"}, "Outcome unknown"},
    {{status = "incomplete"}, "Incomplete"},
    {{status = "complete", termination_reason = "model_invalid"}, "Model error"},
    {{status = "complete", termination_reason = "infrastructure_failure"}, "Infrastructure error"},
    {{termination_reason = "winner", winner_side = 0, terminal_class = "infrastructure"}, "Infrastructure error"},
    {{termination_reason = "max_turns", failure_code = "bad_response"}, "Execution error"},
    {{termination_reason = "winner", winner_side = 1, terminal_class = "model_invalid"}, "Model error"},
    {{termination_reason = "budget_interrupted", failure_code = "max_game_total_tokens_exhausted", terminal_class = "budget_interrupted"}, "Budget interrupted"},
    {{termination_reason = "budget_interrupted", failure_code = "model_calls_budget_exhausted", terminal_class = "model_invalid"}, "Budget interrupted"},
    {{failure_code = "max_game_total_tokens_exhausted"}, "Budget interrupted"},
    {{termination_reason = "max_turns", winner_side = 1}, "Outcome unknown"},
    {{termination_reason = "winner", winner_side = 2}, "Outcome unknown"},
}) do
    assert(recorded.result_label(case[1]) == case[2], case[2])
end

assert(recorded.played_time("2026-09-08T13:54:23.581252+00:00") == "2026-09-08 13:54:23")
assert(recorded.played_time("2026-09-08T13:54:23Z") == "2026-09-08 13:54:23")
assert(recorded.played_time(nil) == "unknown")
assert(recorded.gold_turns({starting_gold = 50, played_turns = 15}) == "50/15")
assert(recorded.gold_turns({starting_gold = 0, played_turns = 24.5}) == "0/24.5")
assert(recorded.gold_turns({starting_gold = 100}) == "100/?")
for winner = 0, 1 do
    local game = {termination_reason = "resignation", winner_side = winner}
    local r, g = recorded.side_color(game, winner)
    assert(g > r, "winner must be green")
    r, g = recorded.side_color(game, 1 - winner)
    assert(r > g, "loser must be red")
    game.terminal_class = "model_invalid"
    r, g = recorded.side_color(game, winner)
    assert(r == g, "failed execution must stay neutral")
    game.terminal_class = "budget_interrupted"
    r, g = recorded.side_color(game, winner)
    assert(r == g, "budget interruption must stay neutral")
end

-- Rows convey outcomes by side colors; details retain the written outcome.
local drawn = {}
local colors, current_color = {}, {}
local original_love = love
love = {graphics = setmetatable({
    setColor = function(...) current_color = {...} end,
    print = function(text) drawn[#drawn + 1] = text; colors[text] = current_color end,
    printf = function(text) drawn[#drawn + 1] = text end,
}, {__index = function() return function() end end})}
local draw_screens = require("draw_screens")
local draw_game = {game_id = "draw", status = "complete", termination_reason = "max_turns",
                  started_at = "2026-09-08T13:54:23.581252+00:00", starting_gold = 50, played_turns = 15,
                  players = {{name = "LLM"}, {name = "Greedy"}}}
draw_screens.draw_recorded_games({vp_w = 768, vp_h = 432, fonts = {},
    recorded_browser = {rows = {draw_game}, selected = 1, detail = draw_game}})
local text = table.concat(drawn, "\n")
assert(text:find("Draw (turn limit)", 1, true))
assert(text:find("Ending: Draw (turn limit)", 1, true))
assert(not text:find("complete", 1, true))
assert(not colors.Result and not colors["Draw (turn limit)"])
assert(colors["Gold/Turns"] and colors["50/15"])
assert(colors["2026-09-08 13:54:23"] and not text:find("581252", 1, true))
for _, name in ipairs({"LLM / ?", "Greedy / ?"}) do
    local color = colors[name]
    assert(color[1] == 1 and color[2] == .82 and color[3] == .25, "both sides of draw must be yellow")
end
love = original_love

local rows = {}
for i = 1, 25 do rows[i] = {game_id = tostring(i), players = {}, name = 'model } " {'} end
local response = {games = rows, total = 27, diagnostics = {"broken catalog skipped"}}
local original_popen, original_tmpname, original_remove = io.popen, os.tmpname, os.remove
local removed, temporary, opened, failed = {}, {}, 0, false
local decoder = norrust.json_decode
io.popen = function(command)
    local payload
    if command:find("export", 1, true) then payload = {bundle = "test-export"}
    else payload = response end
    return {read = function() return norrust.json_encode(payload) end, close = function() return true end}
end
os.tmpname = function() temporary[#temporary + 1] = "test-export"; return "test-export" end
os.remove = function(path) removed[#removed + 1] = path; return true end
local browser = recorded.new("/a repo's path", decoder, function(path)
    opened = opened + 1
    assert(path == "test-export")
    if failed then error("bad replay") end
end)
assert(#browser.rows == 25 and browser.rows[1].name == 'model } " {')
assert(#browser.diagnostics == 1)
for _, malformed in ipairs({false, "not an object", {games = 3, total = 25}}) do
    response = malformed
    browser:refresh()
    assert(browser.error and #browser.rows == 25)
end
response = {games = rows, total = 27}
browser:refresh(); assert(not browser.error)
browser:move(9)
response = {games = {rows[10], rows[1]}, total = 27}
browser:refresh()
assert(browser.selected == 1 and browser.detail.game_id == "10")
browser:page(1); assert(browser.offset == 25)
browser:page(1); assert(browser.offset == 25)
browser:page(-1); assert(browser.offset == 0)
browser:watch(); assert(opened == 1 and #removed == 1 and not browser.error)
failed = true
browser:watch(); assert(browser.error:find("bad replay") and #removed == 2)
assert(#temporary == #removed)

-- Actual input dispatcher: clicks must use the same rectangles as drawing.
browser.rows, browser.total, browser.selected = rows, 27, 25
local shared = {recorded_browser = browser, buttons = {}}
local vars = {game_mode = 7}
local sel = {}
local modes = {RECORDED_GAMES = 7, PLAYING = 4, PICK_SCENARIO = -1}
input.init({vars = vars, shared = shared, sel = sel, MODES = modes, mods = {},
    recorded_games_mod = recorded, replay_mod = replay,
    screen_to_game = function(x, y) return x / 2.5, y / 2.5 end,
    get_viewport = function() return 768, 432 end,
    sound = {play_music = function() end}})
local layout = recorded.layout(browser, 768, 432)
assert(layout.rows[#layout.rows].index == 25)
assert(layout.rows[#layout.rows].y + 24 < layout.detail_y)
local click = function(rect)
    input.mousepressed((rect.x + 4) * 2.5, (rect.y + 4) * 2.5, 1)
end
click(layout.rows[1]); assert(browser.selected == layout.rows[1].index)
failed = false
click(layout.watch); assert(opened == 3 and not browser.error)
assert(browser.selected == layout.rows[1].index) -- button is not a row
-- Returning must preserve the browser object and selection without refreshing.
local before = browser.selected
shared.replay = replay.new({frames = {{state = {}}}}); vars.game_mode = 4
input.keypressed("escape")
assert(vars.game_mode == 7 and shared.replay == nil and browser.selected == before)
-- A CLI replay has no browser: both return controls must go to the menu.
shared.recorded_browser = nil
shared.replay = replay.new({frames = {{state = {}}}}); vars.game_mode = 4
input.keypressed("escape"); assert(vars.game_mode == -1)
shared.replay = replay.new({frames = {{state = {}}}}); vars.game_mode = 4
-- Toolbar hit testing recomputes the same layout drawing uses; it does not
-- read a cached rectangle table.
local replay_layout = replay.layout(shared.replay, {vp_w = 768})
click(replay_layout.buttons.back_to_games); assert(vars.game_mode == -1)
io.popen, os.tmpname, os.remove = original_popen, original_tmpname, original_remove
print("recorded games regression tests passed")
