-- norrust_love/state.lua — Pure state declarations for the game
-- All mutable state tables grouped here. No logic, no require() calls.

-- Mutable scalars grouped for module sharing (input.lua reads/writes these)
local vars = {
    engine = nil,
    game_mode = -1,  -- MODES.PICK_SCENARIO; set properly in love.load
    game_over = false,
    winner_faction = -1,
    status_message = nil,
    status_timer = 0,
    sel_faction_idx = 0,
}

local combat_state = {preview = nil, target = -1}
local ai = {vs_ai = false, delay = 0.5, timer = 0}
local shared = {agent = nil, agent_mod = nil, show_help = false, buttons = {}}

local terrain_tiles = {}
local unit_sprites = {}
local tile_color_cache = {}
local FACTION_COLORS = {[0] = {0.25, 0.42, 0.88}, [1] = {0.80, 0.12, 0.12}}
local unit_anims = {}
local dying_units = {}
local pending_anims = {}
local fonts = {}

-- Context tables (grouped to reduce LuaJIT upvalue pressure)

local scn = {
    path = "", board = "", units = "", preset = false,
    COLS = 8, ROWS = 5,
}

local sel = {
    unit_id = -1, reachable_cells = {}, reachable_set = {},
    recruit_idx = 0, recruit_mode = false, recruit_error = "",
    recruit_state = {veterans = {}}, recruit_palette = {},
    inspect_id = -1, inspect_terrain = nil,
}

local ghost = {col = nil, row = nil, unit_id = -1, attackable = {}, path = {}}

local campaign = {
    path = "", active = false, data = nil,
    index = 0, veterans = {}, gold = 0, roster = nil,
    deploy = {active = false, veterans = {}, slots = 0, selected = 1},
}

local dlg = {active = {}, history = {}, show_history = false, scroll = 0}

local fog = {seen = {}, visible = {}, enabled = true}

local camera = {
    origin_x = 0, origin_y = 0,
    offset_x = 0, offset_y = 0,
    min_x = 0, min_y = 0, max_x = 0, max_y = 0,
    drag_active = false,
    drag_start_x = 0, drag_start_y = 0,
    drag_cam_x = 0, drag_cam_y = 0,
    target_x = 0, target_y = 0,
    lerping = false, zoom = 1.0,
    ZOOM_MIN = 0.15, ZOOM_MAX = 3.0, ZOOM_STEP = 0.1,
    PAN_SPEED = 500, LERP_SPEED = 8.0,
}

return {
    vars = vars,
    combat_state = combat_state,
    ai = ai,
    shared = shared,
    terrain_tiles = terrain_tiles,
    unit_sprites = unit_sprites,
    tile_color_cache = tile_color_cache,
    FACTION_COLORS = FACTION_COLORS,
    unit_anims = unit_anims,
    dying_units = dying_units,
    pending_anims = pending_anims,
    fonts = fonts,
    scn = scn,
    sel = sel,
    ghost = ghost,
    campaign = campaign,
    dlg = dlg,
    fog = fog,
    camera = camera,
}
