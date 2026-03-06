-- events.lua — In-process event bus
-- Gameplay emits semantic events, UI systems subscribe independently.

local events = {}
local listeners = {}  -- topic -> list of callbacks

function events.on(topic, fn)
    if not listeners[topic] then listeners[topic] = {} end
    local t = listeners[topic]
    t[#t + 1] = fn
end

function events.off(topic, fn)
    local t = listeners[topic]
    if not t then return end
    for i = #t, 1, -1 do
        if t[i] == fn then table.remove(t, i) end
    end
end

function events.emit(topic, data)
    for _, fn in ipairs(listeners[topic] or {}) do
        fn(data)
    end
end

function events.clear()
    listeners = {}
end

return events
