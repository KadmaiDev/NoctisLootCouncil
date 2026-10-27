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
--   log = { award }, oldest first (Rolls.lua, Council.lua): { id = itemID, link, who = "First Last",
--         class = "WARLOCK"|nil, at = time(), how = "ms"|"ms2"|"os"|"council", roll|nil,
--         note = council reason or the winner's bid|nil, inst = raid name|nil, boss = boss name|nil,
--         nms, nos = how many wanted it main spec / off spec|nil }
--   drops = { { id = itemID, at = time(), src|nil, inst|nil, n = copies } }, -- each sighting that added to an item's count, for the bot to merge officers' uploads
--   night = time()|nil,                 -- /nlc newnight: wins before this don't count as tonight's
--   trialRanks = { "rank name", ... }|nil, -- guild ranks that are trials (nil = any rank with "trial" in its name)
--   me = "First Last",                  -- who last logged in with this file (for the companion app's uploads)
--   decisionsAt = time()|nil,           -- the newest decisions from Discord applied (Sync.lua)
--   scale = 0.5-3|nil,                  -- our windows' size (nil = EllesmereUI's Window Scale, else 1) (UI.lua)
--   council = { "First Last", ... }|nil, -- who votes on council items (Council.lua; the loot master's matters)
--   roles = { ["First Last"] = role }|nil, -- a character's chosen role for the upgrade % (Upgrades.lua)
--   popupOff = true|nil,                -- no Main spec / Off spec / Pass pop-up (Popup.lua)
--   autoOpenOff = true|nil,             -- the loot master's window doesn't open by itself (LootWindow.lua)
-- }
-- The companion app reads this file; its format is in NoctisLootBot's docs/sync-format.md.
-- Each field's type, so a damaged save is repaired at load instead of breaking things.
local DB_FIELDS = { v = "number", items = "table", encounters = "table", bossSources = "table",
    instances = "table", minQuality = "number", dungeons = "boolean", log = "table", night = "number",
    trialRanks = "table", drops = "table", me = "string", decisionsAt = "number", scale = "number",
    council = "table", roles = "table", popupOff = "boolean", autoOpenOff = "boolean" }
ns.ITEM_FIELDS = { link = "string", q = "number", first = "number", last = "number", seen = "number",
    from = "table", inst = "number", handling = "string", note = "string",
    slot = "string", sub = "string" }
local ENCOUNTER_FIELDS = { name = "string", inst = "number", src = "string" }
local LOG_FIELDS = { id = "number", link = "string", who = "string", class = "string", at = "number",
    how = "string", roll = "number", note = "string", inst = "string", boss = "string", nms = "number", nos = "number",
    tags = "string" }
local DROP_FIELDS = { id = "number", at = "number", src = "string", inst = "number", n = "number" }

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

-- A list with only the entries `keep` accepts, in order and without gaps.
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
    db.log = Compact(db.log or {}, function(e)
        if type(e) ~= "table" then return false end
        KeepTyped(e, LOG_FIELDS)
        return e.who ~= nil and e.at ~= nil and e.how ~= nil
    end)
    db.drops = Compact(db.drops or {}, function(d)
        if type(d) ~= "table" then return false end
        KeepTyped(d, DROP_FIELDS)
        return d.id ~= nil and d.at ~= nil and d.n ~= nil
    end)
    if db.trialRanks then
        db.trialRanks = Compact(db.trialRanks, function(r) return type(r) == "string" end)
    end
    if db.council then
        db.council = Compact(db.council, function(r) return type(r) == "string" end)
    end
    if db.roles then KeepMap(db.roles, "string", "string") end
    return db
end

ns.On("ADDON_LOADED", function(name)
    if name ~= ADDON then return end
    if type(NoctisLootCouncilDB) ~= "table" then NoctisLootCouncilDB = {} end
    ns.db = ns.Repair(NoctisLootCouncilDB)
end)

ns.On("PLAYER_LOGIN", function()
    if ns.db then ns.db.me = ns.PlayerName() or ns.db.me end
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
-- The group
---------------------------------------------------------------------------
-- The group's units: raid1..raidN in a raid, else the player and party1..4.
local function Units()
    local units = {}
    local n = GetNumGroupMembers and GetNumGroupMembers()
    if not ns.Plain(n) or type(n) ~= "number" then n = 0 end
    if IsInRaid and IsInRaid() then
        for i = 1, n do units[#units + 1] = "raid" .. i end
    else
        units[1] = "player"
        if IsInGroup and IsInGroup() then
            for i = 1, n - 1 do units[#units + 1] = "party" .. i end
        end
    end
    return units
end

-- The group member a name means: { name = "First Last", key, unit }, or nil if nobody in the
-- group has it. A first name alone (should some API give only that) matches when exactly one
-- member has that first name.
function ns.GroupMember(name)
    local key = ns.NameKey(name)
    if not key then return nil end
    local firstOnly = not key:find(" ", 1, true)
    local byFirst, firsts = nil, 0
    for _, unit in ipairs(Units()) do
        local full = ns.PlayerName(unit)
        local k = ns.NameKey(full)
        if k == key then return { name = full, key = k, unit = unit } end
        if k and firstOnly and k:match("^%S+") == key then
            byFirst, firsts = { name = full, key = k, unit = unit }, firsts + 1
        end
    end
    if firsts == 1 then return byFirst end
end

-- Posts a line in raid (or party) chat. Solo, or when the game won't let addons send chat,
-- it's shown to the player instead, so they can pass it on.
function ns.Announce(text)
    local chatType = (IsInRaid and IsInRaid() and "RAID") or (IsInGroup and IsInGroup() and "PARTY") or nil
    if not chatType then
        ns.Say(text)
        return true
    end
    local locked = C_ChatInfo and C_ChatInfo.InChatMessagingLockdown and C_ChatInfo.InChatMessagingLockdown()
    local send = C_ChatInfo and C_ChatInfo.SendChatMessage or SendChatMessage
    if not locked and send and pcall(send, text, chatType) then return true end
    ns.Say(L["Couldn't post this in group chat; please pass it on: %s"]:format(text))
    return false
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
