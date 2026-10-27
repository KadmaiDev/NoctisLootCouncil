-- The loot master's window (the mockup's "What the loot master sees"): tonight's drops on the
-- left, each with its decision and state and a button to start it; the running roll on the
-- right, with each roll, its kind and why it's placed there. Other tabs show the item list
-- and the loot log as text. Opens on its own when the loot master loots a boss (or anything
-- worth recording); /nlc show opens it any time.
local ADDON, ns = ...
if ns.disabled then return end
local L = ns.L

local ipairs, pairs, time, floor, concat, type, date, tostring = ipairs, pairs, time, math.floor, table.concat, type, date, tostring

local WIDTH, HEIGHT = 900, 470
local DROP_ROWS, ROLL_ROWS = 8, 10
local LEFT_W = 400

local frame
local dropRows, rollRows = {}, {}
local tab = "drops"
local tick = 0

-- Is the player the one handing out loot? Master looter if the game says so, else the
-- group's leader. Forever's Master Loot API is to be checked on launch night.
function ns.IsLootMaster()
    if C_PartyInfo and C_PartyInfo.GetLootMethod then
        local ok, method, partyIndex = pcall(C_PartyInfo.GetLootMethod)
        local master = Enum and Enum.LootMethod and Enum.LootMethod.Masterlooter
        if ok and ns.Plain(method) and master and method == master then return partyIndex == 0 end
    end
    return UnitIsGroupLeader and UnitIsGroupLeader("player") and true or false
end

---------------------------------------------------------------------------
-- What each drop is doing
---------------------------------------------------------------------------
local function Award(drop)
    for i = #ns.db.log, 1, -1 do
        local e = ns.db.log[i]
        if e.at < drop.at then break end
        if e.id == drop.id then return e end
    end
end

local HOW = { ms = L["main spec"], ms2 = L["second main spec"], os = L["off spec"], council = L["council"] }

-- "Council item · Warlock priority", "Rolling, 0:18", "Done · Bran Holloway, off spec 64"...
function ns.DropState(drop)
    local item = ns.db.items[drop.id] or {}
    local r = ns.CurrentRoll()
    if r and r.id == drop.id then
        local left = r.ends and r.ends - time() or 0
        return L["Rolling, %d:%02d"]:format(floor(left / 60), left % 60), "running"
    end
    local s = ns.CouncilSession()
    if s and s.id == drop.id and s.phase ~= "done" then
        return s.phase == "bids" and L["Council: taking bids"] or s.phase == "vote" and L["Council: voting"] or L["Council: roll-off"], "running"
    end
    local e = Award(drop)
    if e then
        return L["Done · %s, %s"]:format(e.who, (HOW[e.how] or e.how) .. (e.roll and " " .. e.roll or "")), "done"
    end
    if item.handling == "council" then
        return L["Council item"] .. (item.note and " · " .. item.note or ""), "council"
    elseif item.handling == "roll" then
        return L["Roll item"] .. (item.note and " · " .. item.note or ""), "roll"
    end
    return drop.new and L["New · first time seen, so it's rolled"] or L["Not decided · rolled"], "roll"
end

---------------------------------------------------------------------------
-- The window
---------------------------------------------------------------------------
local Refresh

local function DecisionsLine()
    local council, roll = 0, 0
    for _, item in pairs(ns.db.items) do
        if item.handling == "council" then council = council + 1 elseif item.handling == "roll" then roll = roll + 1 end
    end
    if ns.db.decisionsAt then
        return L["Decisions from %s · %d council, %d roll"]:format(date("%d %b, %H:%M", ns.db.decisionsAt), council, roll)
    end
    return L["No decisions from Discord yet · %d council, %d roll"]:format(council, roll)
end

