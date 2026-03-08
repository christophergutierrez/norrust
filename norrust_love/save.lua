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

--- Serialize a Lua array to a TOML inline array string.
local function toml_array(arr)
    local items = {}
    for _, v in ipairs(arr) do
        items[#items + 1] = toml_value(v)
    end
    return "[" .. table.concat(items, ", ") .. "]"
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

    -- [campaign] section (optional)
    if data.campaign then
        lines[#lines + 1] = "[campaign]"
        local camp_order = {"campaign_file", "campaign_index", "campaign_gold", "faction_id_0", "faction_id_1"}
        for _, k in ipairs(camp_order) do
            if data.campaign[k] ~= nil then
                lines[#lines + 1] = k .. " = " .. toml_value(data.campaign[k])
            end
        end
        lines[#lines + 1] = ""
    end

    -- [state] section (trigger zones + dialogue fired)
    if data.state then
        lines[#lines + 1] = "[state]"
        if data.state.trigger_zones_fired then
            lines[#lines + 1] = "trigger_zones_fired = " .. toml_array(data.state.trigger_zones_fired)
        end
        if data.state.dialogue_fired then
            lines[#lines + 1] = "dialogue_fired = " .. toml_array(data.state.dialogue_fired)
        end
        lines[#lines + 1] = ""
    end

    -- [[veterans]] array-of-tables (campaign carry-over units)
    if data.veterans then
        for _, vet in ipairs(data.veterans) do
            lines[#lines + 1] = "[[veterans]]"
            local vet_order = {"def_id", "hp", "xp", "xp_needed", "advancement_pending"}
            for _, k in ipairs(vet_order) do
                if vet[k] ~= nil then
                    lines[#lines + 1] = k .. " = " .. toml_value(vet[k])
                end
            end
            lines[#lines + 1] = ""
        end
    end

    -- [[roster]] array-of-tables (campaign persistent unit roster)
    if data.roster then
        for _, entry in ipairs(data.roster) do
            lines[#lines + 1] = "[[roster]]"
            local roster_order = {"uuid", "def_id", "hp", "max_hp", "xp", "xp_needed", "advancement_pending", "status"}
            for _, k in ipairs(roster_order) do
                if entry[k] ~= nil then
                    lines[#lines + 1] = k .. " = " .. toml_value(entry[k])
                end
            end
            lines[#lines + 1] = ""
        end
    end

    -- [[units]] array-of-tables
    if data.units then
        for _, unit in ipairs(data.units) do
            lines[#lines + 1] = "[[units]]"
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
--- campaign_ctx: nil for standalone, or {file, index, gold, veterans, faction_id}
--- Returns the filename on success, nil on failure.
function save.write_save(engine, norrust, scenario_board, scenarios_path, campaign_ctx)
    local state = norrust.get_state(engine)
    if not state then return nil end

    local int = math.floor

    -- Build save data
    local data = {
        game = {
            display_name = "",
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

    -- Campaign context
    if campaign_ctx then
        data.campaign = {
            campaign_file = campaign_ctx.file,
            campaign_index = int(campaign_ctx.index),
            campaign_gold = int(campaign_ctx.gold),
            faction_id_0 = campaign_ctx.faction_id[1],
            faction_id_1 = campaign_ctx.faction_id[2],
        }
        -- Veterans from previous scenarios
        if campaign_ctx.veterans and #campaign_ctx.veterans > 0 then
            data.veterans = {}
            for _, vet in ipairs(campaign_ctx.veterans) do
                data.veterans[#data.veterans + 1] = {
                    def_id = vet.def_id,
                    hp = int(vet.hp),
                    xp = int(vet.xp),
                    xp_needed = int(vet.xp_needed),
                    advancement_pending = vet.advancement_pending,
                }
            end
        end
        -- Roster (persistent unit identity)
        if campaign_ctx.roster and #campaign_ctx.roster > 0 then
            data.roster = campaign_ctx.roster
        end
    end

    -- Trigger zone and dialogue fired state
    data.state = {}
    local tz_fired = norrust.get_trigger_zones_fired(engine)
    if #tz_fired > 0 then
        data.state.trigger_zones_fired = tz_fired
    end
    local dlg_fired = norrust.get_dialogue_fired(engine)
    if #dlg_fired > 0 then
        data.state.dialogue_fired = dlg_fired
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
    local scenario_name = scenario_board:match("^(.+)/board%.toml$") or scenario_board:gsub("%.toml$", "")
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

--- Parse a TOML inline array value like [true, false, "hello"].
local function parse_toml_array(s)
    local inner = s:match("^%[(.*)%]$")
    if not inner then return nil end
    local arr = {}
    for item in inner:gmatch("[^,]+") do
        item = item:match("^%s*(.-)%s*$")
        if item == "true" then
            arr[#arr + 1] = true
        elseif item == "false" then
            arr[#arr + 1] = false
        else
            local str = item:match('^"(.*)"$')
            if str then
                arr[#arr + 1] = str
            else
                local num = tonumber(item)
                if num then
                    arr[#arr + 1] = num
                else
                    arr[#arr + 1] = item
                end
            end
        end
    end
    return arr
end

--- Parse a TOML save file with [[units]], [[veterans]], and inline arrays.
--- Returns a table with game={...}, units={{...},...}, campaign={...}, state={...}, veterans={{...},...}.
local function parse_save_toml(text)
    local result = {game = {}, units = {}, veterans = {}}
    local current_section = nil
    local current_aot = nil       -- "units" or "veterans"
    local current_aot_entry = nil  -- table being built for current array-of-tables block

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
            -- [[array-of-tables]]
            local aot = line:match("^%[%[([^%]]+)%]%]$")
            if aot then
                aot = aot:match("^%s*(.-)%s*$")
                -- Flush previous entry
                if current_aot_entry and current_aot then
                    if not result[current_aot] then result[current_aot] = {} end
                    result[current_aot][#result[current_aot] + 1] = current_aot_entry
                end
                current_aot = aot
                current_aot_entry = {}
                current_section = nil
            else
                -- [section] header
                local section = line:match("^%[([^%]]+)%]$")
                if section then
                    -- Flush previous array-of-tables entry
                    if current_aot_entry and current_aot then
                        if not result[current_aot] then result[current_aot] = {} end
                        result[current_aot][#result[current_aot] + 1] = current_aot_entry
                        current_aot_entry = nil
                        current_aot = nil
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
                        -- Inline array
                        if value:sub(1, 1) == "[" then
                            parsed = parse_toml_array(value)
                        else
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
                        end

                        if current_aot_entry then
                            current_aot_entry[key] = parsed
                        elseif current_section and result[current_section] then
                            result[current_section][key] = parsed
                        end
                    end
                end
            end
        end
    end

    -- Flush last array-of-tables entry
    if current_aot_entry and current_aot then
        if not result[current_aot] then result[current_aot] = {} end
        result[current_aot][#result[current_aot] + 1] = current_aot_entry
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

    -- Restore trigger zone fired state
    if data.state and data.state.trigger_zones_fired then
        for i, fired in ipairs(data.state.trigger_zones_fired) do
            if fired then
                norrust.set_trigger_zone_fired(engine, i - 1, true)
            end
        end
    end

    -- Restore dialogue fired state
    if data.state and data.state.dialogue_fired and #data.state.dialogue_fired > 0 then
        -- Load dialogue file first (derived from board filename)
        local dialogue_path = g.scenarios_path .. "/" .. g.board_path:gsub("%.toml$", "_dialogue.toml")
        norrust.load_dialogue(engine, dialogue_path)
        -- Build JSON array and pass to FFI
        local items = {}
        for _, id in ipairs(data.state.dialogue_fired) do
            items[#items + 1] = '"' .. id:gsub('\\', '\\\\'):gsub('"', '\\"') .. '"'
        end
        norrust.set_dialogue_fired(engine, "[" .. table.concat(items, ",") .. "]")
    end

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

--- List all save files with metadata, reverse-chronological.
--- Returns array of {filepath, date_str, scenario, turn, campaign}.
function save.list_saves()
    local items = love.filesystem.getDirectoryItems("saves")
    if not items or #items == 0 then return {} end

    -- Sort reverse-alphabetical (date-first naming = reverse-chronological)
    table.sort(items, function(a, b) return a > b end)

    local saves = {}
    for _, filename in ipairs(items) do
        if filename:match("%.toml$") then
            local filepath = "saves/" .. filename
            -- Parse date and scenario from filename: YYYY-MM-DD_HHMMSS_scenario.toml
            local year, month, day, hour, min, sec, scen_name =
                filename:match("^(%d+)-(%d+)-(%d+)_(%d%d)(%d%d)(%d%d)_(.+)%.toml$")

            local date_str = "Unknown"
            local scenario = scen_name or filename
            if year then
                date_str = string.format("%s-%s-%s %s:%s:%s", year, month, day, hour, min, sec)
            end

            -- Read header lines to extract turn, campaign, and display_name
            local turn = "?"
            local campaign_name = nil
            local display_name = nil
            local text = love.filesystem.read(filepath)
            if text then
                local in_game = false
                local in_campaign = false
                for line in text:gmatch("[^\r\n]+") do
                    if line:match("^%[game%]") then
                        in_game = true; in_campaign = false
                    elseif line:match("^%[campaign%]") then
                        in_campaign = true; in_game = false
                    elseif line:match("^%[") then
                        -- Any other section — stop scanning headers
                        if not in_game and not in_campaign then break end
                        in_game = false; in_campaign = false
                    end
                    if in_game then
                        local t = line:match("^turn%s*=%s*(%d+)")
                        if t then turn = t end
                        local dn = line:match('^display_name%s*=%s*"([^"]*)"')
                        if dn then display_name = dn end
                    end
                    if in_campaign then
                        local cf = line:match('^campaign_file%s*=%s*"([^"]+)"')
                        if cf then campaign_name = cf:gsub("%.toml$", "") end
                    end
                end
            end

            saves[#saves + 1] = {
                filepath = filepath,
                date_str = date_str,
                scenario = scenario,
                turn = turn,
                campaign = campaign_name,
                display_name = (display_name and display_name ~= "") and display_name or nil,
            }
        end
    end

    return saves
end

--- Delete a save file.
function save.delete_save(filepath)
    local ok = love.filesystem.remove(filepath)
    if ok then
        print("[SAVE] Deleted: " .. filepath)
    else
        print("[SAVE] Failed to delete: " .. filepath)
    end
    return ok
end

--- Update the display_name field in a save file's [game] section.
--- Performs targeted string replacement without full re-parse.
function save.update_display_name(filepath, name)
    local text = love.filesystem.read(filepath)
    if not text then return false end

    -- Escape quotes in name for TOML
    local safe_name = name:gsub('\\', '\\\\'):gsub('"', '\\"')
    local new_line = 'display_name = "' .. safe_name .. '"'

    -- Try to replace existing display_name line
    local replaced
    replaced = text:gsub('(display_name%s*=%s*"[^"]*")', new_line, 1)
    if replaced ~= text then
        love.filesystem.write(filepath, replaced)
        return true
    end

    -- No existing display_name — insert after [game] header
    replaced = text:gsub('%[game%]\n', '[game]\n' .. new_line .. '\n', 1)
    if replaced ~= text then
        love.filesystem.write(filepath, replaced)
        return true
    end

    return false
end

return save
