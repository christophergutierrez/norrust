-- logger.lua — Verbose logging for debugging FFI calls and state transitions
-- Usage: love norrust_love --verbose (or -v)
-- Output: stdout + /tmp/norrust.log
local M = {}
M.enabled = false
M.file = nil

function M.init()
    M.file = io.open("/tmp/norrust.log", "w")
    if M.file then
        M.file:write("=== norrust verbose log started " .. os.date() .. " ===\n")
        M.file:flush()
    end
    M.enabled = true
    print("[norrust] verbose logging to /tmp/norrust.log")
end

function M.log(msg)
    if not M.enabled then return end
    local line = string.format("[%s] %s", os.date("%H:%M:%S"), msg)
    print(line)
    if M.file then
        M.file:write(line .. "\n")
        M.file:flush()
    end
end

function M.close()
    if M.file then M.file:close() end
end

return M
