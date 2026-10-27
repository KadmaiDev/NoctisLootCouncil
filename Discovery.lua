-- Loot discovery: every item seen dropping in a raid goes into a list, with the boss it came
-- from, how often it has dropped, and how the guild handles it (council or roll, plus a note).
-- Forever's raid loot is hidden from data miners at launch, so nobody knows the drops in
-- advance: the list fills in as we raid, and the loot master is told when an item drops for
-- the first time, or what was decided for it last time.
--
-- Drops are seen three ways, each a fallback for the others:
--   * the loot window (LOOT_READY/LOOT_OPENED): exact, with the corpse or chest it came from,
--     but only for whoever opens it (the loot master, under master loot);
--   * "X receives loot: [item]" chat lines (CHAT_MSG_LOOT), seen by the whole raid;
--   * group loot roll windows (START_LOOT_ROLL) and ENCOUNTER_LOOT_RECEIVED.
-- A drop seen several ways counts once: per kill, an item's count is the most copies any one
-- way saw (two copies in the window, then two chat lines, is two drops, not four).
--
-- Which boss: ENCOUNTER_END (or BOSS_KILL) names the kill. The first corpse or chest with
-- loot worth recording that's opened within RECENT seconds of a kill is learned as that
-- boss's (db.bossSources), so later kills are recognised by the corpse alone. Chat lines
-- and roll windows within RECENT of a kill count as that boss's when the item is new or
-- already known to come from that boss; otherwise they're recorded without a source.
-- Nothing is assumed about which NPC is which boss, so obfuscated or new bosses work too.
local ADDON, ns = ...
if ns.disabled then return end
local L = ns.L

local GetTime, time, max, floor, tonumber, type, pairs, ipairs, next = GetTime, time, math.max, math.floor, tonumber, type, pairs, ipairs, next
local sort, concat = table.sort, table.concat
local GetInstanceInfo, GetNumLootItems, GetLootSlotType, GetLootSlotLink, GetLootSlotInfo, GetLootSourceInfo =
    GetInstanceInfo, GetNumLootItems, GetLootSlotType, GetLootSlotLink, GetLootSlotInfo, GetLootSourceInfo
local Plain = ns.Plain

local RECENT = 600       -- seconds after a kill in which loot counts as that boss's (council decisions take time)
local DEFAULT_QUALITY = 3 -- rare (blue) and up
local SLOT_ITEM = Enum and Enum.LootSlotType and Enum.LootSlotType.Item or 1

local kill       -- the last boss kill this session: { id, at = GetTime(), key, claimed }
local kills = {} -- per kill (or trash corpse): { [itemID] = { window, chat, roll, counted } }; session only
local told = {}  -- [kill key .. ":" .. itemID] = true once the loot master was told about it

function ns.MinQuality() return ns.db.minQuality or DEFAULT_QUALITY end

-- The instance ID if drops here are recorded: raids, and dungeons too with /nlc dungeons on.
local function Here()
    local name, instanceType, _, _, _, _, _, instanceID = GetInstanceInfo()
    if not Plain(instanceType) or not Plain(instanceID) or type(instanceID) ~= "number" then return nil end
    if instanceType ~= "raid" and not (ns.db.dungeons and instanceType == "party") then return nil end
    if Plain(name) and type(name) == "string" then ns.db.instances[instanceID] = name end
    return instanceID
end
ns.Here = Here

function ns.ItemID(link)
    if not Plain(link) or type(link) ~= "string" then return nil end
    return tonumber(link:match("item:(%d+)"))
end

function ns.ItemName(item)
    return item and item.link and item.link:match("%[(.-)%]") or "?"
end

-- Quality from what the caller knows, else the item cache, else the link's colour (the item
-- may not be cached yet, which is likely for loot nobody has seen before).
local COLOURS = { ["9d9d9d"] = 0, ffffff = 1, ["1eff00"] = 2, ["0070dd"] = 3, a335ee = 4, ff8000 = 5, e6cc80 = 6 }
local function Quality(itemID, link, known)
    if Plain(known) and type(known) == "number" and known >= 0 then return known end
    local q = C_Item and C_Item.GetItemQualityByID and C_Item.GetItemQualityByID(itemID)
    if Plain(q) and type(q) == "number" then return q end
    local iq = link:match("|cnIQ(%d+):")
    if iq then return tonumber(iq) end
    local hex = link:match("|c%x%x(%x%x%x%x%x%x)")
    return hex and COLOURS[hex:lower()]
