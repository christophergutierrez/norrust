-- conf.lua — Love2D configuration: window title, dimensions, and graphics settings.

--- Configure Love2D window and graphics settings.
function love.conf(t)
    t.identity = "norrust"
    t.window.title = "The Clash for Norrust"
    t.window.width = 1280
    t.window.height = 720
    t.window.resizable = true

    -- Allow symlinks so data/ -> ../data works for unit sprites
    love.filesystem.setSymlinksEnabled(true)
end
