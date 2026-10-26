-- A small fake of the WoW: Forever client API, just enough to load Noctis Loot Council outside
-- the game: frames and events, slash commands, the instance, the loot window, loot chat and
-- roll windows. It encodes what we believe the client does; Forever's raids can't be checked
-- until launch, so every assumption here is one to confirm in game.
local M = {}

local KNOWN_EVENTS = {
    ADDON_LOADED = true, PLAYER_LOGIN = true, ENCOUNTER_END = true, BOSS_KILL = true,
    LOOT_READY = true, LOOT_OPENED = true, CHAT_MSG_LOOT = true, START_LOOT_ROLL = true,
    ENCOUNTER_LOOT_RECEIVED = true,
}

-- A secret value: issecretvalue says so, and using it the ways the game forbids throws.
local function forbidden() error("attempt to use a secret value", 2) end
M.SECRET = setmetatable({}, { __index = forbidden, __eq = forbidden, __lt = forbidden, __le = forbidden,
    __concat = forbidden, __len = forbidden, __call = forbidden })

-- An item link as the client makes one. quality picks the colour.
local HEX = { [0] = "9d9d9d", "ffffff", "1eff00", "0070dd", "a335ee", "ff8000" }
function M.link(id, name, quality)
    return ("|cff%s|Hitem:%d::::::::60:::::::::|h[%s]|h|r"):format(HEX[quality or 4], id, name)
end

-- A creature GUID for an NPC ID (the spawn part is made unique per call).
local spawn = 0
function M.npc(npcID)
    spawn = spawn + 1
    return ("Creature-0-4170-409-12345-%d-%010X"):format(npcID, spawn)
end
function M.object(objectID)
    spawn = spawn + 1
    return ("GameObject-0-4170-409-12345-%d-%010X"):format(objectID, spawn)
end

function M.load(files, addonName)
    NoctisLootCouncilRunning, NoctisLootCouncilDB = nil, M.saved
    M.saved = nil
    for k in pairs(_G) do
        if type(k) == "string" and k:find("^SLASH_") then _G[k] = nil end
    end
    M.frames, M.printed, M.now, M.clock = {}, {}, 0, 1790000000
    M.instance = { "Molten Core", "raid", 9, "40 Player", 40, 0, false, 409 }
    M.loot = {}      -- the open loot window: { { link, quality, guid } or { money = true } }
    M.rolls = {}     -- [rollID] = { link, quality }
    M.qualities = {} -- [itemID] = quality the item cache knows (nil = not cached)
    M.player = { "Kadmai", "Moonwhisper" }

    wipe = function(t) for k in pairs(t) do t[k] = nil end return t end
    print = function(msg) M.printed[#M.printed + 1] = msg end
    geterrorhandler = function() return function(err) error(err, 0) end end
    issecretvalue = function(x) return x == nil and false or rawequal(x, M.SECRET) end
    GetTime = function() return M.now end
    time = function() return M.clock + math.floor(M.now) end
    UnitName = function() return M.player[1], M.player[2] end
    SlashCmdList = {}
    Enum = { LootSlotType = { None = 0, Item = 1, Money = 2, Currency = 3 } }
    ITEM_QUALITY3_DESC, ITEM_QUALITY4_DESC = "Rare", "Epic"
    LOOT_ITEM = "%s receives loot: %s."
    LOOT_ITEM_MULTIPLE = "%s receives loot: %sx%d."
    LOOT_ITEM_SELF = "You receive loot: %s."
    LOOT_ITEM_SELF_MULTIPLE = "You receive loot: %sx%d."
    LOOT_ROLL_NEED = "%s has selected Need for: %s"

    GetInstanceInfo = function() return unpack(M.instance) end
    GetNumLootItems = function() return #M.loot end
    GetLootSlotType = function(slot)
        local s = M.loot[slot]
        if not s then return 0 end
        return s.money and 2 or 1
    end
    GetLootSlotLink = function(slot) local s = M.loot[slot] return s and not s.money and s[1] or nil end
    GetLootSlotInfo = function(slot)
        local s = M.loot[slot]
        if not s then return nil end
        return 134400, "item", 1, nil, s[2] or 4, false, false, nil, true, s.money or false
    end
    GetLootSourceInfo = function(slot) local s = M.loot[slot] return s and s[3], 1 end
    GetLootRollItemLink = function(id) return M.rolls[id] and M.rolls[id][1] end
    GetLootRollItemInfo = function(id)
        local r = M.rolls[id]
        if r then return 134400, "item", 1, r[2] or 4, false end
    end
    C_Item = { GetItemQualityByID = function(id) return M.qualities[id] end }

    local frameMethods = {}
    local function ignored(self) return self end
    local meta = { __index = function(_, k)
        if type(k) ~= "string" or not k:match("^%u") then return nil end
        return frameMethods[k] or ignored
    end }
    local function newObject(kind, name)
        local f = setmetatable({ kind = kind, events = {}, scripts = {}, shown = true, name = name }, meta)
        if name then _G[name] = f end
        M.frames[#M.frames + 1] = f
        return f
    end
    function frameMethods:RegisterEvent(event)
        if not KNOWN_EVENTS[event] then error("Attempt to register unknown event \"" .. event .. "\"") end
        self.events[event] = true
    end
    function frameMethods:SetScript(script, fn) self.scripts[script] = fn end
    CreateFrame = function(kind, name) return newObject(kind, name) end

    local ns = {}
    for _, file in ipairs(files) do assert(loadfile(file))(addonName or "NoctisLootCouncil", ns) end
    M.ns = ns
    return ns
end

function M.fire(event, ...)
    for _, f in ipairs(M.frames) do
        if f.events[event] and f.scripts.OnEvent then f.scripts.OnEvent(f, event, ...) end
    end
end

function M.login()
    M.fire("ADDON_LOADED", "NoctisLootCouncil")
    M.fire("PLAYER_LOGIN")
end

-- Moves the clock on.
function M.wait(seconds) M.now = M.now + seconds end

-- A boss dies.
function M.kill(encounterID, name)
    M.fire("ENCOUNTER_END", encounterID, name, 9, 40, 1)
end

-- Opens a loot window with these slots ({ link, quality, guid }).
function M.open(slots)
    M.loot = slots
    M.fire("LOOT_READY", false)
    M.fire("LOOT_OPENED", false, false)
end

function M.close() M.loot = {} end

-- Someone receives an item, as the chat line everyone in the group sees.
function M.receives(who, link)
    M.fire("CHAT_MSG_LOOT", LOOT_ITEM:format(who, link), "", "", "", who, "", 0, 0, "", 0, 1, nil, 0, false, false)
end

function M.type(line)
    local cmd, rest = line:match("^(/%S+)%s*(.*)$")
    for name, fn in pairs(SlashCmdList) do
        local i = 1
        while _G["SLASH_" .. name .. i] do
            if _G["SLASH_" .. name .. i]:lower() == cmd:lower() then return fn(rest) end
            i = i + 1
        end
    end
    error("no slash command " .. cmd)
end

return M
