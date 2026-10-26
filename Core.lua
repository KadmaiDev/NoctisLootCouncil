-- Noctis Loot Council: loot rolls and loot council for the Noctis guild on WoW: Forever.
-- This file: the one-copy guard, events, saved data and the /nlc command.
local ADDON, ns = ...
local L = ns.L

-- Only one copy may run (e.g. a released copy and a dev copy both enabled): both would use
-- the same saved data and the same /nlc command. A copy that finds another already running
-- stays off and says so at login.
if NoctisLootCouncilRunning then
    ns.disabled = true
    local running = NoctisLootCouncilRunning
    local f = CreateFrame("Frame")
    f:RegisterEvent("PLAYER_LOGIN")
    f:SetScript("OnEvent", function()
        print("|cffffd100Noctis Loot Council|r " .. L["two copies are enabled (%s and %s). Only %s is running; disable one of them in the AddOns list."]
            :format(running, ADDON, running))
    end)
    return
end
NoctisLootCouncilRunning = ADDON

local pcall, xpcall, type, pairs, ipairs, next, tostring = pcall, xpcall, type, pairs, ipairs, next, tostring
local issecretvalue = issecretvalue or function() return false end

ns.GOLD, ns.GREY, ns.WHITE, ns.GREEN = "|cffffd100", "|cff9d9d9d", "|cffffffff", "|cff40c040"

function ns.Say(text)
    print(ns.GOLD .. "Noctis Loot Council|r " .. text)
end

-- True for a value addon code may look at: not a secret (testing a secret, even with `if x`,
-- throws, and one written into saved data breaks the whole save) and not nil.
function ns.Plain(x)
    return not issecretvalue(x) and x ~= nil
end

---------------------------------------------------------------------------
-- Events
---------------------------------------------------------------------------
local frame = CreateFrame("Frame")
local handlers = {}

-- Registering an event this client doesn't know throws on Forever, so guard it. Several
-- handlers may listen to one event.
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
-- Saved data
---------------------------------------------------------------------------
-- NoctisLootCouncilDB = {
--   v = 1,
--   items = { [itemID] = item },        -- every drop seen (Discovery.lua)
--   encounters = { [encounterID] = { name, inst = instanceID, src = "n<npcID>"|"o<objectID>" } },
--   bossSources = { ["n<npcID>"|"o<objectID>"] = encounterID }, -- corpses and chests learned to be a boss's
--   instances = { [instanceID] = name },
--   minQuality = number|nil,            -- lowest quality recorded (nil = 3, rare)
--   dungeons = true|nil,                -- record dungeon drops too (for trying it out)
-- }
-- Each field's type, so a damaged save is repaired at load instead of breaking things.
local DB_FIELDS = { v = "number", items = "table", encounters = "table", bossSources = "table",
    instances = "table", minQuality = "number", dungeons = "boolean" }
ns.ITEM_FIELDS = { link = "string", q = "number", first = "number", last = "number", seen = "number",
    from = "table", inst = "number", handling = "string", note = "string" }
local ENCOUNTER_FIELDS = { name = "string", inst = "number", src = "string" }

local function KeepTyped(t, fields)
    for k, v in pairs(t) do
        if fields[k] ~= type(v) then t[k] = nil end
    end
end

-- Keeps only entries whose key and value have the given types (a table value is checked
-- with `fields` when given).
local function KeepMap(t, keyType, valueType, fields)
    for k, v in pairs(t) do
        if type(k) ~= keyType or type(v) ~= valueType then
            t[k] = nil
        elseif fields then
            KeepTyped(v, fields)
        end
    end
end

function ns.Repair(db)
    KeepTyped(db, DB_FIELDS)
    db.v = 1
    db.items = db.items or {}
    db.encounters = db.encounters or {}
    db.bossSources = db.bossSources or {}
    db.instances = db.instances or {}
    KeepMap(db.items, "number", "table", ns.ITEM_FIELDS)
    for _, item in pairs(db.items) do
        if item.from then KeepMap(item.from, "string", "number") end
    end
    KeepMap(db.encounters, "number", "table", ENCOUNTER_FIELDS)
    KeepMap(db.bossSources, "string", "number")
    KeepMap(db.instances, "number", "string")
    return db
end

ns.On("ADDON_LOADED", function(name)
    if name ~= ADDON then return end
    if type(NoctisLootCouncilDB) ~= "table" then NoctisLootCouncilDB = {} end
    ns.db = ns.Repair(NoctisLootCouncilDB)
end)

---------------------------------------------------------------------------
-- Names
---------------------------------------------------------------------------
-- Forever characters have a first name and a surname, unique together. UnitName returns
-- them as two values ("Vespera", "Ashward"); the second is not a realm. Chat shows "First
-- Last". Every name the addon compares goes through ns.NameKey, which accepts either form
-- (and drops a "-Realm" ending, should one ever appear), so the format a given API uses
-- can be settled in game without touching the rest.
function ns.PlayerName(unit)
    local first, last = UnitName(unit or "player")
    if not ns.Plain(first) then return nil end
    if ns.Plain(last) and last ~= "" then return first .. " " .. last end
    return first
end

function ns.NameKey(name)
    if not ns.Plain(name) or type(name) ~= "string" then return nil end
    name = name:gsub("%-.*$", ""):gsub("^%s+", ""):gsub("%s+$", "")
    if name == "" then return nil end
    return name:lower()
end

---------------------------------------------------------------------------
-- /nlc
---------------------------------------------------------------------------
-- Each file adds its own subcommands: ns.Command("loot", fn, L["help text"]). The help
-- lists them in the order they were added.
local commands, order = {}, {}

function ns.Command(name, fn, help)
    if not commands[name] then order[#order + 1] = name end
    commands[name] = { fn = fn, help = help }
end

local function Help()
    ns.Say(L["commands:"])
    for _, name in ipairs(order) do
        local c = commands[name]
        if c.help then print("  " .. ns.WHITE .. "/nlc " .. name .. "|r " .. c.help) end
    end
end

SLASH_NOCTISLOOTCOUNCIL1 = "/nlc"
SLASH_NOCTISLOOTCOUNCIL2 = "/noctisloot"
SlashCmdList.NOCTISLOOTCOUNCIL = function(msg)
    if not ns.db then return end
    local word, rest = (msg or ""):match("^%s*(%S*)%s*(.-)%s*$")
    local c = commands[word:lower()]
    if c then c.fn(rest) else Help() end
end