local function RefreshDrops()
    local list = ns.tonight
    local first = #list > DROP_ROWS and #list - DROP_ROWS + 1 or 1 -- the newest drops
    for i = 1, DROP_ROWS do
        local row, drop = dropRows[i], list[first + i - 1]
        row.drop = drop
        row:SetShown(drop ~= nil)
        if drop then
            local state, kind = ns.DropState(drop)
            local link = drop.link .. (drop.n > 1 and " ×" .. drop.n or "")
            row.item:SetText(link)
            row.state:SetText((drop.boss and drop.boss .. " · " or "") .. state)
            local idle = kind ~= "running" and kind ~= "done"
            row.start:SetShown(idle)
            row.other:SetShown(idle)
            row.start:SetText(kind == "council" and L["Council"] or L["Roll"])
            row.other:SetText(kind == "council" and L["Roll instead"] or L["Council instead"])
            row.kind = kind
        end
    end
    frame.empty:SetShown(#list == 0)
end

local function RefreshRoll()
    local r = ns.CurrentRoll()
    local s = ns.CouncilSession()
    local council = s and s.phase ~= "done" and s.phase ~= "rolloff" and s.mine
    frame.rollItem:SetText(r and r.link or council and s.link or L["Nothing running"])
    if r then
        local left = r.ends and r.ends - time() or 0
        if left < 0 then left = 0 end
        frame.rollTime:SetText(("%d:%02d"):format(floor(left / 60), left % 60))
    else
        frame.rollTime:SetText("")
    end
    frame.endNow:SetShown(r ~= nil)
    frame.toCouncil:SetShown(r ~= nil and not r.only)
    frame.callOff:SetShown(r ~= nil)
    frame.openCouncil:SetShown(council and true or false)
    local standings = ns.RollStandings()
    for i = 1, ROLL_ROWS do
        local row, e = rollRows[i], standings[i]
        row:SetShown(e ~= nil)
        if e then
            row.n:SetText(tostring(i))
            row.name:SetText(e.name)
            row.roll:SetText(tostring(e.roll or "-"))
            row.kind:SetText(e.kind)
            row.why:SetText(e.why)
        end
    end
    local ignored = {}
    for _, g in ipairs(r and r.ignored or {}) do
        ignored[#ignored + 1] = L["%s rolled %d (%d-%d)"]:format(g.name, g.roll, g.low or 0, g.high or 0)
    end
    frame.ignored:SetText(#ignored > 0 and L["Ignored: %s. Only /roll and /roll 99 count."]:format(concat(ignored, "; ")) or "")
    frame.leader:SetText(r and standings[1] and L["When the time is up: %s wins, announced in raid chat and logged."]:format(standings[1].name) or "")
end

local function LogText()
    local lines = {}
    for i = #ns.db.log, 1, -1 do
        local e = ns.db.log[i]
        lines[#lines + 1] = ("%s · %s · %s · %s%s%s"):format(date("%d %b %H:%M", e.at), e.who, e.link or "?",
            HOW[e.how] or e.how, e.roll and " " .. e.roll or "", e.note and " · " .. e.note or "")
    end
    return #lines > 0 and concat(lines, "\n") or L["The loot log is empty."]
end

Refresh = function()
    if not frame or not frame:IsShown() then return end
    frame.decisions:SetText(DecisionsLine())
    for name, b in pairs(frame.tabs) do b:SetEnabled(name ~= tab) end
    local drops = tab == "drops"
    frame.dropsPane:SetShown(drops)
    frame.text.scroll:SetShown(not drops)
    if drops then
        RefreshDrops()
        RefreshRoll()
    elseif tab == "items" then
        local lines = ns.LootLines()
        frame.text:Fill(#lines > 0 and concat(lines, "\n") or L["No raid drops seen yet."])
    else
        frame.text:Fill(LogText())
    end
end
ns.RollChanged = Refresh
ns.DropsChanged = Refresh
local councilChanged = ns.CouncilChanged -- the council window's
ns.CouncilChanged = function()
    if councilChanged then councilChanged() end
    Refresh()
end

local function Countdown()
    if not frame or not frame:IsShown() then return end
    if tab == "drops" then
        RefreshDrops()
        RefreshRoll()
    end
    tick = tick + 1
    local mine = tick
    C_Timer.After(1, function() if tick == mine then Countdown() end end)
end

local function Cell(parent, x, w, template)
    local fs = ns.Label(parent, template)
    fs:SetPoint("LEFT", parent, "LEFT", x, 0)
    fs:SetWidth(w)
    fs:SetWordWrap(false)
    return fs
end

local function CreateWindow()
    local f = ns.Window("NoctisLootCouncilLoot", L["Noctis Loot Council"], WIDTH, HEIGHT)
    frame = f
    f.tabs = {}
    local tabs = { { "drops", L["Drops"] }, { "items", L["Item list"] }, { "log", L["Loot log"] } }
    for i, t in ipairs(tabs) do
        local b = ns.Button(f, t[2], 100, function()
            tab = t[1]
            Refresh()
        end)
        b:SetPoint("TOPLEFT", f, "TOPLEFT", 14 + (i - 1) * 104, -30)
        f.tabs[t[1]] = b
    end
    f.decisions = ns.Label(f, "GameFontHighlightSmall")
    f.decisions:SetPoint("TOPRIGHT", f, "TOPRIGHT", -16, -36)

    -- Text tabs.
    f.text = ns.CopyBox(f, "NoctisLootCouncilLootText", WIDTH - 52)
    f.text.scroll:SetPoint("TOPLEFT", f, "TOPLEFT", 18, -62)
    f.text.scroll:SetPoint("BOTTOMRIGHT", f, "BOTTOMRIGHT", -34, 14)

    -- Drops: the list on the left.
    local pane = CreateFrame("Frame", nil, f)
    pane:SetPoint("TOPLEFT", f, "TOPLEFT", 0, -60)
    pane:SetPoint("BOTTOMRIGHT", f, "BOTTOMRIGHT", 0, 0)
    f.dropsPane = pane
    f.empty = ns.Label(pane)
    f.empty:SetPoint("TOPLEFT", pane, "TOPLEFT", 18, -8)
    f.empty:SetText(L["No drops looted yet tonight."])
    for i = 1, DROP_ROWS do
        local row = CreateFrame("Frame", nil, pane)
        row:SetSize(LEFT_W, 44)
        row:SetPoint("TOPLEFT", pane, "TOPLEFT", 14, -4 - (i - 1) * 46)
        row.item = ns.Label(row, "GameFontNormal")
        row.item:SetPoint("TOPLEFT", row, "TOPLEFT", 4, -4)
        row.item:SetWidth(LEFT_W - 190)
        row.item:SetWordWrap(false)
        row.state = ns.Label(row, "GameFontHighlightSmall")
        row.state:SetPoint("TOPLEFT", row.item, "BOTTOMLEFT", 0, -4)
        row.state:SetWidth(LEFT_W - 190)
        row.state:SetWordWrap(false)
        row.start = ns.Button(row, L["Roll"], 80, function()
            if row.drop then ns.StartItem(row.drop.id, row.drop.link, row.kind == "council" and "council" or "roll") end
        end)
        row.start:SetPoint("TOPRIGHT", row, "TOPRIGHT", -96, -4)
        row.other = ns.Button(row, L["Council instead"], 92, function()
            if row.drop then ns.StartItem(row.drop.id, row.drop.link, row.kind == "council" and "roll" or "council") end
        end)
        row.other:SetPoint("LEFT", row.start, "RIGHT", 4, 0)
        dropRows[i] = row
    end
    local hint = ns.Label(pane, "GameFontDisableSmall")
    hint:SetPoint("BOTTOMLEFT", pane, "BOTTOMLEFT", 18, 14)
    hint:SetWidth(LEFT_W)
    hint:SetText(L["Council or roll comes from the officers' vote in Discord; you can still change it here."])

    -- The running roll on the right.
    local x = LEFT_W + 40
    f.rollItem = ns.Label(pane, "GameFontNormalLarge")
    f.rollItem:SetPoint("TOPLEFT", pane, "TOPLEFT", x, -8)
    f.rollItem:SetWidth(WIDTH - x - 80)
    f.rollTime = ns.Label(pane, "GameFontNormalLarge")
    f.rollTime:SetPoint("TOPRIGHT", pane, "TOPRIGHT", -18, -8)
    f.endNow = ns.Button(pane, L["End now"], 90, function() SlashCmdList.NOCTISLOOTCOUNCIL("stop") end)
    f.endNow:SetPoint("TOPLEFT", pane, "TOPLEFT", x, -34)
    f.toCouncil = ns.Button(pane, L["Make it council"], 120, function()
        local r = ns.CurrentRoll()
        if not r then return end
        local id, link = r.id, r.link
        SlashCmdList.NOCTISLOOTCOUNCIL("cancel")
        ns.StartItem(id, link, "council")
    end)
    f.toCouncil:SetPoint("LEFT", f.endNow, "RIGHT", 6, 0)
    f.callOff = ns.Button(pane, L["Call off"], 80, function() SlashCmdList.NOCTISLOOTCOUNCIL("cancel") end)
    f.callOff:SetPoint("LEFT", f.toCouncil, "RIGHT", 6, 0)
    f.openCouncil = ns.Button(pane, L["Open the council window"], 180, function() ns.ShowCouncilWindow() end)
    f.openCouncil:SetPoint("TOPLEFT", pane, "TOPLEFT", x, -34)
    local heads = { { 0, "#" }, { 24, L["Player"] }, { 180, L["Roll"] }, { 230, L["Rolls as"] }, { 340, L["Why here"] } }
    for _, h in ipairs(heads) do
        local fs = ns.Label(pane, "GameFontNormalSmall")
        fs:SetPoint("TOPLEFT", pane, "TOPLEFT", x + h[1], -68)
        fs:SetText(h[2])
    end
    for i = 1, ROLL_ROWS do
        local row = CreateFrame("Frame", nil, pane)
        row:SetSize(WIDTH - x - 20, 20)
        row:SetPoint("TOPLEFT", pane, "TOPLEFT", x, -84 - (i - 1) * 21)
        row.n = Cell(row, 0, 20)
        row.name = Cell(row, 24, 150)
        row.roll = Cell(row, 180, 40)
        row.kind = Cell(row, 230, 106)
        row.why = Cell(row, 340, WIDTH - x - 360)
        rollRows[i] = row
    end
    f.ignored = ns.Label(pane, "GameFontHighlightSmall")
    f.ignored:SetPoint("TOPLEFT", pane, "TOPLEFT", x, -84 - ROLL_ROWS * 21 - 4)
    f.ignored:SetWidth(WIDTH - x - 20)
    f.leader = ns.Label(pane, "GameFontHighlight")
    f.leader:SetPoint("BOTTOMLEFT", pane, "BOTTOMLEFT", x, 14)
    f.leader:SetWidth(WIDTH - x - 20)
    f:HookScript("OnShow", function()
        Refresh()
        Countdown()
    end)
    f:HookScript("OnHide", function() tick = tick + 1 end)
end

function ns.ShowLootWindow(which)
    if not frame then CreateWindow() end
    tab = which or tab
    if frame:IsShown() then Refresh() else frame:Show() end
end

-- Opens by itself when the loot master loots something worth recording.
local function Looted()
    if frame and frame:IsShown() then return end
    if ns.IsLootMaster() and not ns.db.autoOpenOff then ns.ShowLootWindow("drops") end
end
local seen = 0
ns.On("LOOT_OPENED", function()
    if #ns.tonight > seen then
        seen = #ns.tonight
        Looted()
    end
end)

ns.Command("show", function(text)
    text = text:lower()
    ns.ShowLootWindow(text == "items" and "items" or text == "log" and "log" or "drops")
end, L["[items|log]: open the loot master's window"])

ns.Command("autoopen", function(text)
    text = text:lower()
    if text == "off" then ns.db.autoOpenOff = true elseif text == "on" then ns.db.autoOpenOff = nil end
    ns.Say(ns.db.autoOpenOff and L["The loot window won't open by itself."] or L["The loot window opens by itself when you loot a boss as loot master."])
end, L["on|off: open the loot master's window when you loot a boss"])
