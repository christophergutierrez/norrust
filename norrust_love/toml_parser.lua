-- toml_parser.lua — Minimal TOML parser for sprite.toml subset
-- Supports: key = "string", key = number, [section], [section.subsection]
-- Does NOT support: arrays, arrays-of-tables, multiline, dates, booleans

local toml_parser = {}

--- Parse a TOML string into a nested Lua table.
-- @param text string: TOML content
-- @return table: parsed data
function toml_parser.parse(text)
    local result = {}
    local current = result  -- pointer to current section table

    for line in text:gmatch("[^\r\n]+") do
        -- Strip comments
        local comment_pos = line:find("#")
        if comment_pos then
            -- Only strip if # is not inside a quoted string
            local in_string = false
            for i = 1, comment_pos - 1 do
                if line:sub(i, i) == '"' then in_string = not in_string end
            end
            if not in_string then
                line = line:sub(1, comment_pos - 1)
            end
        end
        line = line:match("^%s*(.-)%s*$")  -- trim

        if line ~= "" then
            -- Section header: [section] or [section.subsection]
            local section = line:match("^%[([^%]]+)%]$")
            if section then
                current = result
                for part in section:gmatch("[^%.]+") do
                    part = part:match("^%s*(.-)%s*$")
                    if not current[part] then
                        current[part] = {}
                    end
                    current = current[part]
                end
            else
                -- Key = value
                local key, value = line:match("^([%w_%-]+)%s*=%s*(.+)$")
                if key and value then
                    -- String value
                    local str = value:match('^"(.*)"$')
                    if str then
                        current[key] = str
                    else
                        -- Number value
                        local num = tonumber(value)
                        if num then
                            current[key] = num
                        else
                            -- Boolean
                            if value == "true" then
                                current[key] = true
                            elseif value == "false" then
                                current[key] = false
                            else
                                current[key] = value
                            end
                        end
                    end
                end
            end
        end
    end

    return result
end

--- Parse a TOML file.
-- @param path string: file path (Love2D filesystem)
-- @return table|nil: parsed data, or nil if file not found
function toml_parser.parse_file(path)
    local info = love.filesystem.getInfo(path)
    if not info then return nil end
    local text = love.filesystem.read(path)
    if not text then return nil end
    return toml_parser.parse(text)
end

return toml_parser
