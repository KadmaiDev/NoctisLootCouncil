-- Telling an officer about milestones in game (Milestones.lua reads them): off until turned on,
-- and only while milestones are active (on, and an officer):
--   /nlc milestones tell on       a line in your own chat window (nothing is sent)
--   /nlc milestones sound on      a sound: the cue to /reload, so the companion can send it to Discord
--
-- Nothing goes to guild chat: Forever blocks an addon's SendChatMessage to GUILD from a timer
-- (ADDON_ACTION_BLOCKED, seen in game 2026-11-05; pcall doesn't notice, the call just does
-- nothing), and Discord has the congratulations anyway.
local ADDON, ns = ...
if ns.disabled then return end
local L = ns.L

local ipairs, tonumber, date = ipairs, tonumber, date

ns.DEFAULT_LEVELS = { 10, 20, 30, 40, 50, 60 } -- the bot's default too
local FRESH = 300 -- a level-up seen within this long of the last sighting is news
-- The first of these the client has. Names, not numbers: the list differs between clients. The
-- alarm clock comes first because nothing else in a raid sounds like it.
local SOUNDS = { "ALARM_CLOCK_WARNING_3", "READY_CHECK", "RAID_WARNING" }
local rung -- the read of the roster that last played it: several milestones in one read ring once

function ns.Levels()
    local ms = ns.MS()
    return ms and ms.levels or ns.DEFAULT_LEVELS
end

-- The highest milestone a level-up from `from` to `to` passed (18 to 31: 30), or nil.
function ns.MilestoneFor(from, to)
    local best
    for _, level in ipairs(ns.Levels()) do
        if level > from and level <= to and (not best or level > best) then best = level end
    end
    return best
end

local function Fresh(e)
    return e.since ~= nil and e.at - e.since <= FRESH
end

local function Ring()
    if type(SOUNDKIT) ~= "table" or not PlaySound then return end
    for _, name in ipairs(SOUNDS) do
        if SOUNDKIT[name] then
            PlaySound(SOUNDKIT[name], "SFX") -- the player's own volume and mute apply
            return
        end
    end
end

---------------------------------------------------------------------------
-- Called by Milestones.lua for each level-up in the guild the player is in
---------------------------------------------------------------------------
function ns.Celebrate(e)
    local level = ns.MilestoneFor(e.from, e.to)
    if not level then return end
    local ms = ns.MS()
    if ms.sound and rung ~= e.at then
        rung = e.at
        Ring()
    end
    if not ms.tell then return end
    local line = L["%s reached level %d."]:format(e.name, level)
    if not Fresh(e) then
        line = line .. " " .. ns.GREY .. L["(caught up: last seen at level %d, %s)"]
            :format(e.from, date("%d %b %H:%M", e.since or e.at)) .. "|r"
    end
    ns.Say(line)
end

---------------------------------------------------------------------------
-- /nlc milestones tell, sound, levels
---------------------------------------------------------------------------
local function OnOff(word)
    word = (word or ""):lower()
    if word == "on" then return true elseif word == "off" then return false end
end

ns.MilestoneCommand("tell", function(rest)
    local ms = ns.MS()
    local on = OnOff(rest)
    if on == nil then
        ns.Say(L["tell is %s. /nlc milestones tell on/off"]:format(ms.tell and L["on"] or L["off"]))
        return
    end
    ms.tell = on or nil
    ns.Say(on and L["you'll be told in your chat window when someone reaches a milestone (only you see it)."]
        or L["you won't be told about milestones in chat."])
end, L["on/off: a line in your own chat window when someone reaches a milestone (only you see it)"])

ns.MilestoneCommand("sound", function(rest)
    local ms = ns.MS()
    local on = OnOff(rest)
    if on == nil then
        ns.Say(L["sound is %s. /nlc milestones sound on/off"]:format(ms.sound and L["on"] or L["off"]))
        return
    end
    ms.sound = on or nil
    if on then Ring() end -- so you know what to listen for
    ns.Say(on and L["you'll hear this when someone reaches a milestone: /reload then and it goes to Discord."]
        or L["no sound for milestones."])
end, L["on/off: a sound when someone reaches a milestone, your cue to /reload so it reaches Discord"])

ns.MilestoneCommand("levels", function(rest)
    if rest == "" then
        ns.Say(L["milestone levels: %s. /nlc milestones levels 10, 20, 30 (or default)"]:format(table.concat(ns.Levels(), ", ")))
        return
    end
    if rest:lower() == "default" then
        ns.MS().levels = nil
    else
        local levels, seen = {}, {}
        for part in rest:gmatch("[^%s,;]+") do
            local n = tonumber(part)
            if not n or n ~= math.floor(n) or n < 2 or n > 200 then
                ns.Say(L["levels are whole numbers from 2 to 200, like: /nlc milestones levels 10, 20, 30"])
                return
            end
            if not seen[n] then levels[#levels + 1], seen[n] = n, true end
        end
        table.sort(levels)
        ns.MS().levels = levels
    end
    ns.Say(L["milestone levels: %s. (These are for your chat and sound here; the bot's own are set in Discord.)"]:format(table.concat(ns.Levels(), ", ")))
end, L["the levels told about in game (default 10, 20, 30, 40, 50, 60)"])
