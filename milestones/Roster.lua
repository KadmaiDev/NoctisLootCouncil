-- The guild roster: each member's level, and every level-up between two reads of it. The bot
-- picks the milestones (10, 20, ... 60 by default) from the level-ups; the addon notes them all.
-- Someone the addon hasn't seen before is only noted, never counted as a level-up, so the first
-- read of a guild (or a new member) announces nothing.
local ADDON, ns = ...
if ns.disabled then return end
local L = ns.L

local type, ipairs, pairs, time, date = type, ipairs, pairs, time, date

local ASK_EVERY = 60          -- seconds between asking the server for a fresh roster
local SETTLE = 2              -- roster updates come in bursts: read once they've settled
local KEEP_SECONDS = 30 * 86400 -- level-ups older than this are dropped (the bot has them by then)
local KEEP_MAX = 2000
local SHOWN = 5               -- recent level-ups /nms lists

-- The player's guild: name, realm and its key in db.guilds, or nil (not in one, or the client
-- hasn't loaded it yet).
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
    local name, realm, key = ns.GuildKey()
    if not key then return nil end
    local g = ns.db.guilds[key]
    if not g and create then
        g = { name = name, realm = realm, members = {}, levels = {} }
        ns.db.guilds[key] = g
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
    if not ns.db then return 0 end
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
                    g.levels[#g.levels + 1] = { name = name, class = class or m.class, from = m.level, to = level,
                        at = now, since = m.seen }
                    ups = ups + 1
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
    if ask and (not IsInGuild or IsInGuild()) then pcall(ask) end
end

-- Every ASK_EVERY seconds while logged in (a timer, not OnUpdate), so level-ups are seen even
-- when nothing else makes the client refresh the roster.
local function Tick()
    AskForRoster()
    C_Timer.After(ASK_EVERY, Tick)
end

local settling = false
ns.On("GUILD_ROSTER_UPDATE", function()
    if settling then return end
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
-- /nms
---------------------------------------------------------------------------
local function Ago(seconds)
    if seconds < 90 then return L["just now"] end
    local floor = math.floor
    if seconds < 5400 then return L["%d minutes ago"]:format(floor(seconds / 60 + 0.5)) end
    if seconds < 129600 then return L["%d hours ago"]:format(floor(seconds / 3600 + 0.5)) end
    return L["%d days ago"]:format(floor(seconds / 86400 + 0.5))
end

function ns.Status()
    local name, realm = ns.GuildKey()
    local g = ns.Guild(false)
    if not name then
        ns.Say(L["this character isn't in a guild (or the guild hasn't loaded yet)."])
    elseif not g or not g.scanned then
        ns.Say(L["%s: the roster hasn't been read yet; it will be within a minute."]:format(name))
    else
        local members = 0
        for _ in pairs(g.members) do members = members + 1 end
        ns.Say(L["%s (%s): %d members, roster read %s; %d level-ups noted in the last 30 days."]
            :format(g.name, realm, members, Ago(time() - g.scanned), #g.levels))
        for i = #g.levels, math.max(1, #g.levels - SHOWN + 1), -1 do
            local e = g.levels[i]
            print("  " .. ns.WHITE .. e.name .. "|r " .. L["%d to %d"]:format(e.from, e.to) .. ns.GREY .. "  "
                .. date("%d %b %H:%M", e.at) .. "|r")
        end
    end
    ns.Say(L["The companion app sends level-ups to Discord after you log out or /reload; the bot only takes its own guild's."])
end

ns.Command("status", ns.Status, L["your guild, and the level-ups noted"])
ns.Command("scan", function()
    AskForRoster()
    ns.Say(L["asked the server for the guild roster."])
end, L["read the guild roster now"])
