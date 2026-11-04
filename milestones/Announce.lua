-- Telling people about milestones in game, both off until an officer turns them on:
--   /nms tell on       a line in your own chat window (nothing is sent; every character on the account)
--   /nms guildchat on  "Congratulations to X on reaching level 20!" in guild chat (this guild only)
--
-- Several officers may have guild chat on; one of them, the announcer, posts. The addons with it
-- on say hello to each other over the guild's addon channel (at login, then every HEARTBEAT
-- seconds; those already online answer a newcomer), and the announcer is whoever has been online
-- longest (a /reload keeps your place). When the announcer logs off, the guild roster shows them
-- offline (or they stop being heard from) and the next one takes over: nothing is handed over.
-- If addon messages can't be sent (Forever may restrict them), every addon thinks it's alone, so
-- each waits a random moment first and stays quiet if the same line appears in guild chat.
-- Only fresh level-ups go to guild chat: ones seen happen within FRESH seconds, not ones caught up
-- on at login after time away.
local ADDON, ns = ...
if ns.disabled then return end
local L = ns.L

local type, pairs, ipairs, tonumber, date, pcall, random = type, pairs, ipairs, tonumber, date, pcall, math.random

local PREFIX = "NoctisMS"
ns.DEFAULT_LEVELS = { 10, 20, 30, 40, 50, 60 } -- the bot's default too
local FRESH = 300           -- a level-up seen within this long of the last sighting is news
local HEARTBEAT = 300       -- seconds between hellos while guild chat is on
local GONE = 2 * HEARTBEAT + 60 -- an announcer not heard from for this long has gone
local DELAY_MIN, DELAY_SPREAD = 0.5, 1.5 -- the announcer waits 0.5 to 2 seconds (in case another posts)
local ALONE_MIN, ALONE_SPREAD = 1, 7     -- without addon messages: 1 to 8 seconds

if C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix then pcall(C_ChatInfo.RegisterAddonMessagePrefix, PREFIX) end

function ns.Levels()
    return ns.db.levels or ns.DEFAULT_LEVELS
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

---------------------------------------------------------------------------
-- Who announces
---------------------------------------------------------------------------
-- Other officers' addons with guild chat on, in this guild: [name key] = { name, since = time(), heard = GetTime() }
local peers = {}
ns.peers = peers
local messagesWork = false -- our last hello went out

local function GuildChatOn()
    local g = ns.Guild and ns.Guild(false)
    return g and g.guildChat and g
end

-- Says hello ("H", answered by those online) or answers one ("R"), or goodbye ("B").
local function Send(kind)
    local send = C_ChatInfo and C_ChatInfo.SendAddonMessage
    if not send or not ns.onlineSince then return false end
    local ok, result = pcall(send, PREFIX, kind .. "\t" .. ns.onlineSince, "GUILD")
    messagesWork = ok and (result == 0 or result == true)
    return messagesWork
end

local function Before(aSince, aKey, bSince, bKey)
    if aSince ~= bSince then return aSince < bSince end
    return aKey < bKey
end

-- The officer who posts: name, and true if it's us.
function ns.Announcer()
    local me = ns.NameKey(ns.PlayerName())
    local bestKey, bestSince, bestName = me, ns.onlineSince or time(), ns.PlayerName()
    local now = GetTime()
    for key, p in pairs(peers) do
        if now - p.heard > GONE then
            peers[key] = nil
        elseif Before(p.since, key, bestSince, bestKey) then
            bestKey, bestSince, bestName = key, p.since, p.name
        end
    end
    return bestName, bestKey == me
end

-- Roster.lua tells us who's offline, so an announcer who logged off is dropped at once.
function ns.SeenOffline(key)
    peers[key] = nil
end

ns.On("CHAT_MSG_ADDON", function(prefix, text, channel, sender)
    if prefix ~= PREFIX or channel ~= "GUILD" then return end
    text = ns.Typed(text, "string")
    local name = ns.CleanName(sender)
    local key = ns.NameKey(name)
    if not text or not key or key == ns.NameKey(ns.PlayerName()) then return end
    local kind, since = text:match("^(%u)\t(%d+)$")
    since = tonumber(since)
    if not kind or not since then return end
    if kind == "B" then
        peers[key] = nil
    elseif kind == "H" or kind == "R" then
        peers[key] = { name = name, since = since, heard = GetTime() }
        if kind == "H" and GuildChatOn() then Send("R") end -- so the newcomer knows we're here
    end
end)

-- When this session started: kept across /reload (PLAYER_ENTERING_WORLD says which it was).
ns.On("PLAYER_LOGIN", function()
    ns.onlineSince = time()
end)

local entered = false
local function Heartbeat()
    if GuildChatOn() then Send("H") end
    C_Timer.After(HEARTBEAT, Heartbeat)
end
ns.On("PLAYER_ENTERING_WORLD", function(isInitialLogin, isReloadingUi)
    if entered then return end -- it fires again at every loading screen
    entered = true
    if isReloadingUi == true and ns.Typed(ns.db.onlineSince, "number") then ns.onlineSince = ns.db.onlineSince end
    ns.db.onlineSince = ns.onlineSince
    Heartbeat()
end)

