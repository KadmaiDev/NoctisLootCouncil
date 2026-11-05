-- Level milestones, for officers: the guild roster, each member's level, and every level-up
-- between two reads of it. The companion app sends the level-ups and the Noctis bot picks the
-- milestones (10, 20, ... 60 by default) from them and congratulates them on Discord;
-- MilestonesChat.lua can also tell about them in game.
--
-- Off until `/nlc milestones on` (db.milestones is made then: raiders' saved files never hold a
-- roster), and even then only on characters the game says are officers of their guild
-- (C_GuildInfo.IsGuildOfficer / CanViewOfficerNote), checked at every read. Anyone else's
-- addon doesn't ask for the roster, read it or say anything.
-- Someone the addon hasn't seen before is only noted, never counted as a level-up, so the first
-- read of a guild (or a new member) announces nothing.
local ADDON, ns = ...
if ns.disabled then return end
local L = ns.L

local type, ipairs, pairs, time, date, pcall = type, ipairs, pairs, time, date, pcall

local ASK_EVERY = 60          -- seconds between asking the server for a fresh roster
local SETTLE = 2              -- roster updates come in bursts: read once they've settled
local KEEP_SECONDS = 30 * 86400 -- level-ups older than this are dropped (the bot has them by then)
local KEEP_MAX = 2000
local SHOWN = 5               -- recent level-ups the status lists

-- A plain value of this type, else nil.
function ns.Typed(x, kind)
    if ns.Plain(x) and type(x) == kind then return x end
end

-- A roster name as shown: "-Realm" dropped, trimmed.
function ns.CleanName(name)
    name = ns.Typed(name, "string")
    if not name then return nil end
    name = name:gsub("%-.*$", ""):gsub("^%s+", ""):gsub("%s+$", "")
    if name == "" then return nil end
    return name
end

-- The milestones part of the saved data, or nil if it was never turned on.
function ns.MS()
    return ns.db and ns.db.milestones
end

-- True if the game says this character may read officer notes or is an officer of its guild.
-- If it can't tell, no.
function ns.IsGuildOfficer()
    if IsInGuild and not IsInGuild() then return false end
    local gi = C_GuildInfo
    if not gi then return false end
    for _, ask in ipairs({ gi.IsGuildOfficer, gi.CanViewOfficerNote }) do
        local ok, yes = pcall(ask)
        if ok and ns.Typed(yes, "boolean") then return true end
    end
    return false
end

-- Turned on, and an officer: the only case where anything is read or said.
function ns.MilestonesActive()
    local ms = ns.MS()
    return ms ~= nil and ms.on == true and ns.IsGuildOfficer()
end

-- The player's guild: name, realm and its key in db.milestones.guilds, or nil (not in one, or
-- the client hasn't loaded it yet).
function ns.GuildKey()
    if IsInGuild and not IsInGuild() then return nil end
    local name, _, _, realm = GetGuildInfo("player")
    name = ns.Typed(name, "string")
    if not name or name == "" then return nil end
    realm = ns.Typed(realm, "string")
    if not realm or realm == "" then realm = ns.Typed(GetRealmName and GetRealmName(), "string") or "" end
    return name, realm, name .. "|" .. realm
end

function ns.Guild(create)
    local ms = ns.MS()
    local name, realm, key = ns.GuildKey()
    if not ms or not key then return nil end
    local g = ms.guilds[key]
    if not g and create then
        g = { name = name, realm = realm, members = {}, levels = {} }
        ms.guilds[key] = g
    end
    return g
end

