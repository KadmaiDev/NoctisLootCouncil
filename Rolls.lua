-- Rolls: the loot master starts a roll for an item, the raid rolls, and the addon picks the
-- winner by the guild's rules and announces it. It runs on the loot master's client from chat
-- alone (the announcement in raid chat, the rolls as the system lines everyone sees), so it
-- works for raiders without the addon and if the game blocks addon messages.
--
-- One round, the kind of roll told apart by its range: /roll (1-100) is main spec, /roll 99
-- (1-99) off spec. The order is the rules' tiers, so one round gives the same winner as
-- rolling each tier in turn:
--   1. main spec, no main-spec win tonight
--   2. main spec, already won one tonight ("second main spec")
--   3. off spec
-- Within a tier a member beats a trial (trials win only if no member rolled in that tier),
-- then the highest roll wins. A tie for first is re-rolled by those tied, in their tier.
-- Each player's first roll counts. Rolls outside a round, or of other ranges, don't.
local ADDON, ns = ...
if ns.disabled then return end
local L = ns.L

local time, tonumber, tostring, type, ipairs, pairs = time, tonumber, tostring, type, ipairs, pairs
local sort, concat = table.sort, table.concat
local Plain = ns.Plain

local DURATION = 30      -- seconds to roll
local NIGHT = 12 * 3600  -- a win counts as tonight's for this long (or until /nlc newnight)
local MS, OS = 100, 99   -- the top of each kind of roll

local HOW = { "ms", "ms2", "os" }
local function TierName(tier)
    return tier == 1 and L["main spec"] or tier == 2 and L["second main spec"] or L["off spec"]
end

local WARN = 10          -- seconds left when raid chat is reminded

-- The roll running now: { link, id, sid, round, tied = { [key] = true }|nil, rolls = { [key] = entry },
-- only = { [key] = true }|nil (a roll-off: only these count, all as equals), onAward = fn|nil }
local current
local token = 0  -- each round's timer checks it's still the round it was started for
local sessions = 0

-- A number for each roll or council session, so raiders' addons can tell them apart.
function ns.NewSession()
    sessions = sessions + 1
    return time() % 1000000 * 100 + sessions % 100
end

---------------------------------------------------------------------------
-- Tonight's wins and trials
---------------------------------------------------------------------------
-- Tonight's awards are those in the last NIGHT seconds and since /nlc newnight.
local function Tonight()
    local since = time() - NIGHT
    if ns.db.night and ns.db.night > since then since = ns.db.night end
    return since
end
ns.NightStart = Tonight

-- True if this player (a NameKey) won a main-spec item tonight.
function ns.WonTonight(key)
    local since, log = Tonight(), ns.db.log
    for i = #log, 1, -1 do
        local e = log[i]
        if e.at < since then return false end
        if e.how ~= "os" and ns.NameKey(e.who) == key then return true end
    end
    return false
end

-- True if this unit has one of the guild's trial ranks (by default, any rank with "trial" in
-- its name). Only our own guild's ranks count.
function ns.IsTrial(unit)
    if not GetGuildInfo then return false end
    local guild, rank = GetGuildInfo(unit)
    local mine = GetGuildInfo("player")
    if not Plain(guild) or not Plain(rank) or not Plain(mine) or type(rank) ~= "string" or guild ~= mine then
        return false
    end
    rank = rank:lower()
    if not ns.db.trialRanks then return rank:find("trial", 1, true) ~= nil end
    for _, r in ipairs(ns.db.trialRanks) do
        if r:lower() == rank then return true end
    end
    return false
end

---------------------------------------------------------------------------
-- A roll
---------------------------------------------------------------------------
-- Ranks two rolls: tier, then member before trial, then each round's roll (none = -1).
local function Before(a, b, rounds)
    if a.tier ~= b.tier then return a.tier < b.tier end
    if a.trial ~= b.trial then return not a.trial end
    for i = 1, rounds do
        local x, y = a.r[i] or -1, b.r[i] or -1
        if x ~= y then return x > y end
    end
    return false
end

