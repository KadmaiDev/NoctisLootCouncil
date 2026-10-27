-- The raider's pop-up: when the loot master starts a roll or a council item, raiders with the
-- addon get Main spec / Off spec / Pass buttons instead of typing.
--  * A roll item: Main spec does /roll, Off spec /roll 99. The roll itself, in chat, is what
--    counts, exactly as if it were typed.
--  * A council item: no roll yet. Optional tags and a note, then Main spec or Off spec sends
--    the bid (with your upgrade % and what you wear in that slot) to the loot master and the
--    council only; Pass takes a bid back.
-- It closes when you choose, when the loot master ends it, or when time is up. /nlc popup off
-- turns it off for this account.
local ADDON, ns = ...
if ns.disabled then return end
local L = ns.L

local tonumber, tostring, ipairs, concat, time, floor = tonumber, tostring, ipairs, table.concat, time, math.floor

local WIDTH, HEIGHT = 380, 128
local COUNCIL_HEIGHT = 236

local frame
local open -- { sid, id, link, kind, lm, council = { names }, ends }
local tick = 0

local function ItemLink(id, link)
    if link and link ~= "" then return link end
    local GetInfo = C_Item and C_Item.GetItemInfo
    local _, l = GetInfo and GetInfo(id)
    if ns.Plain(l) and type(l) == "string" then return l end
    if C_Item and C_Item.RequestLoadItemDataByID then C_Item.RequestLoadItemDataByID(id) end
    return "item:" .. tostring(id)
end

local function Close()
    open = nil
    if frame then frame:Hide() end
end

local function Countdown()
    if not open or not frame:IsShown() then return end
    local left = open.ends - time()
    if left <= 0 then return Close() end
    frame.timer:SetText(L["%d s"]:format(left))
    tick = tick + 1
    local mine = tick
    C_Timer.After(1, function() if tick == mine then Countdown() end end)
end

