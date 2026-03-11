-- save.lua — Save/load game state (JSON format, backward-compat TOML reading)

local norrust_mod = require("norrust")
local json_encode = norrust_mod.json_encode
local json_decode = norrust_mod.json_decode

local save = {}

-- ── Save ────────────────────────────────────────────────────────────────────

--- Save the current game state to a JSON file via single FFI call.
--- Returns the filename on success, nil on failure.
function save.write_save(engine, norrust, scenario_board, display_name)
    -- Set display name on engine before serializing
    norrust.set_display_name(engine, display_name or "")

    -- Get full state as JSON from engine
    local json_str = norrust.save_json(engine)
    if not json_str or json_str == "" then return nil end

    -- Create saves directory
    love.filesystem.createDirectory("saves")

    -- Generate filename: YYYY-MM-DD_HHMMSS_scenario.json
    local date = os.date("%Y-%m-%d_%H%M%S")
    local scenario_name = scenario_board:match("^(.+)/board%.toml$") or scenario_board:gsub("%.toml$", "")
    local filename = "saves/" .. date .. "_" .. scenario_name .. ".json"

    local ok, err = love.filesystem.write(filename, json_str)
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
--- Supports new JSON (single FFI call), old JSON, and legacy TOML save files.
--- Returns the parsed save data on success, nil on failure.
function save.load_save(engine, norrust, filepath, center_camera_fn)
    local text = love.filesystem.read(filepath)
    if not text then
        print("[LOAD] Failed to read: " .. filepath)
        return nil
    end

    -- JSON saves
    if filepath:match("%.json$") then
        local data = json_decode(text)
        if not data then
            print("[LOAD] Invalid JSON save file")
            return nil
        end

        -- New Rust-format saves have board_path at top level
        if data.board_path then
            local ok = norrust.load_json(engine, text)
            if not ok then
                print("[LOAD] Failed to restore engine state from JSON")
                return nil
            end
            print("[LOAD] Loaded: " .. filepath)
            return data
        end

        -- Old JSON format: fall through to legacy multi-call restore
        if not data.game or not data.game.board_path then
            print("[LOAD] Invalid save file format")
            return nil
        end
        return save._legacy_restore(engine, norrust, data, filepath)
    end

    -- TOML saves: parse and use legacy restore
    local data = parse_save_toml(text)
    if not data or not data.game or not data.game.board_path then
        print("[LOAD] Invalid save file format")
        return nil
    end
    return save._legacy_restore(engine, norrust, data, filepath)
end

--- Legacy multi-call restore for old JSON and TOML save files.
function save._legacy_restore(engine, norrust, data, filepath)
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
        norrust.restore_unit_at(engine, int(u.id), u.def_id, int(u.faction), int(u.col), int(u.row))
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
        local dialogue_path = g.scenarios_path .. "/" .. g.board_path:gsub("board%.toml$", "dialogue.toml")
        norrust.load_dialogue(engine, dialogue_path)
        local items = {}
        for _, id in ipairs(data.state.dialogue_fired) do
            items[#items + 1] = '"' .. id:gsub('\\', '\\\\'):gsub('"', '\\"') .. '"'
        end
        norrust.set_dialogue_fired(engine, "[" .. table.concat(items, ",") .. "]")
    end

    print("[LOAD] Loaded: " .. filepath)
    return data
end

--- Find the most recent save file (JSON or TOML).
--- Returns filepath relative to save dir, or nil if none.
function save.find_latest()
    local items = love.filesystem.getDirectoryItems("saves")
    if not items or #items == 0 then return nil end

    -- Filter to save files only
    local saves = {}
    for _, f in ipairs(items) do
        if f:match("%.json$") or f:match("%.toml$") then
            saves[#saves + 1] = f
        end
    end
    if #saves == 0 then return nil end

    -- Sort alphabetically (date-first naming = chronological)
    table.sort(saves)
    -- Return last = most recent
    return "saves/" .. saves[#saves]
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
        if filename:match("%.json$") or filename:match("%.toml$") then
            local filepath = "saves/" .. filename
            -- Parse date and scenario from filename: YYYY-MM-DD_HHMMSS_scenario.{json,toml}
            local year, month, day, hour, min, sec, scen_name =
                filename:match("^(%d+)-(%d+)-(%d+)_(%d%d)(%d%d)(%d%d)_(.+)%.%a+$")

            local date_str = "Unknown"
            local scenario = scen_name or filename
            if year then
                date_str = string.format("%s-%s-%s %s:%s:%s", year, month, day, hour, min, sec)
            end

            -- Read metadata: turn, campaign, display_name
            local turn = "?"
            local campaign_name = nil
            local display_name = nil
            local text = love.filesystem.read(filepath)
            if text then
                if filepath:match("%.json$") then
                    -- JSON save: parse and extract fields
                    local d = json_decode(text)
                    if d then
                        if d.board_path then
                            -- New Rust-format save
                            turn = tostring(d.turn or "?")
                            display_name = d.display_name
                            if d.campaign and d.campaign.campaign_def then
                                campaign_name = d.campaign.campaign_def.name
                            end
                        elseif d.game then
                            -- Old JSON format
                            turn = tostring(d.game.turn or "?")
                            display_name = d.game.display_name
                            if display_name == "" then display_name = nil end
                            if d.campaign and d.campaign.campaign_file then
                                campaign_name = d.campaign.campaign_file:gsub("%.toml$", "")
                            end
                        end
                    end
                else
                    -- Legacy TOML save: line-scan
                    local in_game = false
                    local in_campaign = false
                    for line in text:gmatch("[^\r\n]+") do
                        if line:match("^%[game%]") then
                            in_game = true; in_campaign = false
                        elseif line:match("^%[campaign%]") then
                            in_campaign = true; in_game = false
                        elseif line:match("^%[") then
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

--- Update the display_name field in a save file.
function save.update_display_name(filepath, name)
    local text = love.filesystem.read(filepath)
    if not text then return false end

    if filepath:match("%.json$") then
        -- JSON: parse, modify, re-encode
        local data = json_decode(text)
        if not data then return false end
        if data.board_path then
            -- New Rust-format save
            data.display_name = name
            love.filesystem.write(filepath, json_encode(data))
            return true
        elseif data.game then
            -- Old JSON format
            data.game.display_name = name
            love.filesystem.write(filepath, json_encode(data))
            return true
        end
        return false
    end

    -- Legacy TOML: targeted string replacement
    local safe_name = name:gsub('\\', '\\\\'):gsub('"', '\\"')
    local new_line = 'display_name = "' .. safe_name .. '"'

    local replaced
    replaced = text:gsub('(display_name%s*=%s*"[^"]*")', new_line, 1)
    if replaced ~= text then
        love.filesystem.write(filepath, replaced)
        return true
    end

    replaced = text:gsub('%[game%]\n', '[game]\n' .. new_line .. '\n', 1)
    if replaced ~= text then
        love.filesystem.write(filepath, replaced)
        return true
    end

    return false
end

return save
