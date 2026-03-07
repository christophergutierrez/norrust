#!/usr/bin/env luajit
-- test_roster.lua — Quick standalone test for roster logic
-- Run: luajit norrust_love/test_roster.lua

package.path = "norrust_love/?.lua;" .. package.path

local roster_mod = require("roster")

local function assert_eq(a, b, msg)
    if a ~= b then
        error(string.format("FAIL: %s — expected %s, got %s", msg, tostring(b), tostring(a)), 2)
    end
end

local pass = 0
local function ok(msg) pass = pass + 1; print("  OK: " .. msg) end

-- ── Test 1: UUID generation ─────────────────────────────────────────────────
print("Test 1: UUID generation")
local u1 = roster_mod.generate_uuid()
local u2 = roster_mod.generate_uuid()
assert_eq(#u1, 8, "uuid length")
assert_eq(#u2, 8, "uuid length")
assert(u1 ~= u2, "uuids should be unique")
ok("UUIDs are 8 chars and unique")

-- ── Test 2: Add + get_living ─────────────────────────────────────────────────
print("Test 2: Add + get_living")
local r = roster_mod.new()
local uuid1 = roster_mod.add(r, "fighter", 1, 30, 30, 0, 40, false)
local uuid2 = roster_mod.add(r, "archer", 2, 20, 20, 5, 32, false)
local uuid3 = roster_mod.add(r, "mage", 3, 24, 24, 0, 48, false)

assert_eq(r.entries[uuid1].def_id, "fighter", "entry 1 def_id")
assert_eq(r.entries[uuid2].def_id, "archer", "entry 2 def_id")
assert_eq(r.id_map[1], uuid1, "id_map[1]")
assert_eq(r.id_map[2], uuid2, "id_map[2]")

local living = roster_mod.get_living(r)
assert_eq(#living, 3, "3 living")
ok("3 units added, all living")

-- ── Test 3: sync_from_engine — unit dies ─────────────────────────────────────
print("Test 3: sync_from_engine — unit dies")
-- Simulate engine state where unit 2 (archer) is dead
local fake_state = {
    units = {
        {id = 1, def_id = "fighter", faction = 0, hp = 25, max_hp = 30, xp = 10, xp_needed = 40, advancement_pending = false},
        {id = 3, def_id = "mage", faction = 0, hp = 18, max_hp = 24, xp = 8, xp_needed = 48, advancement_pending = false},
    }
}
roster_mod.sync_from_engine(r, fake_state)

assert_eq(r.entries[uuid1].hp, 25, "fighter hp updated")
assert_eq(r.entries[uuid1].xp, 10, "fighter xp updated")
assert_eq(r.entries[uuid2].status, "dead", "archer should be dead")
assert_eq(r.entries[uuid3].hp, 18, "mage hp updated")

living = roster_mod.get_living(r)
assert_eq(#living, 2, "2 living after death")
ok("sync updates stats, marks dead unit")

-- ── Test 4: clear_id_map + map_id ───────────────────────────────────────────
print("Test 4: clear_id_map + map_id")
roster_mod.clear_id_map(r)
assert_eq(next(r.id_map), nil, "id_map cleared")

-- Re-map with new engine IDs (like a new scenario)
roster_mod.map_id(r, 10, uuid1)
roster_mod.map_id(r, 11, uuid3)
assert_eq(r.id_map[10], uuid1, "remapped fighter")
assert_eq(r.id_map[11], uuid3, "remapped mage")
ok("id_map cleared and remapped")

-- ── Test 5: to_save_array + from_save_array ─────────────────────────────────
print("Test 5: to_save_array + from_save_array")
local arr = roster_mod.to_save_array(r)
assert_eq(#arr, 3, "save array has 3 entries (alive + dead)")

local r2 = roster_mod.from_save_array(arr)
local living2 = roster_mod.get_living(r2)
assert_eq(#living2, 2, "restored roster has 2 living")

-- Verify dead entry preserved
local found_dead = false
for _, e in pairs(r2.entries) do
    if e.status == "dead" then found_dead = true end
end
assert(found_dead, "dead entry preserved in round-trip")
ok("save/load round-trip preserves all entries")

-- ── Test 6: Simulate full campaign flow ─────────────────────────────────────
print("Test 6: Full campaign flow simulation")
local cr = roster_mod.new()

-- First scenario: 5 preset units
for i = 1, 5 do
    roster_mod.add(cr, "unit_" .. i, i, 30, 30, 0, 40, false)
end
assert_eq(#roster_mod.get_living(cr), 5, "5 preset units")

-- Battle happens: units 2,4 die, others take damage
local end_state = {
    units = {
        {id = 1, def_id = "unit_1", faction = 0, hp = 20, max_hp = 30, xp = 15, xp_needed = 40, advancement_pending = false},
        {id = 3, def_id = "unit_3", faction = 0, hp = 10, max_hp = 30, xp = 25, xp_needed = 40, advancement_pending = false},
        {id = 5, def_id = "unit_5", faction = 0, hp = 28, max_hp = 30, xp = 8, xp_needed = 40, advancement_pending = false},
    }
}
roster_mod.sync_from_engine(cr, end_state)
local survivors = roster_mod.get_living(cr)
assert_eq(#survivors, 3, "3 survivors after battle")

-- Build campaign_veterans from living roster (like victory handler)
local campaign_veterans = {}
for _, entry in ipairs(survivors) do
    campaign_veterans[#campaign_veterans + 1] = {
        def_id = entry.def_id,
        hp = entry.hp,
        xp = entry.xp,
        xp_needed = entry.xp_needed,
        advancement_pending = entry.advancement_pending,
    }
end
assert_eq(#campaign_veterans, 3, "3 campaign veterans derived")

-- New scenario: clear id_map, map new engine IDs
roster_mod.clear_id_map(cr)
for i, vet in ipairs(survivors) do
    local new_engine_id = 100 + i
    roster_mod.map_id(cr, new_engine_id, vet.uuid)
end

-- Verify mappings work for next sync
assert(cr.id_map[101] ~= nil, "new mapping exists")
assert(cr.id_map[102] ~= nil, "new mapping exists")
assert(cr.id_map[103] ~= nil, "new mapping exists")
ok("Full campaign flow: 5→battle→3 survivors→remap works")

-- ── Summary ─────────────────────────────────────────────────────────────────
print(string.format("\n%d/%d tests passed", pass, 6))
