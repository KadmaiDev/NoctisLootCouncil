-- A small fake of the WoW: Forever client API, just enough to load Noctis Loot Council outside
-- the game: frames and events, slash commands, the instance, the loot window, loot chat and
-- roll windows. It encodes what we believe the client does; Forever's raids can't be checked
-- until launch, so every assumption here is one to confirm in game.
local M = {}

local KNOWN_EVENTS = {
    ADDON_LOADED = true, PLAYER_LOGIN = true, ENCOUNTER_END = true, BOSS_KILL = true,
    LOOT_READY = true, LOOT_OPENED = true, CHAT_MSG_LOOT = true, START_LOOT_ROLL = true,
    ENCOUNTER_LOOT_RECEIVED = true, CHAT_MSG_SYSTEM = true, GET_ITEM_INFO_RECEIVED = true,
    CHAT_MSG_ADDON = true, PLAYER_ENTERING_WORLD = true, TRAIT_CONFIG_UPDATED = true,
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
    for _, f in ipairs(M.frames or {}) do -- the last load's named frames
        if f.name then _G[f.name] = nil end
    end
    M.frames, M.printed, M.now, M.clock = {}, {}, 0, 1790000000
    M.instance = { "Molten Core", "raid", 9, "40 Player", 40, 0, false, 409 }
    M.loot = {}      -- the open loot window: { { link, quality, guid } or { money = true } }
    M.rolls = {}     -- [rollID] = { link, quality }
    M.qualities = {} -- [itemID] = quality the item cache knows (nil = not cached)
    M.cache = {}     -- [itemID] = { name, quality }: items the client has loaded (GetItemInfo answers)
    M.requested = {} -- item IDs the addon asked the client to load
    M.player = { "Kadmai", "Moonwhisper", guild = "Noctis", rank = "Officer", class = "HUNTER" }
    M.group = {}     -- the group, the player first (raid1 / player, then raid2 / party1, ...); empty = solo
    M.inRaid = false
    M.timers = {}    -- { at, fn }, run by M.wait
    M.sent = {}      -- chat lines the addon sent: { text, chatType }
    M.lockdown = false

    wipe = function(t) for k in pairs(t) do t[k] = nil end return t end
    print = function(msg) M.printed[#M.printed + 1] = msg end
    geterrorhandler = function() return function(err) error(err, 0) end end
    issecretvalue = function(x) return x == nil and false or rawequal(x, M.SECRET) end
    GetTime = function() return M.now end
    time = function() return M.clock + math.floor(M.now) end
    local function Unit(unit)
        if unit == "player" then return M.player end
        local kind, i = unit:match("^(%a+)(%d+)$")
        i = tonumber(i)
        if kind == "raid" and M.inRaid then return M.group[i] end
        if kind == "party" and not M.inRaid then return M.group[i + 1] end
    end
    UnitName = function(unit)
        local u = Unit(unit)
        if u then return u[1], u[2] end
    end
    UnitClass = function(unit)
        local u = Unit(unit)
        if u and u.class then return u.class:sub(1, 1) .. u.class:sub(2):lower(), u.class, 1 end
    end
    date = os.date
    NoctisLootDecisions = nil
    GetGuildInfo = function(unit)
        local u = Unit(unit)
        if u and u.guild then return u.guild, u.rank, 1 end
    end
    M.leader = false
    -- Others lead or assist with leader = true or assist = true on their member table.
    UnitIsGroupLeader = function(unit)
        if unit == "player" then return M.leader end
        local u = Unit(unit)
        return u and u.leader or false
    end
    UnitIsGroupAssistant = function(unit)
        local u = Unit(unit)
        return u and u.assist or false
    end
    IsInRaid = function() return M.inRaid end
    IsInGroup = function() return #M.group > 0 end
    GetNumGroupMembers = function() return #M.group end
    C_Timer = { After = function(seconds, fn) M.timers[#M.timers + 1] = { at = M.now + seconds, fn = fn } end }
    C_ChatInfo = {
        InChatMessagingLockdown = function() return M.lockdown end,
        SendChatMessage = function(text, chatType)
            assert(#text <= 255, "chat line over 255 characters")
            M.sent[#M.sent + 1] = { text, chatType }
        end,
        RegisterAddonMessagePrefix = function(prefix) assert(#prefix <= 16) return 0 end,
        -- Recorded; raid and party messages come back to the sender, as in the game.
        -- M.addonResult (else 0, success) is what the game answers; M.whisperFails makes
        -- whispers fail (the name format a whisper wants on Forever isn't known).
        SendAddonMessage = function(prefix, text, channel, target)
            assert(#text <= 255, "addon message over 255 bytes")
            if M.addonResult and M.addonResult ~= 0 then return M.addonResult end
            if channel == "WHISPER" and M.whisperFails then return 9 end
            M.addon[#M.addon + 1] = { prefix = prefix, text = text, channel = channel, target = target }
            if channel == "RAID" or channel == "PARTY" then
                M.fire("CHAT_MSG_ADDON", prefix, text, channel, M.player[1] .. " " .. M.player[2], "", 0, 0, "", 0)
            end
            return 0
        end,
    }
    M.addon = {}       -- addon messages sent: { prefix, text, channel, target }
    M.addonResult, M.whisperFails = nil, nil
    M.nextRoll = 50    -- what RandomRoll rolls
    M.rolled = nil     -- the last RandomRoll's { low, high }
    RandomRoll = function(low, high)
        M.rolled = { low, high }
        M.fire("CHAT_MSG_SYSTEM", RANDOM_ROLL_RESULT:format(M.player[1] .. " " .. M.player[2], M.nextRoll, low, high))
    end
    M.gear = {}        -- [slot] = item link the player wears
    M.stats = {}       -- [itemID] = { ITEM_MOD_..._SHORT = value }
    GetInventoryItemLink = function(unit, slot) if unit == "player" then return M.gear[slot] end end
    RANDOM_ROLL_RESULT = "%s rolls %d (%d-%d)"
    SlashCmdList = {}
    Enum = { LootSlotType = { None = 0, Item = 1, Money = 2, Currency = 3 }, LootMethod = { Freeforall = 0, Masterlooter = 2 } }
    -- The master looter: M.masterLooter = { party = n } or { raid = n } (Forever's IDs).
    M.masterLooter = nil
    C_PartyInfo = { GetLootMethod = function()
        local ml = M.masterLooter
        if not ml then return Enum.LootMethod.Freeforall end
        return Enum.LootMethod.Masterlooter, ml.party, ml.raid
    end }
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
    C_Item = {
        GetItemQualityByID = function(id) return M.qualities[id] end,
        GetItemInfo = function(id)
            local c = M.cache[id]
            if c then return c[1], M.link(id, c[1], c[2]), c[2] end
        end,
        RequestLoadItemDataByID = function(id) M.requested[#M.requested + 1] = id end,
        -- itemID, type, subtype, equip location (from M.equip), as the client answers for any
        -- item ID even when it isn't cached.
        GetItemInfoInstant = function(item)
            local id = tonumber(tostring(item):match("item:(%d+)") or item)
            local e = id and M.equip[id]
            if e then return id, e[1], e[2], e[3], 134400, e.class or 4, e.sub or 1 end
            return id
        end,
        GetItemStats = function(link)
            local id = tonumber(tostring(link):match("item:(%d+)"))
            local s = id and M.stats[id]
            if not s then return nil end
            local copy = {}
            for k, v in pairs(s) do copy[k] = v end
            return copy
        end,
    }
    M.equip = {}     -- [itemID] = { type, subtype, equipLoc, class = classID, sub = subclassID }
    Enum.SendAddonMessageResult = { Success = 0, GeneralError = 9 }

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
    function frameMethods:GetScript(script) return self.scripts[script] end
    function frameMethods:HookScript(script, fn)
        self.hooks = self.hooks or {}
        self.hooks[script] = self.hooks[script] or {}
        table.insert(self.hooks[script], fn)
    end
    -- Runs a script and its hooks, as the client does.
    function frameMethods:Run(script, ...)
        if self.scripts[script] then self.scripts[script](self, ...) end
        for _, fn in ipairs(self.hooks and self.hooks[script] or {}) do fn(self, ...) end
    end
    function frameMethods:Show()
        if self.shown then return end
        self.shown = true
        self:Run("OnShow")
    end
    function frameMethods:Hide()
        if not self.shown then return end
        self.shown = false
        self:Run("OnHide")
    end
    function frameMethods:SetShown(on) if on then self:Show() else self:Hide() end end
    function frameMethods:IsShown() return self.shown end
    function frameMethods:IsVisible() return self.shown and (not self.parent or self.parent:IsVisible()) end
    function frameMethods:SetText(text) self.text = text end
    function frameMethods:GetText() return self.text end
    function frameMethods:SetFormattedText(fmt, ...) self.text = fmt:format(...) end
    function frameMethods:SetScale(s) self.scale = s end
    function frameMethods:GetScale() return self.scale or 1 end
    function frameMethods:GetParent() return self.parent end
    function frameMethods:Enable() self.disabled = nil end
    function frameMethods:Disable() self.disabled = true end
    function frameMethods:SetEnabled(on) self.disabled = not on or nil end
    function frameMethods:IsEnabled() return not self.disabled end
    function frameMethods:SetChecked(on) self.checked = on and true or false end
    function frameMethods:GetChecked() return self.checked end
    function frameMethods:GetRegions() end
    function frameMethods:GetCenter() end
    function frameMethods:GetPoint() end
    function frameMethods:GetFont() end
    function frameMethods:Click(...) if not self.disabled then self:Run("OnClick", ...) end end
    function frameMethods:CreateFontString() local o = newObject("FontString") o.parent = self return o end
    function frameMethods:CreateTexture() local o = newObject("Texture") o.parent = self return o end
    CreateFrame = function(kind, name, parent, template)
        local f = newObject(kind, name)
        f.parent = parent
        if template == "BasicFrameTemplateWithInset" then
            f.TitleText = f:CreateFontString()
            f.CloseButton = newObject("Button")
            f.CloseButton.parent = f
            f.Inset = newObject("Frame")
        end
        -- Frames start shown, as in the game; a window hides itself after it's built.
        return f
    end
    UIParent = newObject("Frame", "UIParent")
    UISpecialFrames = {}
    hooksecurefunc = function() end

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

-- Moves the clock on, running timers that come due on the way, in order.
function M.wait(seconds)
    local stop = M.now + seconds
    while true do
        local next, at
        for i, t in ipairs(M.timers) do
            if t.at <= stop and (not at or t.at < at) then next, at = i, t.at end
        end
        if not next then break end
        local t = table.remove(M.timers, next)
        M.now = t.at
        t.fn()
    end
    M.now = stop
end

-- Puts the player in a raid with these members ({ "First", "Last", rank = "Member" }; guild
-- Noctis unless guild is given, or guild = false for someone outside it).
function M.raid(members)
    M.inRaid = true
    M.group = { M.player }
    for _, m in ipairs(members) do
        if m.guild == nil then m.guild = "Noctis" elseif m.guild == false then m.guild = nil end
        M.group[#M.group + 1] = m
    end
end

-- The client finishes loading an item (as after RequestLoadItemDataByID).
function M.itemLoads(id, name, quality)
    M.cache[id] = { name, quality or 4 }
    M.fire("GET_ITEM_INFO_RECEIVED", id, true)
end

-- Someone's roll, as the system line everyone in the group sees.
function M.roll(who, roll, max, min)
    M.fire("CHAT_MSG_SYSTEM", RANDOM_ROLL_RESULT:format(who, roll, min or 1, max or 100), "", "", "", "", "", 0, 0, "", 0, 1, nil, 0)
end

-- An addon message from another player's copy of the addon (fields as the addon encodes them).
function M.message(who, channel, kind, ...)
    M.fire("CHAT_MSG_ADDON", "NoctisLC", M.ns.Encode(kind, ...), channel, who, "", 0, 0, "", 0)
end

-- The addon messages sent, decoded: { kind, fields..., channel = , target = }.
function M.messages(kind)
    local out = {}
    for _, a in ipairs(M.addon) do
        local f = M.ns.Decode(a.text)
        if not kind or f[1] == kind then
            f.channel, f.target = a.channel, a.target
            out[#out + 1] = f
        end
    end
    return out
end

-- Every chat line sent so far, joined.
function M.said()
    local out = {}
    for _, s in ipairs(M.sent) do out[#out + 1] = s[1] end
    return table.concat(out, "\n")
end

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
