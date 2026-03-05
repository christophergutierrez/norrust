-- norrust.lua — LuaJIT FFI bindings for norrust_core C ABI
local ffi = require("ffi")
local M = {}

-- ── Minimal JSON decoder ────────────────────────────────────────────────────

local function json_decode(str)
    local pos = 1

    local function skip_ws()
        pos = str:match("^%s*()", pos)
    end

    local function parse_string()
        pos = pos + 1 -- skip opening "
        local parts = {}
        while pos <= #str do
            local c = str:sub(pos, pos)
            if c == '"' then
                pos = pos + 1
                return table.concat(parts)
            elseif c == '\\' then
                pos = pos + 1
                local esc = str:sub(pos, pos)
                if esc == '"' then parts[#parts + 1] = '"'
                elseif esc == '\\' then parts[#parts + 1] = '\\'
                elseif esc == '/' then parts[#parts + 1] = '/'
                elseif esc == 'n' then parts[#parts + 1] = '\n'
                elseif esc == 't' then parts[#parts + 1] = '\t'
                elseif esc == 'r' then parts[#parts + 1] = '\r'
                elseif esc == 'b' then parts[#parts + 1] = '\b'
                elseif esc == 'f' then parts[#parts + 1] = '\f'
                else parts[#parts + 1] = esc end
                pos = pos + 1
            else
                parts[#parts + 1] = c
                pos = pos + 1
            end
        end
    end

    local function parse_number()
        local num_str = str:match("^%-?%d+%.?%d*[eE]?[%+%-]?%d*", pos)
        pos = pos + #num_str
        return tonumber(num_str)
    end

    local parse_value -- forward declaration

    local function parse_array()
        pos = pos + 1 -- skip [
        local arr = {}
        skip_ws()
        if str:sub(pos, pos) == ']' then
            pos = pos + 1
            return arr
        end
        while true do
            skip_ws()
            arr[#arr + 1] = parse_value()
            skip_ws()
            if str:sub(pos, pos) == ',' then
                pos = pos + 1
            else
                break
            end
        end
        skip_ws()
        pos = pos + 1 -- skip ]
        return arr
    end

    local function parse_object()
        pos = pos + 1 -- skip {
        local obj = {}
        skip_ws()
        if str:sub(pos, pos) == '}' then
            pos = pos + 1
            return obj
        end
        while true do
            skip_ws()
            local key = parse_string()
            skip_ws()
            pos = pos + 1 -- skip :
            skip_ws()
            obj[key] = parse_value()
            skip_ws()
            if str:sub(pos, pos) == ',' then
                pos = pos + 1
            else
                break
            end
        end
        skip_ws()
        pos = pos + 1 -- skip }
        return obj
    end

    parse_value = function()
        skip_ws()
        local c = str:sub(pos, pos)
        if c == '"' then return parse_string()
        elseif c == '{' then return parse_object()
        elseif c == '[' then return parse_array()
        elseif c == 't' then pos = pos + 4; return true
        elseif c == 'f' then pos = pos + 5; return false
        elseif c == 'n' then pos = pos + 4; return nil
        else return parse_number()
        end
    end

    return parse_value()
end

M.json_decode = json_decode

-- ── FFI declarations ────────────────────────────────────────────────────────

ffi.cdef[[
    typedef struct NorRustEngine NorRustEngine;

    // Lifecycle
    NorRustEngine* norrust_new(void);
    void norrust_free(NorRustEngine* engine);
    void norrust_free_string(char* s);
    void norrust_free_int_array(int32_t* arr, int32_t len);

    // Data loading
    char* norrust_get_core_version(void);
    int32_t norrust_load_data(NorRustEngine* engine, const char* data_path);
    int32_t norrust_get_unit_max_hp(NorRustEngine* engine, const char* unit_id);

    // Game initialization
    int32_t norrust_create_game(NorRustEngine* engine, int32_t cols, int32_t rows, int64_t seed);
    void norrust_set_terrain_at(NorRustEngine* engine, int32_t col, int32_t row, const char* terrain_id);
    int32_t norrust_generate_map(NorRustEngine* engine, int64_t seed);
    int32_t norrust_load_board(NorRustEngine* engine, const char* board_path, int64_t seed);
    int32_t norrust_load_units(NorRustEngine* engine, const char* units_path);
    char* norrust_get_terrain_at(NorRustEngine* engine, int32_t col, int32_t row);

    // Unit management
    void norrust_place_unit_at(NorRustEngine* engine, int32_t unit_id, const char* def_id, int32_t hp, int32_t faction, int32_t col, int32_t row);
    int32_t norrust_remove_unit_at(NorRustEngine* engine, int32_t col, int32_t row);
    int32_t norrust_get_unit_cost(NorRustEngine* engine, const char* def_id);
    int32_t norrust_get_unit_level(NorRustEngine* engine, const char* def_id);

    // Recruitment
    int32_t norrust_recruit_unit_at(NorRustEngine* engine, int32_t unit_id, const char* def_id, int32_t col, int32_t row);
    int32_t norrust_ai_recruit(NorRustEngine* engine, const char* faction_id, int32_t start_unit_id);
    int32_t norrust_apply_starting_gold(NorRustEngine* engine, const char* f0_id, const char* f1_id);

    // Faction queries
    int32_t norrust_load_factions(NorRustEngine* engine, const char* data_path);
    char* norrust_get_faction_ids_json(NorRustEngine* engine);
    char* norrust_get_faction_leader(NorRustEngine* engine, const char* faction_id);
    char* norrust_get_faction_recruits_json(NorRustEngine* engine, const char* faction_id, int32_t max_level);

    // Game state queries
    int32_t norrust_get_active_faction(NorRustEngine* engine);
    int32_t norrust_get_turn(NorRustEngine* engine);
    char* norrust_get_time_of_day_name(NorRustEngine* engine);
    int32_t norrust_get_winner(NorRustEngine* engine);
    char* norrust_get_state_json(NorRustEngine* engine);
    void norrust_set_objective_hex(NorRustEngine* engine, int32_t col, int32_t row);
    void norrust_set_max_turns(NorRustEngine* engine, int32_t max_turns);

    // Actions
    int32_t norrust_apply_move(NorRustEngine* engine, int32_t unit_id, int32_t col, int32_t row);
    int32_t norrust_apply_attack(NorRustEngine* engine, int32_t attacker_id, int32_t defender_id);
    int32_t norrust_apply_advance(NorRustEngine* engine, int32_t unit_id);
    int32_t norrust_end_turn(NorRustEngine* engine);
    int32_t norrust_apply_action_json(NorRustEngine* engine, const char* json);

    // Pathfinding
    int32_t* norrust_get_reachable_hexes(NorRustEngine* engine, int32_t unit_id, int32_t* out_len);
    int32_t* norrust_find_path(NorRustEngine* engine, int32_t unit_id, int32_t dest_col, int32_t dest_row, int32_t* out_len);

    // AI
    void norrust_ai_take_turn(NorRustEngine* engine, int32_t faction);

    // Trigger zones
    int32_t norrust_get_next_unit_id(NorRustEngine* engine);

    // Campaign
    char* norrust_load_campaign(NorRustEngine* engine, const char* path);
    char* norrust_get_survivors_json(NorRustEngine* engine, int32_t faction);
    int32_t norrust_get_carry_gold(NorRustEngine* engine, int32_t faction, int32_t gold_carry_percent, int32_t early_finish_bonus);
    int32_t norrust_place_veteran_unit(NorRustEngine* engine, int32_t unit_id, const char* def_id, int32_t faction, int32_t col, int32_t row, int32_t hp, int32_t xp, int32_t xp_needed, int32_t advancement_pending);
    void norrust_set_faction_gold(NorRustEngine* engine, int32_t faction, int32_t gold);

    // Terrain query
    char* norrust_get_unit_terrain_info(NorRustEngine* engine, int32_t unit_id, int32_t col, int32_t row);

    // Combat preview
    char* norrust_simulate_combat(NorRustEngine* engine, int32_t attacker_id, int32_t defender_id, int32_t attacker_col, int32_t attacker_row, int32_t num_sims);
]]

-- ── Load shared library ─────────────────────────────────────────────────────

local lib_path = os.getenv("NORRUST_LIB")
if not lib_path then
    local source = love.filesystem.getSource()
    lib_path = source .. "/../norrust_core/target/debug/libnorrust_core.so"
end
local lib = ffi.load(lib_path)

-- ── Helpers ─────────────────────────────────────────────────────────────────

--- Convert a C string pointer to a Lua string and free the original.
local function get_string(cstr)
    if cstr == nil then return "" end
    local s = ffi.string(cstr)
    lib.norrust_free_string(cstr)
    return s
end

-- ── Lifecycle ───────────────────────────────────────────────────────────────

--- Create a new engine instance with automatic garbage collection.
function M.new()
    local engine = lib.norrust_new()
    return ffi.gc(engine, lib.norrust_free)
end

-- ── Data loading ────────────────────────────────────────────────────────────

--- Return the engine core version string.
function M.get_core_version()
    return get_string(lib.norrust_get_core_version())
end

--- Load unit and terrain definitions from the given data directory.
function M.load_data(engine, data_path)
    return lib.norrust_load_data(engine, data_path) == 1
end

--- Return the max HP for a unit definition by its ID.
function M.get_unit_max_hp(engine, unit_id)
    return lib.norrust_get_unit_max_hp(engine, unit_id)
end

-- ── Game initialization ─────────────────────────────────────────────────────

--- Initialize a new game with the given board dimensions and RNG seed.
function M.create_game(engine, cols, rows, seed)
    return lib.norrust_create_game(engine, cols, rows, seed) == 1
end

--- Set the terrain type at a hex coordinate.
function M.set_terrain_at(engine, col, row, terrain_id)
    lib.norrust_set_terrain_at(engine, col, row, terrain_id)
end

--- Procedurally generate terrain for the current board using the given seed.
function M.generate_map(engine, seed)
    return lib.norrust_generate_map(engine, seed) == 1
end

--- Load a board layout from a TOML file with the given RNG seed.
function M.load_board(engine, board_path, seed)
    return lib.norrust_load_board(engine, board_path, seed) == 1
end

--- Load unit placements from a TOML file onto the current board.
function M.load_units(engine, units_path)
    return lib.norrust_load_units(engine, units_path) == 1
end

--- Return the terrain ID string at a hex coordinate.
function M.get_terrain_at(engine, col, row)
    return get_string(lib.norrust_get_terrain_at(engine, col, row))
end

-- ── Unit management ─────────────────────────────────────────────────────────

--- Place a unit on the board at the given hex coordinate.
function M.place_unit_at(engine, unit_id, def_id, hp, faction, col, row)
    lib.norrust_place_unit_at(engine, unit_id, def_id, hp, faction, col, row)
end

--- Remove the unit at a hex coordinate, returning true on success.
function M.remove_unit_at(engine, col, row)
    return lib.norrust_remove_unit_at(engine, col, row) == 1
end

--- Return the recruitment gold cost for a unit definition.
function M.get_unit_cost(engine, def_id)
    return lib.norrust_get_unit_cost(engine, def_id)
end

--- Return the level of a unit definition.
function M.get_unit_level(engine, def_id)
    return lib.norrust_get_unit_level(engine, def_id)
end

-- ── Recruitment ─────────────────────────────────────────────────────────────

--- Recruit a new unit at the given hex, deducting gold from the active faction.
function M.recruit_unit_at(engine, unit_id, def_id, col, row)
    return lib.norrust_recruit_unit_at(engine, unit_id, def_id, col, row)
end

--- Run AI recruitment logic for a faction, returning the next available unit ID.
function M.ai_recruit(engine, faction_id, start_unit_id)
    return lib.norrust_ai_recruit(engine, faction_id, start_unit_id)
end

--- Set starting gold for both factions based on their leader costs.
function M.apply_starting_gold(engine, f0_id, f1_id)
    return lib.norrust_apply_starting_gold(engine, f0_id, f1_id) == 1
end

-- ── Faction queries ─────────────────────────────────────────────────────────

--- Load faction definitions from the given data directory.
function M.load_factions(engine, data_path)
    return lib.norrust_load_factions(engine, data_path) == 1
end

--- Return a list of all loaded faction ID strings.
function M.get_faction_ids(engine)
    local raw = get_string(lib.norrust_get_faction_ids_json(engine))
    return json_decode(raw) or {}
end

--- Return the leader unit def_id for a faction.
function M.get_faction_leader(engine, faction_id)
    return get_string(lib.norrust_get_faction_leader(engine, faction_id))
end

--- Return the list of recruitable unit def_ids for a faction up to max_level.
function M.get_faction_recruits(engine, faction_id, max_level)
    local raw = get_string(lib.norrust_get_faction_recruits_json(engine, faction_id, max_level))
    return json_decode(raw) or {}
end

-- ── Game state queries ──────────────────────────────────────────────────────

--- Return the index of the currently active faction (0 or 1).
function M.get_active_faction(engine)
    return lib.norrust_get_active_faction(engine)
end

--- Return the current turn number.
function M.get_turn(engine)
    return lib.norrust_get_turn(engine)
end

--- Return the current time-of-day name (e.g. "Dawn", "Dusk").
function M.get_time_of_day_name(engine)
    return get_string(lib.norrust_get_time_of_day_name(engine))
end

--- Return the winning faction index, or -1 if no winner yet.
function M.get_winner(engine)
    return lib.norrust_get_winner(engine)
end

--- Return the full game state as a decoded Lua table.
function M.get_state(engine)
    local raw = get_string(lib.norrust_get_state_json(engine))
    if raw == "" then return {} end
    return json_decode(raw) or {}
end

--- Set the objective hex for win-condition evaluation.
function M.set_objective_hex(engine, col, row)
    lib.norrust_set_objective_hex(engine, col, row)
end

--- Set the maximum number of turns before the game ends.
function M.set_max_turns(engine, max_turns)
    lib.norrust_set_max_turns(engine, max_turns)
end

-- ── Actions ─────────────────────────────────────────────────────────────────

--- Move a unit to the target hex coordinate.
function M.apply_move(engine, unit_id, col, row)
    return lib.norrust_apply_move(engine, unit_id, col, row)
end

--- Execute an attack from one unit against another.
function M.apply_attack(engine, attacker_id, defender_id)
    return lib.norrust_apply_attack(engine, attacker_id, defender_id)
end

--- Advance a unit into the hex vacated by a defeated defender.
function M.apply_advance(engine, unit_id)
    return lib.norrust_apply_advance(engine, unit_id)
end

--- End the current faction's turn and advance to the next.
function M.end_turn(engine)
    return lib.norrust_end_turn(engine)
end

--- Apply a game action from a JSON-encoded string.
function M.apply_action_json(engine, json_str)
    return lib.norrust_apply_action_json(engine, json_str)
end

-- ── Pathfinding ─────────────────────────────────────────────────────────────

--- Return the list of {col, row} hexes reachable by the given unit.
function M.get_reachable_hexes(engine, unit_id)
    local out_len = ffi.new("int32_t[1]")
    local arr = lib.norrust_get_reachable_hexes(engine, unit_id, out_len)
    local len = out_len[0]
    local result = {}
    if arr ~= nil and len > 0 then
        for i = 0, len - 1, 2 do
            result[#result + 1] = {col = arr[i], row = arr[i + 1]}
        end
        lib.norrust_free_int_array(arr, len)
    end
    return result
end

--- Find shortest path from unit's position to destination. Returns {col, row} table or empty.
function M.find_path(engine, unit_id, dest_col, dest_row)
    local out_len = ffi.new("int32_t[1]")
    local arr = lib.norrust_find_path(engine, unit_id, dest_col, dest_row, out_len)
    local len = out_len[0]
    local result = {}
    if arr ~= nil and len > 0 then
        for i = 0, len - 1, 2 do
            result[#result + 1] = {col = arr[i], row = arr[i + 1]}
        end
        lib.norrust_free_int_array(arr, len)
    end
    return result
end

-- ── AI ──────────────────────────────────────────────────────────────────────

--- Run the AI opponent's full turn for the given faction.
function M.ai_take_turn(engine, faction)
    lib.norrust_ai_take_turn(engine, faction)
end

-- ── Trigger zones ──────────────────────────────────────────────────────────

--- Return the next available unit ID for placement.
function M.get_next_unit_id(engine)
    return lib.norrust_get_next_unit_id(engine)
end

-- ── Campaign ──────────────────────────────────────────────────────────────

--- Load a campaign definition from a TOML file, returning it as a Lua table.
function M.load_campaign(engine, path)
    local raw = get_string(lib.norrust_load_campaign(engine, path))
    if raw == "" then return nil end
    return json_decode(raw)
end

--- Return surviving units for a faction as a list of unit tables.
function M.get_survivors(engine, faction)
    local raw = get_string(lib.norrust_get_survivors_json(engine, faction))
    return json_decode(raw) or {}
end

--- Calculate gold carried over between campaign scenarios.
function M.get_carry_gold(engine, faction, gold_carry_percent, early_finish_bonus)
    return lib.norrust_get_carry_gold(engine, faction, gold_carry_percent, early_finish_bonus)
end

--- Place a veteran unit with preserved XP and advancement state from a prior scenario.
function M.place_veteran_unit(engine, unit_id, def_id, faction, col, row, hp, xp, xp_needed, advancement_pending)
    return lib.norrust_place_veteran_unit(engine, unit_id, def_id, faction, col, row, hp, xp, xp_needed, advancement_pending and 1 or 0)
end

--- Set the gold amount for a faction.
function M.set_faction_gold(engine, faction, gold)
    lib.norrust_set_faction_gold(engine, faction, gold)
end

-- ── Terrain query ─────────────────────────────────────────────────────────

--- Return terrain defense/movement info for a unit at a hex, as a Lua table.
function M.get_unit_terrain_info(engine, unit_id, col, row)
    local raw = get_string(lib.norrust_get_unit_terrain_info(engine, unit_id, col, row))
    if raw == "" then return nil end
    return json_decode(raw)
end

-- ── Combat preview ──────────────────────────────────────────────────────────

--- Run a Monte Carlo combat simulation and return predicted outcomes as a Lua table.
function M.simulate_combat(engine, attacker_id, defender_id, attacker_col, attacker_row, num_sims)
    local raw = get_string(lib.norrust_simulate_combat(engine, attacker_id, defender_id, attacker_col, attacker_row, num_sims or 100))
    if raw == "" then return nil end
    return json_decode(raw)
end

--- Manually free an engine instance (normally handled by GC).
function M.free(engine)
    lib.norrust_free(engine)
end

return M