end

-- Adds a sighting to the list. kind is "window" (n = copies in the window at once), "chat",
-- "roll" or "encounter" (one copy each). Returns the item and whether it was new.
local function Record(itemID, link, q, inst, src, killKey, kind, n)
    local db = ns.db
    local item = db.items[itemID]
    local new = not item or item.seen == 0 -- an item added unseen (/nlc council <link>) is new to our raids
    if not item then
        item = { first = time(), seen = 0 }
        db.items[itemID] = item
    end
    item.link = link -- the newest link: a name missing at first fills in once the item loads
    item.q = q or item.q
    item.last = time()
    item.inst = inst or item.inst
    if killKey then
        local k = kills[killKey] or {}
        kills[killKey] = k
        local c = k[itemID] or { counted = 0 }
        k[itemID] = c
        if kind == "window" then c.window = max(c.window or 0, n) else c[kind] = (c[kind] or 0) + 1 end
        local most = max(c.window or 0, c.chat or 0, c.roll or 0, c.encounter or 0)
        if most > c.counted then
            local add = most - c.counted
            c.counted = most
            item.seen = item.seen + add
            if src then
                item.from = item.from or {}
                item.from[src] = (item.from[src] or 0) + add
            end
        end
    end
    return item, new
end

local function BossName(src)
    local id = src and tonumber(src:match("^e(%d+)$"))
    local e = id and ns.db.encounters[id]
    return e and e.name
end

-- Tells the loot master about a drop, once per kill: how it's handled if that's decided
-- (perhaps before it ever dropped for us), else that it's new to our raids.
local function Tell(killKey, itemID, item, new, src)
    local key = killKey .. ":" .. itemID
    if told[key] then return end
    told[key] = true
    if item.handling then
        local how = item.handling == "council" and L["council item"] or L["roll item"]
        if item.note then how = how .. " · " .. item.note end
        ns.Say(("%s: %s"):format(item.link, how))
    elseif new then
        local from = BossName(src) or L["trash"]
        ns.Say(L["First time seen: %s from %s. New items are rolled; /nlc council makes it a council item from its next drop."]:format(item.link, from))
    end
end

---------------------------------------------------------------------------
-- Kills
---------------------------------------------------------------------------
local function Killed(id, name)
    if not Plain(id) or type(id) ~= "number" then return end
    if kill and kill.id == id and GetTime() - kill.at < 60 then return end -- ENCOUNTER_END and BOSS_KILL both fired
    local inst = Here()
    if not inst then return end
    local e = ns.db.encounters[id] or {}
    ns.db.encounters[id] = e
    if Plain(name) and type(name) == "string" and name ~= "" then e.name = name end
    e.inst = inst
    kill = { id = id, at = GetTime(), key = "k" .. id .. "@" .. floor(GetTime()) }
end

ns.On("ENCOUNTER_END", function(id, name, _, _, success)
    if Plain(success) and success == 1 then Killed(id, name) end
end)
ns.On("BOSS_KILL", Killed)

local function RecentKill()
    if kill and GetTime() - kill.at < RECENT then return kill end
end

---------------------------------------------------------------------------
-- The loot window
---------------------------------------------------------------------------
-- The source key and kill key for a corpse or chest GUID.
local function Source(guid)
    if not Plain(guid) or type(guid) ~= "string" then return nil, nil end
    local kind, id = guid:match("^(%a+)%-%d+%-%d+%-%d+%-%d+%-(%d+)%-")
    local src
    if kind == "Creature" or kind == "Vehicle" then
        src = "n" .. id
    elseif kind == "GameObject" then
        src = "o" .. id
    else
        return nil, guid
    end
    local db = ns.db
    local boss = db.bossSources[src]
    local k = RecentKill()
    if not boss and k and not k.claimed then
        local e = db.encounters[k.id]
        if e and not e.src then
            boss, e.src, db.bossSources[src] = k.id, src, k.id
        end
    end
    if not boss then return src, guid end
    if k and k.id == boss then
        k.claimed = true
        return "e" .. boss, k.key
    end
    return "e" .. boss, guid -- a boss opened long after its kill: the corpse is the kill
