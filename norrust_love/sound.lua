-- sound.lua — Sound effects and music manager
-- Generates procedural placeholder sounds via SoundData. No external files needed.

local sound = {}

local effects = {}      -- name -> love.Source
local pools = {}        -- name -> {sources={}, idx=0}
local POOL_SIZE = 3
local volume = 0.5      -- master volume 0.0-1.0
local muted = false
local current_music = nil  -- love.Source or nil

-- ── Procedural sound generation ─────────────────────────────────────────────

local SAMPLE_RATE = 44100

--- Generate a SoundData buffer with a given duration and per-sample function.
-- fn(i, total) should return a sample in [-1, 1].
local function gen(duration, fn)
    local samples = math.floor(SAMPLE_RATE * duration)
    local sd = love.sound.newSoundData(samples, SAMPLE_RATE, 16, 1)
    for i = 0, samples - 1 do
        sd:setSample(i, fn(i, samples))
    end
    return sd
end

--- White noise burst with linear fade-out.
local function noise_burst(duration, amp)
    return gen(duration, function(i, total)
        local env = (1 - i / total) * (amp or 1.0)
        return (math.random() * 2 - 1) * env
    end)
end

--- Sine wave with linear fade-out.
local function sine_tone(duration, freq, amp)
    return gen(duration, function(i, total)
        local env = (1 - i / total) * (amp or 1.0)
        return math.sin(2 * math.pi * freq * i / SAMPLE_RATE) * env
    end)
end

--- Frequency sweep (ascending or descending) with fade-out.
local function sweep(duration, freq_start, freq_end, amp)
    return gen(duration, function(i, total)
        local t = i / total
        local freq = freq_start + (freq_end - freq_start) * t
        local env = (1 - t) * (amp or 1.0)
        return math.sin(2 * math.pi * freq * i / SAMPLE_RATE) * env
    end)
end

-- ── File loading with procedural fallback ────────────────────────────────────

--- Try to load an audio file from data/sounds/<name>.ogg or .wav.
-- Falls back to procedural SoundData if no file found.
local function load_or_generate(name, gen_sound_data)
    for _, ext in ipairs({".ogg", ".wav"}) do
        local path = "data/sounds/" .. name .. ext
        if love.filesystem.getInfo(path) then
            local ok, src = pcall(love.audio.newSource, path, "static")
            if ok then return src end
        end
    end
    return love.audio.newSource(gen_sound_data, "static")
end

-- ── Public API ──────────────────────────────────────────────────────────────

function sound.load()
    effects.hit       = load_or_generate("hit",      noise_burst(0.1, 0.7))
    effects.miss      = load_or_generate("miss",     sweep(0.12, 800, 1200, 0.3))
    effects.death     = load_or_generate("death",    noise_burst(0.25, 0.9))
    effects.move      = load_or_generate("move",     sine_tone(0.05, 300, 0.25))
    effects.recruit   = load_or_generate("recruit",  sweep(0.18, 400, 800, 0.5))
    effects.turn_end  = load_or_generate("turn_end", sine_tone(0.2, 660, 0.4))
    effects.select    = load_or_generate("select",   sine_tone(0.03, 500, 0.2))
end

function sound.play(name)
    if muted then return end
    local src = effects[name]
    if not src then return end
    local pool = pools[name]
    if not pool then
        local sources = {}
        for i = 1, POOL_SIZE do
            sources[i] = src:clone()
        end
        pool = {sources = sources, idx = 0}
        pools[name] = pool
    end
    pool.idx = pool.idx % POOL_SIZE + 1
    local s = pool.sources[pool.idx]
    s:stop()
    s:setVolume(volume)
    s:play()
end

function sound.set_volume(v)
    volume = math.max(0, math.min(1, v))
    if current_music then
        current_music:setVolume(volume * 0.5)
    end
end

function sound.get_volume()
    return volume
end

function sound.toggle_mute()
    muted = not muted
    if current_music then
        if muted then
            current_music:pause()
        else
            current_music:play()
        end
    end
end

function sound.is_muted()
    return muted
end

function sound.play_music(path)
    sound.stop_music()
    if not path then return end
    local info = love.filesystem.getInfo(path)
    if not info then return end
    local ok, src = pcall(love.audio.newSource, path, "stream")
    if not ok then return end
    src:setLooping(true)
    src:setVolume(volume * 0.5)
    if not muted then
        src:play()
    end
    current_music = src
end

function sound.stop_music()
    if current_music then
        current_music:stop()
        current_music = nil
    end
end

return sound