local function Prune(levels, now)
    local keep = {}
    for _, e in ipairs(levels) do
        if now - e.at <= KEEP_SECONDS then keep[#keep + 1] = e end
    end
    while #keep > KEEP_MAX do table.remove(keep, 1) end
    return keep
end

-- Reads the roster the client has. Returns how many level-ups it found.
function ns.Scan()
    if not ns.MilestonesActive() then return 0 end
    local g = ns.Guild(true)
    if not g then return 0 end
    local total = ns.Typed(GetNumGuildMembers(), "number") or 0
    local now, ups = time(), 0
    for i = 1, total do
        local name, rank, _, level, _, _, _, _, _, _, class = GetGuildRosterInfo(i)
        name, level = ns.CleanName(name), ns.Typed(level, "number")
        local key = ns.NameKey(name)
        if key and level and level > 0 then
            rank, class = ns.Typed(rank, "string"), ns.Typed(class, "string")
            local m = g.members[key]
            if not m then
                g.members[key] = { name = name, class = class, level = level, rank = rank, seen = now }
            else
                if level > m.level then
                    local e = { name = name, class = class or m.class, from = m.level, to = level, at = now, since = m.seen }
                    g.levels[#g.levels + 1] = e
                    ups = ups + 1
                    if ns.Celebrate then ns.Celebrate(e) end
                end
                m.name, m.level, m.seen = name, level, now
                m.class, m.rank = class or m.class, rank or m.rank
            end
        end
    end
    if total > 0 then g.scanned = now end
    g.levels = Prune(g.levels, now)
    return ups
end

local function AskForRoster()
    local ask = C_GuildInfo and C_GuildInfo.GuildRoster or GuildRoster
    if ask and ns.MilestonesActive() then pcall(ask) end
end

-- Every ASK_EVERY seconds while logged in (a timer, not OnUpdate), so level-ups are seen even
-- when nothing else makes the client refresh the roster. Asks only while active.
local function Tick()
    AskForRoster()
    C_Timer.After(ASK_EVERY, Tick)
end

local settling = false
ns.On("GUILD_ROSTER_UPDATE", function()
    if settling or not ns.MilestonesActive() then return end
    settling = true
    C_Timer.After(SETTLE, function()
        settling = false
        ns.Scan()
    end)
end)

ns.On("PLAYER_LOGIN", function()
    Tick()
end)

---------------------------------------------------------------------------
-- /nlc milestones
---------------------------------------------------------------------------
local subcommands, order = {}, {}

-- MilestonesChat.lua adds tell and levels.
function ns.MilestoneCommand(name, fn, help)
    if not subcommands[name] then order[#order + 1] = name end
    subcommands[name] = { fn = fn, help = help }
end

local function Ago(seconds)
    if seconds < 90 then return L["just now"] end
    local floor = math.floor
    if seconds < 5400 then return L["%d minutes ago"]:format(floor(seconds / 60 + 0.5)) end
    if seconds < 129600 then return L["%d hours ago"]:format(floor(seconds / 3600 + 0.5)) end
    return L["%d days ago"]:format(floor(seconds / 86400 + 0.5))
end

local function OnOffText(on) return on and L["on"] or L["off"] end

function ns.MilestoneStatus()
    local ms = ns.MS()
    if not ms or not ms.on then
        ns.Say(L["level milestones are off. Officers: /nlc milestones on"])
        return
    end
    local name, realm = ns.GuildKey()
    if not name then
        ns.Say(L["milestones are on, but this character isn't in a guild (or the guild hasn't loaded yet)."])
        return
    end
    if not ns.IsGuildOfficer() then
        ns.Say(L["milestones are on, but this character isn't an officer in %s, so nothing is read or said here."]:format(name))
        return
    end
    local g = ns.Guild(false)
    if not g or not g.scanned then
        ns.Say(L["%s: the roster hasn't been read yet; it will be within a minute."]:format(name))
        return
    end
    local members = 0
    for _ in pairs(g.members) do members = members + 1 end
    ns.Say(L["%s (%s): %d members, roster read %s; %d level-ups noted in the last 30 days."]
        :format(g.name, realm, members, Ago(time() - g.scanned), #g.levels))
    ns.Say(L["told in your chat: %s; sound: %s; levels %s."]:format(OnOffText(ms.tell), OnOffText(ms.sound),
        table.concat(ns.Levels and ns.Levels() or {}, ", ")))
    for i = #g.levels, math.max(1, #g.levels - SHOWN + 1), -1 do
        local e = g.levels[i]
        print("  " .. ns.WHITE .. e.name .. "|r " .. L["%d to %d"]:format(e.from, e.to) .. ns.GREY .. "  "
            .. date("%d %b %H:%M", e.at) .. "|r")
    end
    ns.Say(L["The companion app sends level-ups to Discord after you log out or /reload; the bot only takes its own guild's."])
end

local function Help()
    ns.Say(L["level milestones (officers):"])
    print("  " .. ns.WHITE .. "/nlc milestones|r " .. L["what's been noted"])
    for _, name in ipairs(order) do
        local c = subcommands[name]
        print("  " .. ns.WHITE .. "/nlc milestones " .. name .. "|r " .. c.help)
    end
end

ns.MilestoneCommand("on", function()
    ns.db.milestones = ns.db.milestones or { guilds = {} }
    ns.db.milestones.on = true
    local name = ns.GuildKey()
    if name and not ns.IsGuildOfficer() then
        ns.Say(L["milestones are on for this account, but this character isn't an officer in %s, so it stays quiet here."]:format(name))
        return
    end
    ns.Say(L["milestones are on: the guild roster is read every minute and level-ups noted for the companion app."])
    AskForRoster()
end, L["read the guild roster and note level-ups (officers only; every character on this account)"])

ns.MilestoneCommand("off", function()
    local ms = ns.MS()
    if ms then ms.on = nil end
    ns.Say(L["milestones are off: the roster isn't read. What was noted stays, for when it's turned on again."])
end, L["stop"])

ns.MilestoneCommand("scan", function()
    if not ns.MilestonesActive() then
        ns.MilestoneStatus()
        return
    end
    AskForRoster()
    ns.Say(L["asked the server for the guild roster."])
end, L["read the guild roster now"])

ns.Command("milestones", function(text)
    local word, rest = (text or ""):match("^%s*(%S*)%s*(.-)%s*$")
    word = word:lower()
    if word == "" or word == "status" then return ns.MilestoneStatus() end
    local c = subcommands[word]
    if not c then return Help() end
    if word ~= "on" and word ~= "off" and not ns.MS() then
        ns.Say(L["level milestones are off. Officers: /nlc milestones on"])
        return
    end
    c.fn(rest)
end, L["[on/off/tell/sound/levels]: guild level milestones, for officers (/nlc milestones help)"])