end

local function ReadLootWindow()
    if not ns.db then return end
    local inst = Here()
    if not inst then return end
    local n = GetNumLootItems()
    if not Plain(n) or type(n) ~= "number" then return end
    local minQ = ns.MinQuality()
    local found = {} -- [guid] = { [itemID] = { link, q, n } }
    for slot = 1, n do
        if GetLootSlotType(slot) == SLOT_ITEM then
            local link = GetLootSlotLink(slot)
            local itemID = ns.ItemID(link)
            local _, _, _, _, quality = GetLootSlotInfo(slot)
            local q = itemID and Quality(itemID, link, quality)
            if q and q >= minQ then
                local guid = GetLootSourceInfo(slot)
                if not Plain(guid) or type(guid) ~= "string" then guid = "?" end
                local list = found[guid] or {}
                found[guid] = list
                local seen = list[itemID] or { link = link, q = q, n = 0 }
                list[itemID] = seen
                seen.n = seen.n + 1
            end
        end
    end
    for guid, list in pairs(found) do
        local src, killKey = Source(guid ~= "?" and guid or nil)
        killKey = killKey or ("window@" .. GetTime())
        for itemID, seen in pairs(list) do
            local item, new = Record(itemID, seen.link, seen.q, inst, src, killKey, "window", seen.n)
            Tell(killKey, itemID, item, new, src)
        end
    end
end
ns.On("LOOT_READY", ReadLootWindow)
ns.On("LOOT_OPENED", ReadLootWindow)

---------------------------------------------------------------------------
-- Chat, roll windows and encounter loot
---------------------------------------------------------------------------
-- "%s receives loot: %s." and friends, as Lua patterns, from the client's own text so any
-- language works. Only receipts count: group loot also prints a line per roll and choice.
local function Pattern(text)
    if type(text) ~= "string" then return nil end
    text = text:gsub("%%%d%$", "%%")                    -- "%1$s" -> "%s"
    text = text:gsub("([%(%)%.%+%-%*%?%[%]%^%$])", "%%%1") -- escape magic characters ("%" stays)
    text = text:gsub("%%s", "(.+)"):gsub("%%d", "(%%d+)")
    return "^" .. text .. "$"
