-- Small catalog browser. SQLite and replay bundle creation stay in Python.
local M = {}

-- Completion status is not a game outcome. Use only explicit ending evidence.
function M.result_label(game)
    local reason = game.termination_reason
    if game.terminal_class == "infrastructure" or reason == "infrastructure_failure" then
        return "Infrastructure error"
    elseif game.terminal_class == "model_invalid" or reason == "model_invalid" then
        return "Model error"
    elseif game.failure_code or game.gameplay_valid == false then
        return "Execution error"
    end
    local winner = game.winner_side
    if (winner == 0 or winner == 1) and
        (reason == "winner" or reason == "loss" or reason == "resignation") then
        local label = "Side " .. tostring(winner) .. " won"
        if reason == "resignation" then label = label .. " (resignation)" end
        return label, "win"
    end
    if winner == nil and (reason == "max_turns" or reason == "turn_limit") then
        return "Draw (turn limit)", "draw"
    end
    if game.status == "incomplete" and reason == nil and winner == nil then return "Incomplete" end
    return "Outcome unknown"
end

function M.side_color(game, side)
    local _, outcome = M.result_label(game)
    if outcome == "draw" then return 1, .82, .25, 1 end
    if outcome == "win" then
        if game.winner_side == side then return .35, .85, .45, 1 end
        return 1, .4, .4, 1
    end
    return .85, .85, .85, 1
end

function M.played_time(value)
    local stamp = tostring(value or "unknown")
    return (stamp:match("^(%d%d%d%d%-%d%d%-%d%d[T ]%d%d:%d%d:%d%d)") or stamp):gsub("T", " ")
end

function M.gold_turns(game)
    local turns = type(game.played_turns) == "number" and string.format("%g", game.played_turns) or "?"
    return tostring(game.starting_gold or "?") .. "/" .. turns
end

local function quote(value)
    return "'" .. tostring(value):gsub("'", "'\\''") .. "'"
end

local function request(root, args, json_decode)
    local command = "python3 -m tools.recorded_games " .. args .. " 2>&1"
    local pipe = io.popen("cd " .. quote(root) .. " && " .. command, "r")
    if not pipe then return nil, "could not start history helper" end
    local raw = pipe:read("*a") or ""
    local ok, why, code = pipe:close()
    local decoded = nil
    if raw ~= "" then
        local success, value = pcall(json_decode, raw)
        if success then decoded = value end
    end
    if type(decoded) ~= "table" then return nil, "history helper returned invalid JSON: " .. raw:sub(1, 180) end
    if decoded.error then return decoded, decoded.error end
    if not ok then return nil, "history helper failed (" .. tostring(code or why) .. ")" end
    return decoded
end

function M.new(root, json_decode, open_replay)
    local browser = {root = root, db = root .. "/.norrust_history/history.sqlite", rows = {}, selected = 1,
                     offset = 0, total = 0, error = nil, detail = nil, open_replay = open_replay,
                     loading = false}
    function browser:refresh()
        local selected_id = self.detail and self.detail.game_id
        local result, err = request(self.root, "list --root " .. quote(self.root) .. " --limit 25 --offset " .. tostring(self.offset), json_decode)
        if result and not err and (type(result.games) ~= "table" or type(result.total) ~= "number") then
            result, err = nil, "history helper returned an invalid game list"
        end
        self.error = err
        if result and not err then
            self.rows, self.total = result.games or {}, result.total or 0
            self.diagnostics = result.diagnostics or {}
            self.selected = 1
            for i, row in ipairs(self.rows) do
                if row.game_id == selected_id then self.selected = i; break end
            end
        end
        self.loading = false
        self.selected = math.max(1, math.min(self.selected, math.max(1, #self.rows)))
        self.detail = self.rows[self.selected]
    end
    function browser:watch()
        local row = self.rows[self.selected]
        if not row then return end
        local output = os.tmpname()
        local result, err = request(self.root, "export --db " .. quote(row.catalog or self.db) .. " --game-id " .. quote(row.game_id) .. " --output " .. quote(output), json_decode)
        if result and result.bundle and not err then
            local ok, load_error = pcall(self.open_replay, output, self)
            if ok then self.error = nil else self.error = tostring(load_error) end
        else self.error = err end
        os.remove(output)
    end
    function browser:move(delta)
        if #self.rows == 0 then return end
        self.selected = math.max(1, math.min(#self.rows, self.selected + delta))
        self.detail = self.rows[self.selected]
    end
    function browser:page(delta)
        local last = math.max(0, math.floor((self.total - 1) / 25) * 25)
        local offset = math.max(0, math.min(last, self.offset + delta * 25))
        if offset ~= self.offset then self.offset = offset; self:refresh() end
    end
    browser:refresh()
    return browser
end

function M.hit(button, x, y)
    return button and x >= button.x and x < button.x + button.w
        and y >= button.y and y < button.y + button.h
end

-- Drawing and input share these rectangles, including the visible row window.
function M.layout(browser, width, height)
    local count = math.max(1, math.floor((height - 235) / 24))
    local top = math.max(1, browser.selected - count + 1)
    local layout = {rows = {}, detail_y = 86 + count * 24 + 8}
    for i = top, math.min(#browser.rows, top + count - 1) do
        layout.rows[#layout.rows + 1] = {index = i, x = 20, y = 83 + (i - top) * 24, w = width - 40, h = 24}
    end
    for i, key in ipairs({"watch", "refresh", "previous", "next", "menu"}) do
        layout[key] = {x = 20 + (i - 1) * 82, y = height - 36, w = 78, h = 23}
    end
    return layout
end

function M.click(browser, x, y, width, height)
    local layout = M.layout(browser, width, height)
    if M.hit(layout.watch, x, y) then browser:watch()
    elseif M.hit(layout.refresh, x, y) then browser:refresh()
    elseif M.hit(layout.previous, x, y) then browser:page(-1)
    elseif M.hit(layout.next, x, y) then browser:page(1)
    elseif M.hit(layout.menu, x, y) then return "menu"
    else
        for _, rect in ipairs(layout.rows) do
            if M.hit(rect, x, y) then
                browser.selected = rect.index; browser.detail = browser.rows[rect.index]; break
            end
        end
    end
end

return M
