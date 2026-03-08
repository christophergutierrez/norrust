-- norrust_love/camera_mod.lua — Camera operations module
-- Handles panning, zoom centering, lerp, and offset clamping.

local camera, hex, scn, get_viewport, clamp

local M = {}

function M.init(deps)
    camera = deps.camera
    hex = deps.hex
    scn = deps.scn
    get_viewport = deps.get_viewport
    clamp = deps.clamp
end

function M.apply_offset()
    camera.offset_x = clamp(camera.offset_x, camera.min_x, camera.max_x)
    camera.offset_y = clamp(camera.offset_y, camera.min_y, camera.max_y)
end

function M.center(reset)
    local tlx, tly = hex.to_pixel(0, 0)
    local brx, bry = hex.to_pixel(scn.COLS - 1, scn.ROWS - 1)
    local vp_w, vp_h = get_viewport()
    local usable_w = vp_w - 200
    local center_px = (tlx + brx) / 2
    local center_py = (tly + bry) / 2

    if reset then
        local board_w = (brx - tlx) + hex.RADIUS * 2
        local board_h = (bry - tly) + hex.RADIUS * 2
        local fit_zoom = math.min(usable_w / board_w, vp_h / board_h)
        camera.zoom = clamp(fit_zoom, camera.ZOOM_MIN, camera.ZOOM_MAX)
        camera.offset_x, camera.offset_y = 0, 0
        camera.lerping = false
    end

    camera.origin_x = usable_w / 2 - camera.zoom * center_px
    camera.origin_y = vp_h / 2 - camera.zoom * center_py

    local eff_w = usable_w / camera.zoom
    local eff_h = vp_h / camera.zoom
    local board_half_w = (brx - tlx) / 2 + hex.RADIUS
    local board_half_h = (bry - tly) / 2 + hex.RADIUS
    local pan_range_x = math.max(board_half_w - eff_w / 2 + hex.RADIUS, 0)
    local pan_range_y = math.max(board_half_h - eff_h / 2 + hex.RADIUS, 0)
    camera.min_x, camera.min_y = -pan_range_x, -pan_range_y
    camera.max_x, camera.max_y = pan_range_x, pan_range_y
    M.apply_offset()
end

function M.update(dt)
    -- Arrow key panning
    local pan_x, pan_y = 0, 0
    if love.keyboard.isDown("left") then pan_x = pan_x + 1 end
    if love.keyboard.isDown("right") then pan_x = pan_x - 1 end
    if love.keyboard.isDown("up") then pan_y = pan_y + 1 end
    if love.keyboard.isDown("down") then pan_y = pan_y - 1 end

    if pan_x ~= 0 or pan_y ~= 0 then
        camera.lerping = false
        local len = math.sqrt(pan_x * pan_x + pan_y * pan_y)
        camera.offset_x = camera.offset_x + (pan_x / len) * camera.PAN_SPEED * dt
        camera.offset_y = camera.offset_y + (pan_y / len) * camera.PAN_SPEED * dt
        M.apply_offset()
        return
    end

    -- Camera lerp toward selection target
    if camera.lerping then
        local t = camera.LERP_SPEED * dt
        camera.offset_x = camera.offset_x + (camera.target_x - camera.offset_x) * t
        camera.offset_y = camera.offset_y + (camera.target_y - camera.offset_y) * t
        M.apply_offset()
        local dx = camera.offset_x - camera.target_x
        local dy = camera.offset_y - camera.target_y
        if math.sqrt(dx * dx + dy * dy) < 1.0 then
            camera.offset_x = camera.target_x
            camera.offset_y = camera.target_y
            M.apply_offset()
            camera.lerping = false
        end
    end
end

return M