local function Standings(r)
    local list = {}
    for _, e in pairs(r.rolls) do list[#list + 1] = e end
    sort(list, function(a, b)
        if Before(a, b, r.round) then return true end
        if Before(b, a, r.round) then return false end
        return a.key < b.key
    end)
    return list
end

local function Describe(e)
    local parts = { TierName(e.tier) }
    if e.trial then parts[#parts + 1] = L["trial"] end
    return concat(parts, ", ")
end

local Finish

local function Schedule(r)
    token = token + 1
    local mine = token
    if C_Timer and C_Timer.After then
        if r.round == 1 then
            C_Timer.After(DURATION - WARN, function()
                if current == r and token == mine then
                    ns.Announce(L["%d seconds left to roll for %s."]:format(WARN, r.link))
                end
            end)
        end
        C_Timer.After(DURATION, function()
            if current == r and token == mine then Finish() end
        end)
    end
end

local function Done(r)
    if current == r then current = nil end
    if r.sid then ns.Broadcast("E", r.sid) end
end

-- Adds an award to the loot log, with what the export and the bot want to know: the
-- winner's class, the raid and the boss.
function ns.LogAward(award, unit)
    if unit and UnitClass then
        local _, class = UnitClass(unit)
        if Plain(class) and type(class) == "string" then award.class = class end
    end
    local name, instanceType = GetInstanceInfo()
    if Plain(name) and Plain(instanceType) and instanceType ~= "none" and type(name) == "string" then award.inst = name end
    award.boss = ns.RecentBoss()
    award.at = time()
    local log = ns.db.log
    log[#log + 1] = award
    return award
end

-- How many rolled main spec and off spec (first rolls only).
local function Wanted(r)
    local ms, os = 0, 0
    for _, e in pairs(r.rolls) do
        if e.tier == 3 then os = os + 1 else ms = ms + 1 end
    end
    return ms, os
end

local function Award(r, e)
    if r.onAward then return r.onAward(e, e.r[#e.r]) end
    local ms, os = Wanted(r)
    ns.LogAward({ id = r.id, link = r.link, who = e.name, how = HOW[e.tier], roll = e.r[#e.r], nms = ms, nos = os }, e.unit)
    ns.Announce(L["%s wins %s (%s, %d)."]:format(e.name, r.link, Describe(e), e.r[#e.r]))
end

-- Ends the round: a winner, a tie to re-roll, or nobody.
Finish = function()
    local r = current
    if not r then return end
    local list = Standings(r)
    for i, e in ipairs(list) do
        local rolls = {}
        for n, v in ipairs(e.r) do rolls[n] = tostring(v) end
        if #rolls == 0 then rolls[1] = "-" end
        print(("  %d. %s %s · %s"):format(i, e.name, concat(rolls, " / "), Describe(e)))
    end
    if #list == 0 then
        Done(r)
        ns.Announce(L["Nobody rolled for %s."]:format(r.link))
        if r.onNobody then r.onNobody() end
        return
    end
    local top, tied = list[1], { list[1] }
    for i = 2, #list do
        if Before(top, list[i], r.round) then break end
        tied[#tied + 1] = list[i]
    end
    if #tied == 1 then
        Done(r)
        Award(r, top)
        return
    end
    if r.round > 1 and not top.r[r.round] then
        Done(r) -- a tie, and none of those tied rolled again
        ns.Announce(L["Nobody re-rolled for %s; the loot master decides."]:format(r.link))
        return
    end
    r.round, r.tied = r.round + 1, {}
    local names = {}
    for _, e in ipairs(tied) do
        r.tied[e.key] = true
        names[#names + 1] = e.name
    end
    ns.Announce(L["Tie for %s: %s. Roll again, %d seconds."]:format(r.link, concat(names, ", "), DURATION))
    Schedule(r)
end

local function OnRoll(m, roll, low, high)
    local r = current
    if not r then return end
    if r.only and not r.only[m.key] then return end
    if low ~= 1 or (high ~= MS and high ~= OS) then
        ns.Say(L["Ignored %s's roll of %d (%d-%d): only /roll (main spec) and /roll 99 (off spec) count."]:format(m.name, roll, low or 0, high or 0))
        return
    end
    local e = r.rolls[m.key]
    if r.tied then
        if not r.tied[m.key] or e.r[r.round] then return end
        e.r[r.round] = roll
        for key in pairs(r.tied) do
            if not r.rolls[key].r[r.round] then return end
        end
        Finish() -- everyone tied has rolled again
        return
    end
    if e then return end -- the first roll counts
    if r.only then -- a roll-off: everyone in it rolls as an equal
        r.rolls[m.key] = { name = m.name, key = m.key, unit = m.unit, tier = 1, trial = false, r = { roll } }
        return
    end
    local tier = high == OS and 3 or (ns.WonTonight(m.key) and 2 or 1)
    r.rolls[m.key] = { name = m.name, key = m.key, unit = m.unit, tier = tier, trial = ns.IsTrial(m.unit), r = { roll } }
end

-- A roll line from chat, "%s rolls %d (%d-%d)" in the client's own words, as the group
-- member who rolled, the roll and its range; nil for anything else.
local ROLL
function ns.ParseRoll(text)
    if not Plain(text) or type(text) ~= "string" then return nil end
    ROLL = ROLL or ns.ChatPattern(RANDOM_ROLL_RESULT)
    if not ROLL then return nil end
    local who, roll, low, high = text:match(ROLL)
    roll, low, high = tonumber(roll), tonumber(low), tonumber(high)
    local m = who and roll and ns.GroupMember(who)
    if m then return m, roll, low, high end
end

ns.On("CHAT_MSG_SYSTEM", function(text)
    if not current then return end
    local m, roll, low, high = ns.ParseRoll(text)
    if m then OnRoll(m, roll, low, high) end
end)

function ns.CurrentRoll() return current end

-- Starts a roll. opts: only = { key = true } and onAward = fn(entry, roll) for a council
-- roll-off; onNobody = fn. Returns false if a roll is already running.
function ns.StartRoll(id, link, opts)
    if current then return false end
    opts = opts or {}
    current = { id = id, link = link, round = 1, rolls = {}, sid = ns.NewSession(), only = opts.only,
        onAward = opts.onAward, onNobody = opts.onNobody }
    if opts.only then
        ns.Announce(L["Roll-off for %s between %s: /roll. %d seconds."]:format(link, opts.names, DURATION))
    else
        ns.Announce(L["Roll for %s: /roll for main spec, /roll 99 for off spec. %d seconds."]:format(link, DURATION))
        ns.Broadcast("S", current.sid, link, "roll", DURATION)
    end
    Schedule(current)
    return true
end

---------------------------------------------------------------------------
-- Commands
---------------------------------------------------------------------------
-- An item from a command's text: any shift-clicked item link, or a listed item's ID or name.
local function ItemFrom(text)
    local link = text:match("|c.-|Hitem:.-|h|r")
    if link then return ns.ItemID(link), link end
    local id, item = ns.FindItem(text)
    if item then return id, item.link end
end

-- Starts the item's lane: the council for a council item (unless `how` is "roll"), else a
-- roll. Returns false if something is already running.
function ns.StartItem(id, link, how)
    if current then
        ns.Say(L["Already rolling for %s. /nlc stop ends it now, /nlc cancel calls it off."]:format(current.link))
        return false
    end
    local item = id and ns.db.items[id]
    if how ~= "roll" and (how == "council" or (item and item.handling == "council")) and ns.StartCouncil then
        return ns.StartCouncil(id, link)
    end
    return ns.StartRoll(id, link)
end

ns.Command("start", function(text)
    local how = text:match("%s(%a+)$")
    if how ~= "roll" and how ~= "council" then how = nil end
    local id, link = ItemFrom(how and text:sub(1, -#how - 2) or text)
    if not link then
        ns.Say(L["Roll for what? Shift-click the item, or use a listed item's ID or name."])
        return
    end
    ns.StartItem(id, link, how)
end, L["<item> [roll|council]: start its roll, or the council for a council item"])

ns.Command("stop", function()
    if current then return Finish() end
    if ns.StopCouncil and ns.StopCouncil() then return end
    ns.Say(L["No roll running."])
end, L["end the roll (or the council's bids or vote) now"])

ns.Command("cancel", function()
    if not current then
        if ns.CancelCouncil and ns.CancelCouncil() then return end
        ns.Say(L["No roll running."])
        return
    end
    local r = current
    Done(r)
    ns.Announce(L["Roll for %s called off."]:format(r.link))
end, L["call off the roll or the council"])

ns.Command("wins", function()
    local since, lines = Tonight(), {}
    for _, e in ipairs(ns.db.log) do
        if e.how ~= "os" and e.at >= since then
            lines[#lines + 1] = ("  %s · %s"):format(e.who, e.link or "?")
        end
    end
    if #lines == 0 then ns.Say(L["No main-spec wins tonight."]) return end
    ns.Say(L["main-spec wins tonight (they roll second main spec):"])
    for _, line in ipairs(lines) do print(line) end
end, L["tonight's main-spec wins"])

ns.Command("newnight", function()
    ns.db.night = time()
    ns.Say(L["New raid night: earlier wins no longer count."])
end, L["start a new raid night (wins reset after 12 hours anyway)"])

ns.Command("undo", function()
    local log = ns.db.log
    local e = log[#log]
    if not e then ns.Say(L["Nothing to undo."]) return end
    log[#log] = nil
    ns.Say(L["Removed: %s won %s."]:format(e.who, e.link or "?"))
end, L["remove the last award (it no longer counts as a win)"])

ns.Command("trials", function(text)
    if text:lower() == "default" then
        ns.db.trialRanks = nil
    elseif text ~= "" then
        local ranks = {}
        for rank in text:gmatch("[^,]+") do
            rank = rank:match("^%s*(.-)%s*$")
            if rank ~= "" then ranks[#ranks + 1] = rank end
        end
        ns.db.trialRanks = ranks
    end
    if ns.db.trialRanks then
        ns.Say(L["Trial ranks: %s."]:format(concat(ns.db.trialRanks, ", ")))
    else
        ns.Say(L["Trial ranks: any guild rank with \"trial\" in its name."])
    end
end, L["[rank, rank]: the guild ranks that are trials (default: any with \"trial\" in the name)"])
