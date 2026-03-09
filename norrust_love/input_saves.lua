-- norrust_love/input_saves.lua — Save list screen input handlers
-- Split from input.lua. Receives context references via init().

local M = {}

-- Context references (set by init)
local vars, scn, campaign
local sound
local game_data, mods
local MODES
local int
local center_camera, clear_selection

-- Forward reference for restore_from_save
local restore_from_save

function M.init(ctx)
    vars = ctx.vars
    scn = ctx.scn
    campaign = ctx.campaign
    sound = ctx.sound
    game_data = ctx.game_data
    mods = ctx.mods
    MODES = ctx.MODES
    int = ctx.int
    center_camera = ctx.center_camera
    clear_selection = ctx.clear_selection
end

--- Set the restore_from_save callback (called by input.lua after defining it).
function M.set_restore(fn)
    restore_from_save = fn
end

function M.keypressed(key)
    local saves = game_data.save_list or {}

    -- Rename mode intercepts keys
    if game_data.save_renaming then
        if key == "return" or key == "kpenter" then
            local selected = saves[game_data.save_idx]
            if selected then
                mods.save.update_display_name(selected.filepath, game_data.save_rename_text)
                game_data.save_list = mods.save.list_saves()
            end
            game_data.save_renaming = false
        elseif key == "escape" then
            game_data.save_renaming = false
        elseif key == "backspace" then
            local t = game_data.save_rename_text
            if #t > 0 then
                -- Remove last byte (ASCII-safe; UTF-8 multi-byte unlikely in save names)
                game_data.save_rename_text = t:sub(1, #t - 1)
            end
        end
        return
    end

    if key == "escape" then
        vars.game_mode = MODES.PICK_SCENARIO
    elseif key == "up" then
        if game_data.save_idx > 1 then
            game_data.save_idx = game_data.save_idx - 1
        end
    elseif key == "down" then
        if game_data.save_idx < #saves then
            game_data.save_idx = game_data.save_idx + 1
        end
    elseif key == "return" and #saves > 0 then
        local selected = saves[game_data.save_idx]
        if selected then
            local data = mods.save.load_save(vars.engine, mods.norrust, selected.filepath, center_camera)
            if data then
                restore_from_save(data)
                vars.status_message = "Loaded: " .. selected.filepath
            else
                vars.status_message = "Load failed!"
            end
            vars.status_timer = 3.0
        end
    elseif key == "d" and #saves > 0 then
        local selected = saves[game_data.save_idx]
        if selected then
            mods.save.delete_save(selected.filepath)
            game_data.save_list = mods.save.list_saves()
            if game_data.save_idx > #game_data.save_list then
                game_data.save_idx = math.max(1, #game_data.save_list)
            end
        end
    elseif key == "r" and #saves > 0 then
        local selected = saves[game_data.save_idx]
        if selected then
            game_data.save_renaming = true
            game_data.save_rename_skip = true
            game_data.save_rename_text = selected.display_name or ""
        end
    end
end

return M