-- What you'd send: the tags ticked and the note.
local function Tags()
    local list = {}
    for i, chip in ipairs(frame.chips) do
        if chip:GetChecked() then list[#list + 1] = ns.BID_TAGS[i] end
    end
    return concat(list, ",")
end

local function Gain()
    local gain = ns.MyUpgrade(open.link)
    if gain == math.huge then return "new" end
    return gain and ("%.1f"):format(gain) or ""
end

local function Choose(resp)
    local o = open
    if not o then return end
    if o.kind == "roll" then
        if resp ~= "pass" and RandomRoll then RandomRoll(1, resp == "ms" and 100 or 99) end
    else
        local note = (frame.note:GetText() or ""):sub(1, ns.NOTE_MAX)
        local names = { o.lm }
        for _, n in ipairs(o.council) do names[#names + 1] = n end
        ns.SendTo(names, "B", o.sid, resp, resp == "pass" and "" or Tags(), resp == "pass" and "" or note,
            resp == "pass" and "" or Gain(), ns.WornIDs(o.link))
    end
    Close()
end

local function CreateWindow()
    local f = ns.Window("NoctisLootCouncilPopup", L["Loot"], WIDTH, HEIGHT)
    frame = f
    f:ClearAllPoints()
    f:SetPoint("TOP", UIParent, "TOP", 0, -180)
    f.item = ns.Label(f, "GameFontNormalLarge")
    f.item:SetPoint("TOPLEFT", f, "TOPLEFT", 16, -34)
    f.item:SetPoint("RIGHT", f, "RIGHT", -60, 0)
    f.timer = ns.Label(f)
    f.timer:SetPoint("TOPRIGHT", f, "TOPRIGHT", -16, -36)
    f.info = ns.Label(f, "GameFontHighlightSmall")
    f.info:SetPoint("TOPLEFT", f.item, "BOTTOMLEFT", 0, -6)
    -- The tag chips and note, shown for council items.
    f.chips = {}
    for i, tag in ipairs(ns.BID_TAGS) do
        local c = CreateFrame("CheckButton", nil, f, "UICheckButtonTemplate")
        c:SetSize(24, 24)
        c:SetPoint("TOPLEFT", f, "TOPLEFT", 14 + ((i - 1) % 2) * 170, -84 - floor((i - 1) / 2) * 26)
        c.label = ns.Label(c)
        c.label:SetPoint("LEFT", c, "RIGHT", 2, 0)
        c.label:SetText(tag)
        f.chips[i] = c
    end
    local note = CreateFrame("EditBox", "NoctisLootCouncilPopupNote", f, "InputBoxTemplate")
    note:SetSize(WIDTH - 40, 22)
    note:SetPoint("TOPLEFT", f, "TOPLEFT", 22, -146)
    note:SetAutoFocus(false)
    note:SetMaxLetters(ns.NOTE_MAX)
    note:SetScript("OnEnterPressed", function(self) self:ClearFocus() end)
    note:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    ns.SkinEditBox(note)
    f.note = note
    f.noteLabel = ns.Label(f, "GameFontHighlightSmall")
    f.noteLabel:SetPoint("BOTTOMLEFT", note, "TOPLEFT", -4, 2)
    f.noteLabel:SetText(L["Note for the council (optional)"])
    f.ms = ns.Button(f, L["Main spec"], 110, function() Choose("ms") end)
    f.os = ns.Button(f, L["Off spec"], 110, function() Choose("os") end)
    f.pass = ns.Button(f, L["Pass"], 110, function() Choose("pass") end)
    f.ms:SetPoint("BOTTOMLEFT", f, "BOTTOMLEFT", 14, 14)
    f.os:SetPoint("LEFT", f.ms, "RIGHT", 8, 0)
    f.pass:SetPoint("LEFT", f.os, "RIGHT", 8, 0)
    f:HookScript("OnHide", function() tick = tick + 1 end)
end

local function Show(o)
    if not frame then CreateWindow() end
    open = o
    local council = o.kind == "council"
    frame:SetHeight(council and COUNCIL_HEIGHT or HEIGHT)
    frame.title:SetText(council and L["Council item"] or L["Roll"])
    frame.item:SetText(o.link)
    local up = ns.UpgradeText(ns.MyUpgrade(o.link))
    if council then
        frame.info:SetText(up and L["Your upgrade: %s. Goes to the loot master and council only."]:format(up)
            or L["Goes to the loot master and council only."])
    else
        frame.info:SetText(up and L["Your upgrade: %s. Main spec rolls 1-100, off spec 1-99."]:format(up)
            or L["Main spec rolls 1-100, off spec 1-99."])
    end
    for _, chip in ipairs(frame.chips) do
        chip:SetChecked(false)
        chip:SetShown(council)
    end
    frame.note:SetText("")
    frame.note:SetShown(council)
    frame.noteLabel:SetShown(council)
    frame:Show()
    Countdown()
end

ns.OnMessage("S", function(m, sid, a, b, c, d, e, f)
    if ns.db.popupOff then return end
    -- A roll:    sid, link, "roll", seconds
    -- A council: sid, itemID, "council", seconds, loot master, council names, link (may be missing)
    local o
    if b == "roll" then
        o = { sid = tonumber(sid), link = a, kind = "roll", ends = time() + (tonumber(c) or 30), council = {} }
    elseif b == "council" then
        local names = {}
        for n in (e or ""):gmatch("[^,]+") do names[#names + 1] = n end
        o = { sid = tonumber(sid), id = tonumber(a), kind = "council", ends = time() + (tonumber(c) or 30),
            lm = d, council = names }
        o.link = ItemLink(o.id, f)
    end
    if o and o.sid then Show(o) end
end)

ns.OnMessage("E", function(m, sid)
    if open and tonumber(sid) == open.sid then Close() end
end)

function ns.PopupOpen() return open end
function ns.PopupChoose(resp) Choose(resp) end

ns.Command("popup", function(text)
    text = text:lower()
    if text == "off" then ns.db.popupOff = true elseif text == "on" then ns.db.popupOff = nil end
    ns.Say(ns.db.popupOff and L["The loot pop-up is off."] or L["The loot pop-up is on."])
end, L["on|off: the Main spec / Off spec / Pass pop-up"])
