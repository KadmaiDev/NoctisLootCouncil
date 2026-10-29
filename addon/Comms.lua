-- Addon messages between our addons in the raid: the loot master's tells raiders' addons to
-- show the pop-up, raiders' send their council bids, the council's send votes.
--
-- Everything that decides loot still works without them: rolls are read from chat, and a
-- raider without the addon bids on a council item by rolling. Forever reports outgoing addon
-- messages as restricted (AreOutgoingAddonChatMessagesRestricted, measured in beta; what that
-- blocks was never measured), so every send is checked and a failure is told once.
--
-- A message is a kind and its fields, separated by tabs: "B\t12\tms\tBIS,Sidegrade\tnote".
-- Tabs and line breaks inside a field are escaped. Under 255 bytes, the game's limit.
--
-- Raid-wide (RAID or PARTY): the session start, the vote starting, and the end. Bids and
-- votes go by WHISPER to the loot master and each council member only, so other raiders'
-- addons never see them. They never go raid-wide: if a whisper can't be sent (the name format
-- Forever wants for a whisper isn't known yet), the sender is told, and a bid becomes a roll.
local ADDON, ns = ...
if ns.disabled then return end
local L = ns.L

local type, ipairs, select, concat, tostring = type, ipairs, select, table.concat, tostring
local Plain = ns.Plain

local PREFIX = "NoctisLC"
local MAX = 255

local handlers = {} -- [kind] = { fn(member, fields...) }
local warned = false

if C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix then
    pcall(C_ChatInfo.RegisterAddonMessagePrefix, PREFIX)
end

local function Escape(s)
    return (tostring(s or ""):gsub("\\", "\\\\"):gsub("\t", "\\t"):gsub("\n", "\\n"))
end

local function Unescape(s)
    return (s:gsub("\\(.)", function(c) return c == "t" and "\t" or c == "n" and "\n" or c end))
end

function ns.Encode(kind, ...)
    local parts = { kind }
    for i = 1, select("#", ...) do parts[#parts + 1] = Escape(select(i, ...)) end
    return concat(parts, "\t")
end

function ns.Decode(text)
    local fields = {}
    for field in (text .. "\t"):gmatch("(.-)\t") do fields[#fields + 1] = Unescape(field) end
    return fields
end

local function GroupChannel()
    if IsInRaid and IsInRaid() then return "RAID" end
    if IsInGroup and IsInGroup() then return "PARTY" end
end

local function Sent(result)
    if result == nil or result == true then return result == true or result == nil end
    local ok = Enum and Enum.SendAddonMessageResult and Enum.SendAddonMessageResult.Success or 0
    return result == ok
end

local function Raw(text, channel, target)
    if not (C_ChatInfo and C_ChatInfo.SendAddonMessage) or #text > MAX then return false end
    local ok, result = pcall(C_ChatInfo.SendAddonMessage, PREFIX, text, channel, target)
    return ok and Sent(result)
end

local function Failed()
    if warned then return end
    warned = true
    ns.Say(L["The game wouldn't send our addon's messages. Rolls still work from chat; council bids need raiders to roll instead."])
end

-- To the whole group. Returns whether it went.
function ns.Broadcast(kind, ...)
    local channel = GroupChannel()
    if not channel then return false end
    local ok = Raw(ns.Encode(kind, ...), channel)
    if not ok then Failed() end
    return ok
end

local function Deliver(m, fields)
    for _, fn in ipairs(handlers[fields[1]] or {}) do
        xpcall(fn, geterrorhandler(), m, unpack(fields, 2))
    end
end

local function Myself()
    return { name = ns.PlayerName(), key = ns.NameKey(ns.PlayerName()), unit = "player" }
end

-- To each of these names ("First Last"), privately, and never raid-wide. Returns the names
-- it couldn't reach, or nil if it reached them all.
function ns.SendTo(names, kind, ...)
    local text = ns.Encode(kind, ...)
    local me = ns.NameKey(ns.PlayerName())
    local toMe, done, missed = false, {}, nil
    for _, name in ipairs(names) do
        local key = ns.NameKey(name)
        if not key or done[key] then
            -- a name twice (the loot master on the council): once is enough
        elseif key == me then
            toMe = true -- to ourselves: no need for the network
        elseif not Raw(text, "WHISPER", name) then
            missed = missed or {}
            missed[#missed + 1] = name
        end
        if key then done[key] = true end
    end
    if toMe then Deliver(Myself(), ns.Decode(text)) end
    return missed
end

-- Could this group member be running the loot: the group's leader, an assistant, or the
-- master looter? Session messages (a roll or council starting, moving on, ending) only count
-- from them, so another raider's addon can't open pop-ups or steer the council. If the game
-- can't tell us, anyone can.
function ns.MayRunLoot(unit)
    if not unit then return false end
    if unit == "player" then return true end -- our own messages, back to us
    if not (UnitIsGroupLeader or UnitIsGroupAssistant) then return true end
    if UnitIsGroupLeader and UnitIsGroupLeader(unit) then return true end
    if UnitIsGroupAssistant and UnitIsGroupAssistant(unit) then return true end
    if GetLootMethod and UnitIsUnit then
        local ok, method, partyMaster, raidMaster = pcall(GetLootMethod)
        if ok and method == "master" then
            local master = raidMaster and "raid" .. raidMaster
                or partyMaster and (partyMaster == 0 and "player" or "party" .. partyMaster)
            if master and UnitIsUnit(unit, master) then return true end
        end
    end
    return false
end

function ns.OnMessage(kind, fn)
    handlers[kind] = handlers[kind] or {}
    handlers[kind][#handlers[kind] + 1] = fn
end

ns.On("CHAT_MSG_ADDON", function(prefix, text, _, sender)
    if not Plain(prefix) or prefix ~= PREFIX or not Plain(text) or not Plain(sender) or type(text) ~= "string" then return end
    local fields = ns.Decode(text)
    if not handlers[fields[1]] then return end
    -- Only group members count; ourselves too (raid-wide messages come back to us), as "player".
    local m
    if ns.NameKey(sender) == ns.NameKey(ns.PlayerName()) then m = Myself() else m = ns.GroupMember(sender) end
    if m then Deliver(m, fields) end
end)
