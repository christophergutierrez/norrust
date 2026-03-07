-- roster.lua — Persistent unit identity and campaign roster tracking
-- Units get UUIDs that persist across scenarios; roster tracks alive/dead status.

local roster = {}

-- ── UUID generation ──────────────────────────────────────────────────────────

local uuid_seeded = false

--- Generate an 8-character hex UUID string.
function roster.generate_uuid()
    if not uuid_seeded then
        math.randomseed(os.time() + math.floor(os.clock() * 1000))
        uuid_seeded = true
    end
    local chars = {}
    for i = 1, 8 do
        chars[i] = string.format("%x", math.random(0, 15))
    end
    return table.concat(chars)
end

-- ── Roster CRUD ──────────────────────────────────────────────────────────────

--- Create a new empty roster.
--- entries: UUID → {uuid, def_id, hp, max_hp, xp, xp_needed, advancement_pending, status}
--- id_map: engine_id (number) → UUID for current scenario
function roster.new()
    return {entries = {}, id_map = {}}
end

--- Add a unit to the roster with a fresh UUID. Maps engine_id → UUID.
--- Returns the generated UUID.
function roster.add(r, def_id, engine_id, hp, max_hp, xp, xp_needed, advancement_pending)
    local uuid = roster.generate_uuid()
    r.entries[uuid] = {
        uuid = uuid,
        def_id = def_id,
        hp = hp,
        max_hp = max_hp,
        xp = xp,
        xp_needed = xp_needed,
        advancement_pending = advancement_pending or false,
        status = "alive",
    }
    if engine_id then
        r.id_map[engine_id] = uuid
    end
    return uuid
end

--- Map an engine_id to an existing UUID (e.g. after placing veteran in new scenario).
function roster.map_id(r, engine_id, uuid)
    r.id_map[engine_id] = uuid
end

--- Sync roster entries from engine state.
--- Updates hp/xp/advancement for mapped units; marks missing units as dead.
function roster.sync_from_engine(r, state)
    -- Build lookup of living engine units by id
    local engine_units = {}
    for _, u in ipairs(state.units or {}) do
        engine_units[math.floor(u.id)] = u
    end

    -- Update mapped entries
    for engine_id, uuid in pairs(r.id_map) do
        local entry = r.entries[uuid]
        if entry then
            local u = engine_units[engine_id]
            if u then
                entry.hp = math.floor(u.hp)
                entry.max_hp = math.floor(u.max_hp)
                entry.xp = math.floor(u.xp)
                entry.xp_needed = math.floor(u.xp_needed)
                entry.advancement_pending = u.advancement_pending or false
                entry.def_id = u.def_id
            else
                entry.status = "dead"
            end
        end
    end
end

--- Return an array of living roster entries.
function roster.get_living(r)
    local result = {}
    for _, entry in pairs(r.entries) do
        if entry.status == "alive" then
            result[#result + 1] = entry
        end
    end
    return result
end

--- Clear engine_id → UUID mapping (called between scenarios).
function roster.clear_id_map(r)
    r.id_map = {}
end

--- Convert roster to array for TOML serialization.
function roster.to_save_array(r)
    local arr = {}
    for _, entry in pairs(r.entries) do
        arr[#arr + 1] = {
            uuid = entry.uuid,
            def_id = entry.def_id,
            hp = entry.hp,
            max_hp = entry.max_hp,
            xp = entry.xp,
            xp_needed = entry.xp_needed,
            advancement_pending = entry.advancement_pending,
            status = entry.status,
        }
    end
    return arr
end

--- Build a roster from a saved array (from TOML load).
function roster.from_save_array(arr)
    local r = roster.new()
    for _, entry in ipairs(arr) do
        r.entries[entry.uuid] = {
            uuid = entry.uuid,
            def_id = entry.def_id,
            hp = math.floor(entry.hp),
            max_hp = math.floor(entry.max_hp),
            xp = math.floor(entry.xp),
            xp_needed = math.floor(entry.xp_needed),
            advancement_pending = entry.advancement_pending or false,
            status = entry.status or "alive",
        }
    end
    return r
end

return roster
