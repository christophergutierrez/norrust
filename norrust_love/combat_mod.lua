-- norrust_love/combat_mod.lua — Combat and animation operations module
-- Handles combat animations, attack execution, and per-frame animation ticking.

local unit_anims, unit_sprites, anim_module, pending_anims
local dying_units, norrust, vars, hex, sound
local combat_state, ghost, sel, events, int

local M = {}

function M.init(deps)
    unit_anims = deps.unit_anims
    unit_sprites = deps.unit_sprites
    anim_module = deps.anim_module
    pending_anims = deps.pending_anims
    dying_units = deps.dying_units
    norrust = deps.norrust
    vars = deps.vars
    hex = deps.hex
    sound = deps.sound
    combat_state = deps.combat_state
    ghost = deps.ghost
    sel = deps.sel
    events = deps.events
    int = deps.int
end

-- ── Animation helpers ─────────────────────────────────────────────────────

local function play_combat_anim(uid, anim_name, duration)
    local anim_state = unit_anims[uid]
    if not anim_state then return end
    local key = anim_state.def_id and anim_state.def_id:lower():gsub(" ", "_")
    local entry = key and unit_sprites[key]
    if not entry or not entry.anims or not entry.anims[anim_name] then return end
    anim_module.play(anim_state, anim_name)
    if duration > 0 then
        pending_anims[#pending_anims + 1] = {
            uid = uid,
            end_time = love.timer.getTime() + duration,
            return_to = "idle",
        }
    end
end

local function trigger_attack_anims(attacker_id, defender_id, is_ranged)
    local atk_anim = is_ranged and "attack-ranged" or "attack-melee"
    play_combat_anim(attacker_id, atk_anim, 0.75)
    play_combat_anim(defender_id, "defend", 0.5)
end

local function trigger_death_anim(uid)
    -- Death is now derived at render time (tilt + fade from idle)
    -- Just ensure anim state is on idle; draw_board handles the visual
    local anim_state = unit_anims[uid]
    if anim_state then
        anim_module.play(anim_state, "idle")
    end
end

local function apply_attack_with_anims(attacker_id, defender_id, is_ranged)
    local pre_state = norrust.get_state(vars.engine)
    local def_info = nil
    for _, unit in ipairs(pre_state.units or {}) do
        if int(unit.id) == defender_id then
            def_info = {def_id = unit.def_id, col = int(unit.col), row = int(unit.row), faction = int(unit.faction)}
            break
        end
    end

    trigger_attack_anims(attacker_id, defender_id, is_ranged)
    norrust.apply_attack(vars.engine, attacker_id, defender_id)
    local new_state = norrust.get_state(vars.engine)
    local defender_alive = false
    for _, unit in ipairs(new_state.units or {}) do
        if int(unit.id) == defender_id then
            defender_alive = true
            break
        end
    end
    if not defender_alive then
        trigger_death_anim(defender_id)
        if def_info then
            dying_units[defender_id] = {
                def_id = def_info.def_id, col = def_info.col, row = def_info.row,
                faction = def_info.faction, timer = 1.0,
            }
        end
        sound.play("death")
    else
        sound.play("hit")
    end
end

-- ── Exported combat functions ─────────────────────────────────────────────

function M.is_ranged_attack()
    if not combat_state.preview or combat_state.target < 0 then return false end
    local state = norrust.get_state(vars.engine)
    local atk_col, atk_row, def_col, def_row
    local atk_id = ghost.col ~= nil and ghost.unit_id or sel.unit_id
    if ghost.col ~= nil then
        atk_col, atk_row = ghost.col, ghost.row
    end
    for _, unit in ipairs(state.units or {}) do
        local uid = int(unit.id)
        if uid == atk_id and not atk_col then
            atk_col, atk_row = int(unit.col), int(unit.row)
        end
        if uid == combat_state.target then
            def_col, def_row = int(unit.col), int(unit.row)
        end
    end
    if atk_col and def_col then
        return hex.distance(atk_col, atk_row, def_col, def_row) > 1
    end
    return false
end

