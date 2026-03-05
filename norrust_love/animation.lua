-- animation.lua — Animation state machine for unit sprites
-- Uses Love2D Quads for spritesheet frame selection (no external libs)

local animation = {}

--- Load all animation data for a unit from parsed sprite.toml data.
-- @param base_path string: unit asset directory (e.g. "assets/units/spearman")
-- @param toml_data table: parsed sprite.toml
-- @return table: anim_data with per-state {img, quads, fps, loop}
function animation.load_unit_anims(base_path, toml_data)
    local anims = {}

    -- Helper: load one animation state from a toml section
    local function load_anim(key, section, loop)
        if not section or not section.file then return end
        local path = base_path .. "/" .. section.file
        local info = love.filesystem.getInfo(path)
        if not info then return end

        local ok, img = pcall(love.graphics.newImage, path)
        if not ok then return end

        local fw = section.frame_width or 256
        local fh = section.frame_height or 256
        local frames = section.frames or 1
        local fps = section.fps or 4
        local iw, ih = img:getWidth(), img:getHeight()

        local quads = {}
        for i = 0, frames - 1 do
            quads[i + 1] = love.graphics.newQuad(i * fw, 0, fw, fh, iw, ih)
        end

        anims[key] = {
            img = img,
            quads = quads,
            fps = fps,
            loop = loop,
            frame_width = fw,
            frame_height = fh,
            frames = frames,
        }
    end

    -- Load each animation state
    load_anim("idle", toml_data.idle, true)

    -- Attack animations: attacks.melee, attacks.ranged
    if toml_data.attacks then
        for attack_type, section in pairs(toml_data.attacks) do
            load_anim("attack-" .. attack_type, section, false)
        end
    end

    load_anim("defend", toml_data.defend, false)
    load_anim("death", toml_data.death, false)

    -- Portrait (not an animation, but load the image)
    if toml_data.portrait and toml_data.portrait.file then
        local portrait_path = base_path .. "/" .. toml_data.portrait.file
        local pinfo = love.filesystem.getInfo(portrait_path)
        if pinfo then
            local pok, pimg = pcall(love.graphics.newImage, portrait_path)
            if pok then
                anims.portrait = pimg
            end
        end
    end

    return anims
end

--- Create a new per-unit animation state.
-- @return table: {current, frame, timer, facing}
function animation.new_state()
    return {
        current = "idle",
        frame = 1,
        timer = 0,
        facing = "right",
    }
end

--- Update animation state (advance frame timer).
-- @param anim_state table: per-unit state from new_state()
-- @param anim_data table: loaded anims from load_unit_anims()
-- @param dt number: delta time in seconds
function animation.update(anim_state, anim_data, dt)
    local state_name = anim_state.current
    local anim = anim_data[state_name]
    if not anim then
        -- Fall back to idle if current state has no animation
        anim_state.current = "idle"
        anim = anim_data["idle"]
        if not anim then return end
    end

    anim_state.timer = anim_state.timer + dt
    local frame_duration = 1.0 / anim.fps

    if anim_state.timer >= frame_duration then
        anim_state.timer = anim_state.timer - frame_duration
        anim_state.frame = anim_state.frame + 1

        if anim_state.frame > anim.frames then
            if anim.loop then
                anim_state.frame = 1
            else
                anim_state.frame = anim.frames  -- hold last frame
            end
        end
    end
end

--- Transition to a new animation state.
-- @param anim_state table: per-unit state
-- @param anim_name string: state name (e.g. "idle", "attack-melee")
function animation.play(anim_state, anim_name)
    if anim_state.current ~= anim_name then
        anim_state.current = anim_name
        anim_state.frame = 1
        anim_state.timer = 0
    end
end

--- Get the current Image and Quad for drawing.
-- @param anim_state table: per-unit state
-- @param anim_data table: loaded anims
-- @return Image|nil, Quad|nil, number, number: img, quad, frame_width, frame_height
function animation.get_quad(anim_state, anim_data)
    local anim = anim_data[anim_state.current]
    if not anim then
        anim = anim_data["idle"]
        if not anim then return nil, nil, 0, 0 end
    end

    local frame = math.min(anim_state.frame, anim.frames)
    return anim.img, anim.quads[frame], anim.frame_width, anim.frame_height
end

--- Check if a one-shot animation has finished.
-- @param anim_state table: per-unit state
-- @param anim_data table: loaded anims
-- @return boolean
function animation.is_finished(anim_state, anim_data)
    local anim = anim_data[anim_state.current]
    if not anim then return true end
    if anim.loop then return false end
    return anim_state.frame >= anim.frames
end

return animation