---------------------------------------------------------------------------
-- Posting
---------------------------------------------------------------------------
local said = {} -- guild chat lines seen lately: [text] = GetTime()
local pending = {} -- [text] = true while waiting to post it

ns.On("CHAT_MSG_GUILD", function(text)
    text = ns.Typed(text, "string")
    if text then said[text] = GetTime() end
end)

local function SendGuild(text)
    local locked = C_ChatInfo and C_ChatInfo.InChatMessagingLockdown and C_ChatInfo.InChatMessagingLockdown()
    local send = C_ChatInfo and C_ChatInfo.SendChatMessage or SendChatMessage
    if locked or not send or not pcall(send, text, "GUILD") then
        ns.Say(L["couldn't post this in guild chat: %s"]:format(text))
    end
end

local function Congratulate(name, level)
    local _, mine = ns.Announcer()
    if not mine then return end
    local text = L["Congratulations to %s on reaching level %d!"]:format(name, level)
    if pending[text] then return end
    pending[text] = true
    local asked = GetTime()
    local wait = messagesWork and (DELAY_MIN + random() * DELAY_SPREAD) or (ALONE_MIN + random() * ALONE_SPREAD)
    C_Timer.After(wait, function()
        pending[text] = nil
        if said[text] and said[text] >= asked - 60 then return end -- another officer's addon said it
        SendGuild(text)
    end)
end

---------------------------------------------------------------------------
-- Called by Roster.lua for each level-up in the guild the player is in
---------------------------------------------------------------------------
function ns.Celebrate(g, e)
    local level = ns.MilestoneFor(e.from, e.to)
    if not level then return end
    if ns.db.tell then
        local line = L["%s reached level %d."]:format(e.name, level)
        if not Fresh(e) then
            line = line .. " " .. ns.GREY .. L["(caught up: last seen at level %d, %s)"]
                :format(e.from, date("%d %b %H:%M", e.since or e.at)) .. "|r"
        end
        ns.Say(line)
    end
    if g.guildChat and Fresh(e) then Congratulate(e.name, level) end
end

---------------------------------------------------------------------------
-- /nms tell, guildchat, levels
---------------------------------------------------------------------------
local function OnOff(word)
    word = (word or ""):lower()
    if word == "on" then return true elseif word == "off" then return false end
end

ns.Command("tell", function(rest)
    local on = OnOff(rest)
    if on == nil then
        ns.Say(L["tell is %s. /nms tell on/off"]:format(ns.db.tell and L["on"] or L["off"]))
        return
    end
    ns.db.tell = on or nil
    ns.Say(on and L["you'll be told in your chat window when someone reaches a milestone (only you see it)."]
        or L["you won't be told about milestones in chat."])
end, L["on/off: a line in your own chat window when someone reaches a milestone (only you see it)"])

ns.Command("guildchat", function(rest)
    local on = OnOff(rest)
    local g = ns.Guild(on ~= nil)
    if not g then
        ns.Say(L["this character isn't in a guild (or the guild hasn't loaded yet)."])
        return
    end
    if on == true then
        g.guildChat = true
        Send("H")
        ns.Say(L["milestones will be congratulated in %s's guild chat. If other officers have this on, the one online longest posts."]:format(g.name))
    elseif on == false then
        Send("B")
        g.guildChat = nil
        ns.Say(L["no more milestones in %s's guild chat from you."]:format(g.name))
        return
    end
    if not g.guildChat then
        ns.Say(L["guild chat for %s is off. /nms guildchat on/off"]:format(g.name))
        return
    end
    local others = 0
    for _ in pairs(peers) do others = others + 1 end
    local who, mine = ns.Announcer()
    if mine then
        ns.Say(L["guild chat for %s is on, and you're the one posting (%d other officers with it on are online)."]:format(g.name, others))
    else
        ns.Say(L["guild chat for %s is on; %s is posting (online longest). You take over if they log off."]:format(g.name, who))
    end
end, L["on/off: congratulate milestones in guild chat (this guild only; the officer online longest posts)"])

ns.Command("levels", function(rest)
    if rest == "" then
        ns.Say(L["milestone levels: %s. /nms levels 10, 20, 30 (or default)"]:format(table.concat(ns.Levels(), ", ")))
        return
    end
    if rest:lower() == "default" then
        ns.db.levels = nil
    else
        local levels, seen = {}, {}
        for part in rest:gmatch("[^%s,;]+") do
            local n = tonumber(part)
            if not n or n ~= math.floor(n) or n < 2 or n > 200 then
                ns.Say(L["levels are whole numbers from 2 to 200, like: /nms levels 10, 20, 30"])
                return
            end
            if not seen[n] then levels[#levels + 1], seen[n] = n, true end
        end
        table.sort(levels)
        ns.db.levels = levels
    end
    ns.Say(L["milestone levels: %s. (These are for chat here; the bot's own are set in Discord.)"]:format(table.concat(ns.Levels(), ", ")))
end, L["the levels told about in game (default 10, 20, 30, 40, 50, 60)"])
