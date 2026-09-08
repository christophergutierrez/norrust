-- Small catalog browser. SQLite and replay bundle creation stay in Python.
local M = {}

local function quote(value)
    return "'" .. tostring(value):gsub("'", "'\\''") .. "'"
end

local function request(root, args)
    local command = "python3 -m tools.recorded_games " .. args .. " 2>&1"
    local pipe = io.popen("cd " .. quote(root) .. " && " .. command, "r")
    if not pipe then return nil, "could not start history helper" end
    local raw = pipe:read("*a") or ""
    local ok, why, code = pipe:close()
    local first = raw:match("(%b{}).*%s*$") or raw
    local decoded = nil
    if first ~= "" then
        local success, value = pcall(M.json_decode, first)
        if success then decoded = value end
    end
    if not decoded then return nil, "history helper returned invalid JSON: " .. raw:sub(1, 180) end
    if decoded.error then return decoded, decoded.error end
    if ok == false and not decoded then return nil, "history helper failed (" .. tostring(code or why) .. ")" end
    return decoded
end

function M.new(root, json_decode, open_replay)
    M.json_decode = json_decode
    local browser = {root = root, db = root .. "/.norrust_history/history.sqlite", rows = {}, selected = 1,
                     offset = 0, total = 0, error = nil, detail = nil, open_replay = open_replay,
                     loading = false}
    function browser:refresh()
        local result, err = request(self.root, "list --db " .. quote(self.db) .. " --limit 25 --offset " .. tostring(self.offset))
        self.error = err
        if result then self.rows, self.total = result.games or {}, result.total or 0 end
        self.loading = false
        self.selected = math.max(1, math.min(self.selected, math.max(1, #self.rows)))
        self.detail = self.rows[self.selected]
    end
    function browser:watch()
        local row = self.rows[self.selected]
        if not row then return end
        local output = os.tmpname() .. ".json"
        local result, err = request(self.root, "export --db " .. quote(self.db) .. " --game-id " .. quote(row.game_id) .. " --output " .. quote(output))
        if result and result.bundle then self.open_replay(result.bundle, self) else self.error = err end
    end
    function browser:move(delta)
        if #self.rows == 0 then return end
        self.selected = math.max(1, math.min(#self.rows, self.selected + delta))
        self.detail = self.rows[self.selected]
    end
    browser:refresh()
    return browser
end

return M
