-- Noctis Milestones: notes guild members' level-ups for the Noctis bot, which congratulates
-- them on Discord. For officers; the companion app uploads the saved file. This file: the
-- one-copy guard, events, saved data, names and the /nms command.
local ADDON, ns = ...
local L = ns.L

-- Only one copy may run (a released copy and a dev copy would share the saved data and /nms).
if NoctisMilestonesRunning then
    ns.disabled = true
    local running = NoctisMilestonesRunning
    local f = CreateFrame("Frame")
    f:RegisterEvent("PLAYER_LOGIN")
    f:SetScript("OnEvent", function()
        print("|cffffd100Noctis Milestones|r " .. L["two copies are enabled (%s and %s). Only %s is running; disable one of them in the AddOns list."]
            :format(running, ADDON, running))
    end)
    return
end
NoctisMilestonesRunning = ADDON

local pcall, xpcall, type, pairs, ipairs = pcall, xpcall, type, pairs, ipairs
local issecretvalue = issecretvalue or function() return false end

ns.GOLD, ns.GREY, ns.WHITE = "|cffffd100", "|cff9d9d9d", "|cffffffff"

function ns.Say(text)
    print(ns.GOLD .. "Noctis Milestones|r " .. text)
end

-- True for a value addon code may look at: not a secret and not nil.
function ns.Plain(x)
    return not issecretvalue(x) and x ~= nil
end

-- A plain value of this type, else nil.
function ns.Typed(x, kind)
    if ns.Plain(x) and type(x) == kind then return x end
end

---------------------------------------------------------------------------
-- Events
---------------------------------------------------------------------------
local frame = CreateFrame("Frame")
local handlers = {}

