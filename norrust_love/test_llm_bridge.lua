#!/usr/bin/env luajit
-- Bridge smoke test. Run with NORRUST_LIB pointing at libnorrust_core.so.
package.path = "norrust_love/?.lua;" .. package.path

local norrust = require("norrust")
assert(norrust.get_tod_phase, "ToD phase wrapper missing")
assert(norrust.legal_moves, "legal move wrapper missing")
assert(norrust.legal_targets, "legal target wrapper missing")
assert(norrust.place_veteran_unit_json, "JSON veteran wrapper missing")

local engine = norrust.new()
assert(engine ~= nil, "engine allocation failed")
assert(norrust.create_game(engine, 4, 4, 42), "game creation failed")
assert(norrust.get_tod_phase(engine) == 0, "turn 1 must be Dawn phase 0")
norrust.free(engine)
print("LLM bridge smoke: OK")