function M.execute_attack(attacker_id, defender_id, is_ranged, on_done)
    -- Check if defender is a leader — fire leader_attacked trigger
    local pre_state = norrust.get_state(vars.engine)
    for _, unit in ipairs(pre_state.units or {}) do
        if int(unit.id) == defender_id then
            for _, ab in ipairs(unit.abilities or {}) do
                if ab == "leader" then
                    events.emit("dialogue", {trigger = "leader_attacked"})
                    break
                end
            end
            break
        end
    end

    if is_ranged then
        apply_attack_with_anims(attacker_id, defender_id, true)
        if on_done then on_done() end
        return
    end

    -- Melee: look up positions for slide
    local state = norrust.get_state(vars.engine)
    local ax, ay, dx, dy
    for _, unit in ipairs(state.units or {}) do
        local uid = int(unit.id)
        if uid == attacker_id then
            ax, ay = hex.to_pixel(int(unit.col), int(unit.row))
        elseif uid == defender_id then
            dx, dy = hex.to_pixel(int(unit.col), int(unit.row))
        end
    end

    if not ax or not dx then
        apply_attack_with_anims(attacker_id, defender_id, false)
        if on_done then on_done() end
        return
    end

    -- Slide 40% toward defender
    local mid_x = ax + (dx - ax) * 0.4
    local mid_y = ay + (dy - ay) * 0.4

    pending_anims.combat_slide = {
        uid = attacker_id,
        start_x = ax, start_y = ay,
        target_x = mid_x, target_y = mid_y,
        t = 0, speed = 6,
        phase = "approach",
        defender_id = defender_id,
        pause_remaining = nil,
        on_done = on_done,
    }
end

-- ── Animation tick (called from love.update) ──────────────────────────────

function M.update_anims(dt)
    -- Update unit animation frames
    for uid, anim_state in pairs(unit_anims) do
        local entry = nil
        if anim_state.def_id then
            entry = unit_sprites[anim_state.def_id:lower():gsub(" ", "_")]
        end
        if entry and entry.anims then
            anim_module.update(anim_state, entry.anims, dt)
        end
    end

    -- Return combat animations to idle when their duration expires
    local now = love.timer.getTime()
    local i = 1
    while i <= #pending_anims do
        local pa = pending_anims[i]
        if now >= pa.end_time then
            local anim_state = unit_anims[pa.uid]
            if anim_state then
                anim_module.play(anim_state, pa.return_to)
            end
            table.remove(pending_anims, i)
        else
            i = i + 1
        end
    end

    -- Tick down dying unit timers
    for uid, info in pairs(dying_units) do
        info.timer = info.timer - dt
        if info.timer <= 0 then
            dying_units[uid] = nil
            unit_anims[uid] = nil
        end
    end

    -- Movement interpolation animation
    local ma = pending_anims.move
    if ma then
        ma.t = ma.t + ma.speed * dt
        while ma and ma.t >= 1.0 do
            ma.seg = ma.seg + 1
            ma.t = ma.t - 1.0
            if ma.seg >= #ma.path then
                local cb = ma.on_complete
                pending_anims.move = nil
                ma = nil
                if cb then cb() end
            end
        end
    end

    -- Combat slide animation (melee approach/return)
    local cs = pending_anims.combat_slide
    if cs then
        if cs.pause_remaining then
            cs.pause_remaining = cs.pause_remaining - dt
            if cs.pause_remaining <= 0 then
                cs.phase = "return"
                cs.t = 0
                cs.pause_remaining = nil
                cs.target_x, cs.start_x = cs.start_x, cs.target_x
                cs.target_y, cs.start_y = cs.start_y, cs.target_y
            end
        else
            cs.t = cs.t + cs.speed * dt
            if cs.t >= 1.0 then
                cs.t = 1.0
                if cs.phase == "approach" then
                    apply_attack_with_anims(cs.uid, cs.defender_id, false)
                    cs.pause_remaining = 0.3
                elseif cs.phase == "return" then
                    local cb = cs.on_done
                    pending_anims.combat_slide = nil
                    if cb then cb() end
                end
            end
        end
    end
end

return M