end
local RECEIPTS
local function Receipts()
    if not RECEIPTS then
        RECEIPTS = {}
        for _, name in ipairs({ "LOOT_ITEM", "LOOT_ITEM_MULTIPLE", "LOOT_ITEM_SELF", "LOOT_ITEM_SELF_MULTIPLE" }) do
            RECEIPTS[#RECEIPTS + 1] = Pattern(_G[name])
        end
    end
    return RECEIPTS
end
ns.ChatPattern = Pattern

-- A drop seen without its corpse: the recent kill's, if the item is new or known to come
-- from that boss; otherwise just noted.
local function Sighting(link, kind, knownQuality, encounterID)
    if not ns.db then return end
    local inst = Here()
    local itemID = ns.ItemID(link)
    if not inst or not itemID then return end
    local q = Quality(itemID, link, knownQuality)
    if not q or q < ns.MinQuality() then return end
    local k = RecentKill()
    local src, killKey
    if encounterID then
        src = "e" .. encounterID
        killKey = (k and k.id == encounterID) and k.key or ("k" .. encounterID .. "@late")
    elseif k then
        local item = ns.db.items[itemID]
        if not item or (item.from and item.from["e" .. k.id]) then src, killKey = "e" .. k.id, k.key end
    end
    Record(itemID, link, q, inst, src, killKey, kind)
end

ns.On("CHAT_MSG_LOOT", function(text)
    if not Plain(text) or type(text) ~= "string" then return end
    for _, p in ipairs(Receipts()) do
        if text:find(p) then
            Sighting(text:match("|c.-|H.-|h.-|h|r") or text, "chat")
            return
        end
    end
end)

ns.On("START_LOOT_ROLL", function(rollID)
    if not Plain(rollID) or not GetLootRollItemLink then return end
    local link = GetLootRollItemLink(rollID)
    local _, _, _, quality = GetLootRollItemInfo(rollID)
    if Plain(link) then Sighting(link, "roll", quality) end
end)

ns.On("ENCOUNTER_LOOT_RECEIVED", function(encounterID, _, link)
    if Plain(encounterID) and type(encounterID) == "number" and Plain(link) then
        Sighting(link, "encounter", nil, encounterID)
    end
end)

---------------------------------------------------------------------------
-- The list, and deciding how items are handled
---------------------------------------------------------------------------
-- Finds a listed item from a command's text: a shift-clicked link, an item ID, or the start
-- of an item's name (the longest listed name the text starts with). Returns the item ID,
-- the item and the rest of the text.
function ns.FindItem(text)
    local items = ns.db.items
    local id, rest = text:match("^|c.-|Hitem:(%d+).-|h|r%s*(.*)$")
    if not id then id, rest = text:match("^(%d+)%s*(.*)$") end
    if id then
        id = tonumber(id)
        return id, items[id], rest
    end
    local lower, best, bestLen = text:lower(), nil, 0
    for itemID, item in pairs(items) do
        local name = ns.ItemName(item):lower()
        local after = lower:sub(#name + 1, #name + 1)
        if #name > bestLen and lower:sub(1, #name) == name and (after == "" or after == " ") then
            best, bestLen = itemID, #name
        end
    end
    if best then return best, items[best], (text:sub(bestLen + 1):gsub("^%s+", "")) end
end

-- Most loot will be known from other guilds' kills and the community's lists before it drops
-- for us, so it can be decided in advance: a link or an item ID adds an item we haven't seen
-- (seen = 0). Given an ID the game hasn't loaded yet, the link fills in when it arrives.
local waiting = {} -- [itemID] = true while the game loads an added item

local function LoadLink(id)
    local item = ns.db.items[id]
    if not item or item.link:find("|H", 1, true) then return true end
    local GetInfo = C_Item and C_Item.GetItemInfo or GetItemInfo
    if not GetInfo then return true end
    local _, link, q = GetInfo(id)
    if not Plain(link) or type(link) ~= "string" then return false end
    item.link = link
    if Plain(q) and type(q) == "number" then item.q = q end
    return true
end

ns.On("GET_ITEM_INFO_RECEIVED", function(id)
    if Plain(id) and waiting[id] and ns.db and LoadLink(id) then waiting[id] = nil end
end)

-- Like ns.FindItem, but a link or an item ID not in the list is added to it.
local function FindOrAdd(text)
    local id, item, rest = ns.FindItem(text)
    if item or not id then return id, item, rest end
    local link = text:match("^|c.-|h|r")
    item = { first = time(), seen = 0, link = link or ("item:" .. id) }
    if link then item.q = Quality(id, link) end
    ns.db.items[id] = item
    if not link and not LoadLink(id) then
        waiting[id] = true
        if C_Item and C_Item.RequestLoadItemDataByID then C_Item.RequestLoadItemDataByID(id) end
    end
    ns.Say(L["Added %s to the list (not seen in our raids yet)."]:format(item.link))
    return id, item, rest
end

local function Decide(handling)
    return function(text)
        local id, item, rest = FindOrAdd(text)
        if not item then
            ns.Say(L["Not in the list: %s. Shift-click the item, or use its ID or name."]:format(text))
            return
        end
        item.handling = handling
        if rest ~= "" then item.note = rest end
        if handling == "council" then
            ns.Say(L["%s is a council item."]:format(item.link))
        elseif handling == "roll" then
            ns.Say(L["%s is a roll item."]:format(item.link))
        else
            ns.Say(L["%s: not decided."]:format(item.link))
        end
    end
end

-- The list as lines, grouped by where items come from: bosses by instance and name, then
-- items with no known boss, then items decided before we've seen them drop. filter keeps
-- items whose name contains it.
function ns.LootLines(filter)
    local db = ns.db
    filter = filter and filter ~= "" and filter:lower() or nil
    local groups, order = {}, {}
    for itemID, item in pairs(db.items) do
        if not filter or ns.ItemName(item):lower():find(filter, 1, true) then
            local best, bestN = nil, 0
            for src, n in pairs(item.from or {}) do
                if src:find("^e") and n > bestN then best, bestN = src, n end
            end
            local key = best or (item.seen == 0 and "unseen") or "trash"
            if not groups[key] then
                groups[key] = {}
                order[#order + 1] = key
            end
            local g = groups[key]
            g[#g + 1] = item
        end
    end
    local function Label(key)
        if key == "trash" then return L["No known boss"] end
        if key == "unseen" then return L["Not seen in our raids yet"] end
        local e = db.encounters[tonumber(key:sub(2))] or {}
        local inst = e.inst and db.instances[e.inst]
        return (inst and inst .. " · " or "") .. (e.name or key)
    end
    local LAST = { trash = 1, unseen = 2 } -- bosses first, by name
    sort(order, function(a, b)
        if LAST[a] or LAST[b] then return (LAST[a] or 0) < (LAST[b] or 0) end
        return Label(a) < Label(b)
    end)
    local lines = {}
    for _, key in ipairs(order) do
        lines[#lines + 1] = ns.GOLD .. Label(key) .. "|r"
        local g = groups[key]
        sort(g, function(a, b)
            if (a.q or 0) ~= (b.q or 0) then return (a.q or 0) > (b.q or 0) end
            return ns.ItemName(a) < ns.ItemName(b)
        end)
        for _, item in ipairs(g) do
            local parts = { "  " .. item.link, "×" .. item.seen }
            if item.handling == "council" then parts[#parts + 1] = L["council"]
            elseif item.handling == "roll" then parts[#parts + 1] = L["roll"] end
            if item.note then parts[#parts + 1] = item.note end
            lines[#lines + 1] = concat(parts, " · ")
        end
    end
    return lines
end

ns.Command("loot", function(filter)
    local lines = ns.LootLines(filter)
    if #lines == 0 then
        ns.Say(filter ~= "" and L["No listed item matches \"%s\"."]:format(filter) or L["No raid drops seen yet."])
        return
    end
    ns.Say(L["raid drops seen:"])
    for _, line in ipairs(lines) do print(line) end
end, L["[text]: list every raid drop seen, by boss"])

ns.Command("council", Decide("council"), L["<item> [note]: make it a council item"])
ns.Command("roll", Decide("roll"), L["<item> [note]: make it a roll item"])
ns.Command("undecided", Decide(nil), L["<item>: neither"])

ns.Command("note", function(text)
    local _, item, rest = FindOrAdd(text)
    if not item then
        ns.Say(L["Not in the list: %s. Shift-click the item, or use its ID or name."]:format(text))
        return
    end
    item.note = rest ~= "" and rest or nil
    ns.Say(item.note and L["Note for %s: %s"]:format(item.link, item.note) or L["Note for %s removed."]:format(item.link))
end, L["<item> [text]: a note shown when it drops, e.g. Hunter priority"])

ns.Command("forget", function(text)
    local id, item = ns.FindItem(text)
    if not item then
        ns.Say(L["Not in the list: %s. Shift-click the item, or use its ID or name."]:format(text))
        return
    end
    ns.db.items[id] = nil
    ns.Say(L["Removed %s from the list."]:format(item.link))
end, L["<item>: remove it from the list"])

ns.Command("quality", function(text)
    local q = tonumber(text)
    if q and q >= 0 and q <= 5 and q == floor(q) then
        ns.db.minQuality = q ~= DEFAULT_QUALITY and q or nil
    end
    local name = _G["ITEM_QUALITY" .. ns.MinQuality() .. "_DESC"] or tostring(ns.MinQuality())
    ns.Say(L["Recording drops of quality %d (%s) and up."]:format(ns.MinQuality(), name))
end, L["[0-5]: lowest quality recorded (3 = rare, 4 = epic)"])

ns.Command("dungeons", function(text)
    text = text:lower()
    if text == "on" then ns.db.dungeons = true elseif text == "off" then ns.db.dungeons = nil end
    ns.Say(ns.db.dungeons and L["Recording drops in raids and dungeons."] or L["Recording drops in raids only."])
end, L["on|off: record dungeon drops too (for trying it out)"])
