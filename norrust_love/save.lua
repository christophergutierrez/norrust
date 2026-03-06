-- save.lua — Save/load game state to TOML files in Love2D save directory

local toml_parser = require("toml_parser")

local save = {}

-- ── TOML serialization ──────────────────────────────────────────────────────

--- Serialize a Lua value to a TOML value string.
local function toml_value(v)
    local t = type(v)
    if t == "string" then
        return '"' .. v:gsub('\\', '\\\\'):gsub('"', '\\"') .. '"'
    elseif t == "number" then
        if v == math.floor(v) then
            return string.format("%d", v)
        end
        return tostring(v)
    elseif t == "boolean" then
        return v and "true" or "false"
    end
    return tostring(v)
end

--- Serialize a save data table to TOML string.
--- Expects: {game = {key=val,...}, units = {{key=val,...}, ...}}
function save.serialize_toml(data)
    local lines = {}
    lines[#lines + 1] = "# Norrust save file"
    lines[#lines + 1] = ""

    -- [game] section
    if data.game then
        lines[#lines + 1] = "[game]"
        for k, v in pairs(data.game) do
            lines[#lines + 1] = k .. " = " .. toml_value(v)
        end
        lines[#lines + 1] = ""
    end

    -- [[units]] array-of-tables
    if data.units then
        for _, unit in ipairs(data.units) do
            lines[#lines + 1] = "[[units]]"
            -- Write fields in a consistent order
            local order = {"id", "def_id", "faction", "col", "row", "hp", "max_hp", "xp", "xp_needed", "moved", "attacked"}
            for _, k in ipairs(order) do
                if unit[k] ~= nil then
                    lines[#lines + 1] = k .. " = " .. toml_value(unit[k])
                end
            end
            lines[#lines + 1] = ""
        end
    end

    return table.concat(lines, "\n")
end

-- ── Save ────────────────────────────────────────────────────────────────────

--- Save the current game state to a TOML file.
--- Returns the filename on success, nil on failure.
function save.write_save(engine, norrust, scenario_board, scenarios_path)
    local state = norrust.get_state(engine)
    if not state then return nil end

    local int = math.floor

    -- Build save data
    local data = {
        game = {
            board_path = scenario_board,
            scenarios_path = scenarios_path,
            turn = int(state.turn),
            active_faction = int(state.active_faction),
            gold_0 = int(state.gold[1]),
            gold_1 = int(state.gold[2]),
        },
        units = {},
    }

    -- Add objective/max_turns if present
    if state.objective_col then
        data.game.objective_col = int(state.objective_col)
        data.game.objective_row = int(state.objective_row)
    end
    if state.max_turns then
        data.game.max_turns = int(state.max_turns)
    end

    for _, u in ipairs(state.units or {}) do
        data.units[#data.units + 1] = {
            id = int(u.id),
            def_id = u.def_id,
            faction = int(u.faction),
            col = int(u.col),
            row = int(u.row),
            hp = int(u.hp),
            max_hp = int(u.max_hp),
            xp = int(u.xp),
            xp_needed = int(u.xp_needed),
            moved = u.moved,
            attacked = u.attacked,
        }
    end

    local toml_str = save.serialize_toml(data)

    -- Create saves directory
    love.filesystem.createDirectory("saves")

    -- Generate filename: YYYY-MM-DD_HHMMSS_scenario.toml
    local date = os.date("%Y-%m-%d_%H%M%S")
    local scenario_name = scenario_board:gsub("%.toml$", "")
    local filename = "saves/" .. date .. "_" .. scenario_name .. ".toml"

    local ok, err = love.filesystem.write(filename, toml_str)
    if not ok then
        print("[SAVE] Failed to write: " .. tostring(err))
        return nil
    end

    print("[SAVE] Written: " .. filename)
    return filename
end

-- ── Load ────────────────────────────────────────────────────────────────────

--- Parse a TOML save file that uses [[units]] array-of-tables.
--- Returns a table with game={...} and units={{...}, ...}.
local function parse_save_toml(text)
    local result = {game = {}, units = {}}
    local current_section = nil  -- "game" or nil
    local current_unit = nil     -- table being built for current [[units]] block

    for line in text:gmatch("[^\r\n]+") do
        -- Strip comments
        local comment_pos = line:find("#")
        if comment_pos then
            local in_string = false
            for i = 1, comment_pos - 1 do
                if line:sub(i, i) == '"' then in_string = not in_string end
            end
            if not in_string then
                line = line:sub(1, comment_pos - 1)
            end
        end
        line = line:match("^%s*(.-)%s*$")

        if line ~= "" then
            -- [[units]] array-of-tables
            local aot = line:match("^%[%[([^%]]+)%]%]$")
            if aot then
                aot = aot:match("^%s*(.-)%s*$")
                if aot == "units" then
                    if current_unit then
                        result.units[#result.units + 1] = current_unit
                    end
                    current_unit = {}
                    current_section = nil
                end
            else
                -- [section] header
                local section = line:match("^%[([^%]]+)%]$")
                if section then
                    if current_unit then
                        result.units[#result.units + 1] = current_unit
                        current_unit = nil
                    end
                    section = section:match("^%s*(.-)%s*$")
                    current_section = section
                    if not result[section] then
                        result[section] = {}
                    end
                else
                    -- key = value
                    local key, value = line:match("^([%w_%-]+)%s*=%s*(.+)$")
                    if key and value then
                        local parsed
                        -- String
                        local str = value:match('^"(.*)"$')
                        if str then
                            parsed = str
                        else
                            local num = tonumber(value)
                            if num then
                                parsed = num
                            elseif value == "true" then
                                parsed = true
                            elseif value == "false" then
                                parsed = false
                            else
                                parsed = value
                            end
                        end

                        if current_unit then
                            current_unit[key] = parsed
                        elseif current_section and result[current_section] then
                            result[current_section][key] = parsed
                        end
                    end
                end
            end
        end
    end

    -- Flush last unit if any
    if current_unit then
        result.units[#result.units + 1] = current_unit
    end

    return result
end

--- Load a save file and reconstruct engine state.
--- Returns the parsed save data on success, nil on failure.
function save.load_save(engine, norrust, filepath, center_camera_fn)
    local text = love.filesystem.read(filepath)
    if not text then
        print("[LOAD] Failed to read: " .. filepath)
        return nil
    end

    local data = parse_save_toml(text)
    if not data or not data.game or not data.game.board_path then
        print("[LOAD] Invalid save file format")
        return nil
    end

    local int = math.floor
    local g = data.game

    -- Load board (creates fresh GameState with terrain)
    local board_full_path = g.scenarios_path .. "/" .. g.board_path
    local ok = norrust.load_board(engine, board_full_path, 42)
    if not ok then
        print("[LOAD] Failed to load board: " .. board_full_path)
        return nil
    end

    -- Set objective/max_turns if saved
    if g.objective_col then
        norrust.set_objective_hex(engine, int(g.objective_col), int(g.objective_row))
    end
    if g.max_turns then
        norrust.set_max_turns(engine, int(g.max_turns))
    end

    -- Place units and restore combat state
    for _, u in ipairs(data.units) do
        norrust.place_unit_at(engine, int(u.id), u.def_id, 0, int(u.faction), int(u.col), int(u.row))
        if u.hp then
            norrust.set_unit_combat_state(engine, int(u.id), int(u.hp), int(u.xp or 0), u.moved, u.attacked)
        end
    end

    -- Restore gold, turn, active faction
    norrust.set_faction_gold(engine, 0, int(g.gold_0))
    norrust.set_faction_gold(engine, 1, int(g.gold_1))
    norrust.set_turn(engine, int(g.turn))
    norrust.set_active_faction(engine, int(g.active_faction))

    print("[LOAD] Loaded: " .. filepath)
    return data
end

--- Find the most recent save file.
--- Returns filepath relative to save dir, or nil if none.
function save.find_latest()
    local items = love.filesystem.getDirectoryItems("saves")
    if not items or #items == 0 then return nil end

    -- Sort alphabetically (date-first naming = chronological)
    table.sort(items)
    -- Return last = most recent
    return "saves/" .. items[#items]
end

return save
