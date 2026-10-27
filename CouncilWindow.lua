-- The council window: what the council sees while it decides a council item (the mockup's
-- "What the council sees"). Main-spec bids are the candidates; under each, the tags and note
-- from their pop-up. Columns: what they wear now, their upgrade %, what they've won before
-- tonight (from this addon's own loot log) and the votes. Off-spec bids are listed below.
-- Opens on the loot master's addon and each council member's when an item starts.
--
-- Council members vote with the row's button (again to take it back); the loot master also
-- has Award (with a reason, required), Roll off between the most-voted, Close bids / Count
-- votes now, and Call off.
local ADDON, ns = ...
if ns.disabled then return end
local L = ns.L

local ipairs, pairs, time, floor, concat, type, tostring = ipairs, pairs, time, math.floor, table.concat, type, tostring

local WIDTH, HEIGHT = 780, 560
local ROWS = 8
local ROW_H = 40
local COLS = { name = 16, wears = 190, upgrade = 380, earlier = 450, votes = 600, button = 640 }

local frame, rows = nil, {}
local tick = 0

local function Me() return ns.NameKey(ns.PlayerName()) end

local function ClassColour(unit, name)
    local _, class = unit and UnitClass and UnitClass(unit)
    local c = ns.Plain(class) and RAID_CLASS_COLORS and RAID_CLASS_COLORS[class]
    if c and c.colorStr then return "|c" .. c.colorStr .. name .. "|r" end
    return name
end

local function ItemName(id)
    if not id or id == 0 then return L["nothing"] end
    local GetInfo = C_Item and C_Item.GetItemInfo
    local name = GetInfo and GetInfo(id)
    if ns.Plain(name) and type(name) == "string" then return name end
    return "item:" .. id
end

-- What a candidate has won before tonight, from our own loot log: "2 items, last 4 days ago".
function ns.EarlierLoot(key)
    local since, n, last = ns.NightStart(), 0, nil
    for _, e in ipairs(ns.db.log) do
        if e.at < since and ns.NameKey(e.who) == key and e.how ~= "os" then
            n = n + 1
            last = e.at
        end
    end
    if n == 0 then return L["none yet"] end
    local days = floor((time() - last) / 86400)
    local ago = days == 0 and L["today"] or days == 1 and L["yesterday"] or L["%d days ago"]:format(days)
    return (n == 1 and L["1 item, %s"] or L["%d items, last %s"]):format(n == 1 and ago or n, ago)
end

-- The candidates with the most votes (all main-spec candidates if nobody has voted).
local function MostVoted(s)
    local counts = ns.Tally(s)
    local best, keys = 0, {}
    for key, c in pairs(counts) do
        if c > best then best, keys = c, { key } elseif c == best then keys[#keys + 1] = key end
    end
    if best == 0 then
        for _, b in ipairs(ns.Candidates(s)) do
            if b.resp == "ms" then keys[#keys + 1] = b.key end
        end
    end
    table.sort(keys)
    return keys
end

local function PhaseText(s)
    if s.phase == "done" then
        return s.winner and L["Awarded to %s."]:format(s.winner) or L["Finished."]
    elseif s.phase == "rolloff" then
        return L["Roll-off running."]
    end
    local left = s.ends and s.ends - time() or 0
    if left < 0 then left = 0 end
    local clock = ("%d:%02d"):format(floor(left / 60), left % 60)
    return s.phase == "bids" and L["Bids close in %s"]:format(clock) or L["Votes close in %s, then the top candidates roll off"]:format(clock)
end

local function CouncilLine(s)
    local parts = {}
    for _, name in ipairs(s.council) do
        local key = ns.NameKey(name)
        local state
        if not ns.CanVote(s, key) then state = L["sits out: a candidate"]
        elseif s.votes[key] then state = L["voted"]
        else state = L["not yet"] end
        parts[#parts + 1] = (key == Me() and L["%s (you)"]:format(name) or name) .. " · " .. state
    end
    return L["Council: %s"]:format(concat(parts, "   "))
end

local function Refresh()
    if not frame or not frame:IsShown() then return end
    local s = ns.CouncilSession()
    if not s then return frame:Hide() end
    local item = s.id and ns.db.items[s.id]
    frame.item:SetText(s.link)
    frame.priority:SetText(item and item.note or "")
    frame.phase:SetText(PhaseText(s))
    frame.council:SetText(CouncilLine(s))
    local counts = ns.Tally(s)
    local me = Me()
    local voting = s.phase == "vote" and ns.CanVote(s, me)
    local lm = s.mine and s.phase == "vote"
    local list, offSpec = {}, {}
    for _, b in ipairs(ns.Candidates(s)) do
        if b.resp == "ms" then list[#list + 1] = b else offSpec[#offSpec + 1] = b end
    end
    for i = 1, ROWS do
        local row, b = rows[i], list[i]
        row.bid = b
        row:SetShown(b ~= nil)
        if b then
            row.name:SetText(ClassColour(b.unit, b.name) .. (b.trial and " · " .. L["trial"] or ""))
            local wears = {}
            for _, id in ipairs(b.gear or {}) do wears[#wears + 1] = ItemName(id) end
            row.wears:SetText(#wears > 0 and concat(wears, ", ") or "-")
            row.upgrade:SetText(ns.UpgradeText(b.gain) or "-")
            row.earlier:SetText(ns.EarlierLoot(b.key))
            row.votes:SetText(tostring(counts[b.key] or 0))
            local mine = s.votes[me] == b.key
            row.vote:SetText(mine and L["Voted"] or L["Vote"])
            row.vote:SetShown(voting)
            row.award:SetShown(lm)
            local said = {}
            if b.tags and #b.tags > 0 then said[#said + 1] = concat(b.tags, ", ") end
            if b.note then said[#said + 1] = '"' .. b.note .. '"' end
            if #said == 0 then said[1] = b.roll and L["no addon: rolled %d"]:format(b.roll) or L["no note"] end
            row.said:SetText(concat(said, "  "))
        end
    end
    local os = {}
    for _, b in ipairs(offSpec) do os[#os + 1] = b.name .. (b.roll and " (" .. b.roll .. ")" or "") end
    frame.offSpec:SetText(#os > 0 and L["Off spec, not candidates: %s"]:format(concat(os, ", ")) or "")
    if #list > ROWS then
        frame.more:SetText(L["and %d more: /nlc award <name>"]:format(#list - ROWS))
    else
        frame.more:SetText("")
    end
    local owner = s.mine and s.phase ~= "done" and s.phase ~= "rolloff"
    frame.reason:SetShown(lm)
    frame.reasonLabel:SetShown(lm)
    frame.rolloff:SetShown(lm)
    if lm then
        local keys = MostVoted(s)
        local names = {}
        for _, key in ipairs(keys) do names[#names + 1] = s.bids[key].name:match("^%S+") end
        frame.rolloff:SetText(L["Roll off: %s"]:format(concat(names, ", ")))
        frame.rolloff:SetEnabled(#keys >= 2)
        frame.rolloff.keys = keys
    end
    frame.next:SetShown(owner)
    frame.next:SetText(s.phase == "bids" and L["Close bids now"] or L["Count votes now"])
    frame.cancel:SetShown(owner)
end
ns.CouncilChanged = Refresh

local function Countdown()
    if not frame or not frame:IsShown() then return end
    Refresh()
    tick = tick + 1
    local mine = tick
    C_Timer.After(1, function() if tick == mine then Countdown() end end)
end

local function Row(i)
    local f = CreateFrame("Frame", nil, frame)
    f:SetSize(WIDTH - 32, ROW_H)
    f:SetPoint("TOPLEFT", frame, "TOPLEFT", 16, -132 - (i - 1) * ROW_H)
    local function Cell(x, w, template)
        local fs = ns.Label(f, template)
        fs:SetPoint("TOPLEFT", f, "TOPLEFT", x - 16, 0)
        fs:SetWidth(w)
        fs:SetWordWrap(false)
        return fs
    end
    f.name = Cell(COLS.name, 170, "GameFontNormal")
    f.wears = Cell(COLS.wears, 180)
    f.upgrade = Cell(COLS.upgrade, 64)
    f.earlier = Cell(COLS.earlier, 145)
    f.votes = Cell(COLS.votes, 30)
    f.said = ns.Label(f, "GameFontHighlightSmall")
    f.said:SetPoint("TOPLEFT", f, "TOPLEFT", 12, -18)
    f.said:SetWidth(WIDTH - 220)
    f.said:SetWordWrap(false)
    f.vote = ns.Button(f, L["Vote"], 60, function()
        local s = ns.CouncilSession()
        if not s or not f.bid then return end
        ns.Vote(s.votes[Me()] ~= f.bid.key and f.bid.key or nil)
    end)
    f.vote:SetPoint("TOPLEFT", f, "TOPLEFT", COLS.button - 16, 2)
    f.award = ns.Button(f, L["Award"], 64, function()
        if not f.bid then return end
        local reason = frame.reason:GetText() or ""
        if not reason:find("%S") then
            ns.Say(L["Give a reason first: it's posted in the loot log."])
            frame.reason:SetFocus()
            return
        end
        ns.CouncilAward(f.bid.key, reason)
    end)
    f.award:SetPoint("LEFT", f.vote, "RIGHT", 4, 0)
    return f
end

local function CreateWindow()
    local f = ns.Window("NoctisLootCouncilCouncil", L["Loot council"], WIDTH, HEIGHT)
    frame = f
    f:ClearAllPoints()
    f:SetPoint("CENTER", UIParent, "CENTER", 0, 60)
    f.item = ns.Label(f, "GameFontNormalLarge")
    f.item:SetPoint("TOPLEFT", f, "TOPLEFT", 16, -34)
    f.priority = ns.Label(f)
    f.priority:SetPoint("TOPLEFT", f.item, "BOTTOMLEFT", 0, -4)
    f.phase = ns.Label(f)
    f.phase:SetPoint("TOPRIGHT", f, "TOPRIGHT", -16, -36)
    f.council = ns.Label(f, "GameFontHighlightSmall")
    f.council:SetPoint("TOPLEFT", f, "TOPLEFT", 16, -80)
    f.council:SetPoint("RIGHT", f, "RIGHT", -16, 0)
    local heads = { { COLS.name, L["Candidate"] }, { COLS.wears, L["Wears now"] }, { COLS.upgrade, L["Upgrade"] },
        { COLS.earlier, L["Before tonight"] }, { COLS.votes, L["Votes"] } }
    for _, h in ipairs(heads) do
        local fs = ns.Label(f, "GameFontNormalSmall")
        fs:SetPoint("TOPLEFT", f, "TOPLEFT", h[1], -108)
        fs:SetText(h[2])
    end
    for i = 1, ROWS do rows[i] = Row(i) end
    f.more = ns.Label(f, "GameFontHighlightSmall")
    f.more:SetPoint("TOPLEFT", f, "TOPLEFT", 16, -132 - ROWS * ROW_H)
    f.offSpec = ns.Label(f, "GameFontHighlightSmall")
    f.offSpec:SetPoint("TOPLEFT", f.more, "BOTTOMLEFT", 0, -4)
    f.offSpec:SetPoint("RIGHT", f, "RIGHT", -16, 0)
    -- The loot master's controls.
    f.reasonLabel = ns.Label(f, "GameFontHighlightSmall")
    f.reasonLabel:SetPoint("BOTTOMLEFT", f, "BOTTOMLEFT", 18, 44)
    f.reasonLabel:SetText(L["Reason for the award, posted in the loot log (required)"])
    local reason = CreateFrame("EditBox", "NoctisLootCouncilCouncilReason", f, "InputBoxTemplate")
    reason:SetSize(330, 22)
    reason:SetPoint("BOTTOMLEFT", f, "BOTTOMLEFT", 22, 16)
    reason:SetAutoFocus(false)
    reason:SetMaxLetters(120)
    reason:SetScript("OnEnterPressed", function(self) self:ClearFocus() end)
    reason:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    ns.SkinEditBox(reason)
    f.reason = reason
    f.rolloff = ns.Button(f, L["Roll off"], 150, function(self)
        if self.keys then ns.CouncilRollOff(self.keys) end
    end)
    f.rolloff:SetPoint("LEFT", reason, "RIGHT", 10, 0)
    f.next = ns.Button(f, L["Count votes now"], 120, function() ns.StopCouncil() end)
    f.next:SetPoint("LEFT", f.rolloff, "RIGHT", 6, 0)
    f.cancel = ns.Button(f, L["Call off"], 80, function() ns.CancelCouncil() end)
    f.cancel:SetPoint("LEFT", f.next, "RIGHT", 6, 0)
    f.footer = ns.Label(f, "GameFontDisableSmall")
    f.footer:SetPoint("BOTTOMRIGHT", f, "BOTTOMRIGHT", -16, 48)
    f.footer:SetText(L["Votes are private to the council."])
    f:HookScript("OnShow", function()
        reason:SetText("")
        Countdown()
    end)
    f:HookScript("OnHide", function() tick = tick + 1 end)
end

function ns.ShowCouncilWindow()
    if not frame then CreateWindow() end
    if frame:IsShown() then Refresh() else frame:Show() end
end

ns.Command("councilwindow", function()
    if not ns.CouncilSession() then
        ns.Say(L["No council item running."])
        return
    end
    ns.ShowCouncilWindow()
end, L["open the council window again"])