-- Registering an event this client doesn't know throws on Forever, so guard it.
function ns.On(event, fn)
    if not pcall(frame.RegisterEvent, frame, event) then return false end
    handlers[event] = handlers[event] or {}
    handlers[event][#handlers[event] + 1] = fn
    return true
end

frame:SetScript("OnEvent", function(_, event, ...)
    for _, fn in ipairs(handlers[event] or {}) do xpcall(fn, geterrorhandler(), ...) end
end)

---------------------------------------------------------------------------
-- Saved data (account-wide: one file for every character on the account)
---------------------------------------------------------------------------
-- NoctisMilestonesDB = {
--   v = 1,
--   me = "First Last",                 -- who last logged in with this file
--   tell = true|nil,                   -- /nms tell: milestones in your own chat window (Announce.lua)
--   levels = { 10, 20, ... }|nil,      -- /nms levels (nil = ns.DEFAULT_LEVELS)
--   onlineSince = time()|nil,          -- when this session began, kept across /reload (Announce.lua)
--   guilds = { ["Guild|Realm"] = {     -- each guild a character on this account is in, apart
--     name = "Noctis", realm = "...",  -- (the bot takes only its own guild's)
--     scanned = time()|nil,            -- the last roster read
--     guildChat = true|nil,            -- /nms guildchat: congratulate in this guild's chat
--     members = { ["first last"] = { name = "First Last", class = "DRUID", level, rank, seen = time() } },
--     levels = { { name, class, from, to, at = time(), since = time() } }, -- level-ups seen, oldest first:
--   } },                               -- from `from` (last seen at `since`) to `to`, noticed at `at`
-- }
-- The companion app reads this file; its format is in the repository's docs/sync-format.md.
local DB_FIELDS = { v = "number", me = "string", guilds = "table", tell = "boolean", levels = "table",
    onlineSince = "number" }
local GUILD_FIELDS = { name = "string", realm = "string", scanned = "number", members = "table", levels = "table",
    guildChat = "boolean" }
local MEMBER_FIELDS = { name = "string", class = "string", level = "number", rank = "string", seen = "number" }
local LEVEL_FIELDS = { name = "string", class = "string", from = "number", to = "number", at = "number", since = "number" }

local function KeepTyped(t, fields)
    for k, v in pairs(t) do
        if fields[k] ~= type(v) then t[k] = nil end
    end
end

local function Compact(list, keep)
    local out, n = {}, 0
    for i = 1, table.maxn(list) do
        if list[i] ~= nil and keep(list[i]) then
            n = n + 1
            out[n] = list[i]
        end
    end
    return out
end

function ns.Repair(db)
    KeepTyped(db, DB_FIELDS)
    db.v = 1
    if db.levels then
        db.levels = Compact(db.levels, function(n) return type(n) == "number" and n >= 2 and n <= 200 end)
        if #db.levels == 0 then db.levels = nil else table.sort(db.levels) end
    end
    db.guilds = db.guilds or {}
    for key, g in pairs(db.guilds) do
        if type(key) ~= "string" or type(g) ~= "table" then
            db.guilds[key] = nil
        else
            KeepTyped(g, GUILD_FIELDS)
            if not g.name then
                db.guilds[key] = nil
            else
                g.realm = g.realm or ""
                g.members = g.members or {}
                for k, m in pairs(g.members) do
                    if type(k) ~= "string" or type(m) ~= "table" then
                        g.members[k] = nil
                    else
                        KeepTyped(m, MEMBER_FIELDS)
                        if not (m.name and m.level and m.seen) then g.members[k] = nil end
                    end
                end
                g.levels = Compact(g.levels or {}, function(e)
                    if type(e) ~= "table" then return false end
                    KeepTyped(e, LEVEL_FIELDS)
                    return e.name ~= nil and e.from ~= nil and e.to ~= nil and e.at ~= nil
                end)
            end
        end
    end
    return db
end

ns.On("ADDON_LOADED", function(name)
    if name ~= ADDON then return end
    if type(NoctisMilestonesDB) ~= "table" then NoctisMilestonesDB = {} end
    ns.db = ns.Repair(NoctisMilestonesDB)
end)

ns.On("PLAYER_LOGIN", function()
    if ns.db then ns.db.me = ns.PlayerName() or ns.db.me end
end)

---------------------------------------------------------------------------
-- Names
---------------------------------------------------------------------------
-- Forever characters have a first name and a surname ("Vespera Ashward"); the roster may
-- add "-Realm", which is dropped. Members are keyed by the lower-cased name.
function ns.PlayerName(unit)
    local first, last = UnitName(unit or "player")
    if not ns.Typed(first, "string") then return nil end
    if ns.Typed(last, "string") and last ~= "" then return first .. " " .. last end
    return first
end

function ns.CleanName(name)
    name = ns.Typed(name, "string")
    if not name then return nil end
    name = name:gsub("%-.*$", ""):gsub("^%s+", ""):gsub("%s+$", "")
    if name == "" then return nil end
    return name
end

function ns.NameKey(name)
    name = ns.CleanName(name)
    return name and name:lower()
end

---------------------------------------------------------------------------
-- /nms
---------------------------------------------------------------------------
local commands, order = {}, {}

function ns.Command(name, fn, help)
    if not commands[name] then order[#order + 1] = name end
    commands[name] = { fn = fn, help = help }
end

local function Help()
    ns.Say(L["commands:"])
    for _, name in ipairs(order) do
        local c = commands[name]
        if c.help then print("  " .. ns.WHITE .. "/nms " .. name .. "|r " .. c.help) end
    end
end

SLASH_NOCTISMILESTONES1 = "/nms"
SLASH_NOCTISMILESTONES2 = "/noctismilestones"
SlashCmdList.NOCTISMILESTONES = function(msg)
    if not ns.db then return end
    local word, rest = (msg or ""):match("^%s*(%S*)%s*(.-)%s*$")
    local c = commands[word:lower()]
    if c then c.fn(rest) elseif word == "" and ns.Status then ns.Status() else Help() end
end
