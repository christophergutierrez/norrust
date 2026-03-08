-- agent_server.lua — Non-blocking TCP server for external AI agents
-- Protocol: line-based (newline-delimited). Client sends command\n, server responds result\n.
--
-- Commands:
--   get_state        → full StateSnapshot JSON
--   get_faction      → active faction number (0 or 1)
--   check_winner     → winner faction (-1 if none)
--   ai_turn FACTION  → run AI for faction, respond "0"
--   {"action":...}   → ActionRequest JSON, respond result code

local socket = require("socket")

local agent_server = {}

--- Create a new TCP server on the given port.
--- Returns a server handle table, or nil on error.
function agent_server.new(port)
    local server, err = socket.bind("127.0.0.1", port)
    if not server then
        print("[AGENT] Failed to bind port " .. port .. ": " .. tostring(err))
        return nil
    end
    server:settimeout(0)
    local handle = {
        server = server,
        port = port,
        clients = {},   -- array of {sock=, buf=""}
    }
    print("[AGENT] Server listening on 127.0.0.1:" .. port)
    return handle
end

--- Process a single command line from a client.
--- Returns the response string (without trailing newline).
local command_handlers = {
    get_state = function(norrust, engine)
        local state_json = norrust.get_state_raw(engine)
        if not state_json or state_json == "" then return "{}" end
        return state_json
    end,
    get_faction = function(norrust, engine)
        local f = norrust.get_active_faction(engine)
        return tostring(f)
    end,
    check_winner = function(norrust, engine)
        local w = norrust.get_winner(engine)
        return tostring(w)
    end,
}

local function process_command(line, norrust, engine)
    local handler = command_handlers[line]
    if handler then
        return handler(norrust, engine)
    elseif line:sub(1, 8) == "ai_turn " then
        local faction = tonumber(line:sub(9))
        if faction then
            norrust.ai_take_turn(engine, faction)
            return "0"
        else
            return "-1"
        end
    elseif line:sub(1, 1) == "{" then
        local rc = norrust.apply_action_json(engine, line)
        return tostring(rc)
    else
        return "error: unknown command"
    end
end

--- Called from love.update. Accepts new connections, reads commands, sends responses.
function agent_server.update(handle, norrust, engine)
    if not handle then return end

    -- Accept new connections
    local client_sock = handle.server:accept()
    while client_sock do
        client_sock:settimeout(0)
        handle.clients[#handle.clients + 1] = {sock = client_sock, buf = ""}
        print("[AGENT] Client connected (" .. #handle.clients .. " total)")
        client_sock = handle.server:accept()
    end

    -- Process each client
    local i = 1
    while i <= #handle.clients do
        local c = handle.clients[i]
        local disconnected = false
        local data, err, partial = c.sock:receive("*l")

        if data then
            -- Full line received
            local response = process_command(data, norrust, engine)
            local _, send_err = c.sock:send(response .. "\n")
            if send_err then disconnected = true end
        elseif err == "closed" then
            disconnected = true
        elseif partial and partial ~= "" then
            -- Partial data (no newline yet) — buffer it
            c.buf = c.buf .. partial
            -- Check if buffer contains a complete line
            local nl = c.buf:find("\n")
            if nl then
                local line = c.buf:sub(1, nl - 1)
                c.buf = c.buf:sub(nl + 1)
                local response = process_command(line, norrust, engine)
                local _, send_err = c.sock:send(response .. "\n")
                if send_err then disconnected = true end
            end
        end

        if disconnected then
            print("[AGENT] Client disconnected (" .. (#handle.clients - 1) .. " remaining)")
            c.sock:close()
            table.remove(handle.clients, i)
        else
            i = i + 1
        end
    end
end

--- Stop the server and close all connections.
function agent_server.stop(handle)
    if not handle then return end
    for _, c in ipairs(handle.clients) do
        c.sock:close()
    end
    handle.clients = {}
    handle.server:close()
    print("[AGENT] Server stopped")
end

return agent_server
