-- norrust_love/input_deploy.lua — Veteran deployment screen input handlers
-- Split from input.lua. Receives context references via init().

local M = {}

-- Context references (set by init)
local vars, scn, campaign
local mods
local MODES
local int
local build_unit_pos_map
local campaign_client

function M.init(ctx)
    vars = ctx.vars
    scn = ctx.scn
    campaign = ctx.campaign
    mods = ctx.mods
    MODES = ctx.MODES
    int = ctx.int
    build_unit_pos_map = ctx.build_unit_pos_map
    campaign_client = ctx.campaign_client
end

function M.keypressed(key)
    local deploy = campaign.deploy
    local dvets = deploy.veterans or {}

    if key == "up" then
        if deploy.selected > 1 then deploy.selected = deploy.selected - 1 end
    elseif key == "down" then
        if deploy.selected < #dvets then deploy.selected = deploy.selected + 1 end
    elseif key == "space" then
        local dv = dvets[deploy.selected]
        if dv then
            if dv.deployed then
                dv.deployed = false
            else
                -- Count currently deployed
                local count = 0
                for _, v in ipairs(dvets) do
                    if v.deployed then count = count + 1 end
                end
                if count < deploy.slots then
                    dv.deployed = true
                else
                    vars.status_message = "All " .. deploy.slots .. " slots full"
                    vars.status_timer = 2.0
                end
            end
        end
    elseif key == "return" or key == "kpenter" then
        -- Build campaign ctx and commit
        local ctx = {
            norrust = mods.norrust, engine = vars.engine, int = int,
            hex = mods.hex, scenarios_path = scn.path,
            campaign_veterans = campaign.veterans,
            campaign_roster = campaign.roster, roster_mod = mods.roster_mod,
            campaign_deploy = campaign.deploy,
            build_unit_pos_map = build_unit_pos_map,
            PLAYING = MODES.PLAYING,
        }
        campaign_client.commit_deployment(ctx)
        vars.game_mode = ctx.game_mode
        mods.events.emit("scenario_loaded", {board = scn.board})
    elseif key == "escape" then
        -- Deploy all (up to slot limit)
        local count = 0
        for _, dv in ipairs(dvets) do
            if count < deploy.slots then
                dv.deployed = true
                count = count + 1
            else
                dv.deployed = false
            end
        end
        local ctx = {
            norrust = mods.norrust, engine = vars.engine, int = int,
            hex = mods.hex, scenarios_path = scn.path,
            campaign_veterans = campaign.veterans,
            campaign_roster = campaign.roster, roster_mod = mods.roster_mod,
            campaign_deploy = campaign.deploy,
            build_unit_pos_map = build_unit_pos_map,
            PLAYING = MODES.PLAYING,
        }
        campaign_client.commit_deployment(ctx)
        vars.game_mode = ctx.game_mode
        mods.events.emit("scenario_loaded", {board = scn.board})
    else
        -- Number keys 1-9 toggle deploy
        local num = tonumber(key)
        if num and num >= 1 and num <= #dvets then
            local dv = dvets[num]
            if dv.deployed then
                dv.deployed = false
            else
                local count = 0
                for _, v in ipairs(dvets) do
                    if v.deployed then count = count + 1 end
                end
                if count < deploy.slots then
                    dv.deployed = true
                else
                    vars.status_message = "All " .. deploy.slots .. " slots full"
                    vars.status_timer = 2.0
                end
            end
        end
    end
end

return M
