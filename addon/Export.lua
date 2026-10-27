-- The loot log for oxm.gg, the guild's roster and loot history site. oxm imports
-- RCLootCouncil's CSV export, so ours is written in that format, column for column
-- (RCLootCouncil's LootHistory:ExportCSV, read 2026-10-27; the format, not its code). An addon
-- can't write a file or the clipboard, so the text sits selected in a box for Ctrl+C.
--   /nlc export      tonight's awards (since /nlc newnight, at most 12 hours back)
--   /nlc export all  the whole log
local ADDON, ns = ...
if ns.disabled then return end
local L = ns.L

local concat, tostring, type, ipairs, date = table.concat, tostring, type, ipairs, date

local WIDTH, HEIGHT = 720, 420

local HEADER = "player,date,time,id,item,itemID,itemString,response,votes,class,instance,boss,"
    .. "difficultyID,mapID,groupSize,gear1,gear2,responseID,isAwardReason,subType,equipLoc,note,owner"

-- The response column and RCLootCouncil's response number for each kind of award.
local RESPONSE = { ms = "Main spec", ms2 = "Second main spec", os = "Off spec", council = "Council" }
local RESPONSE_ID = { ms = 1, ms2 = 2, os = 3, council = 1 }

-- As RCLootCouncil does it: a field with a comma is quoted, its quotes doubled.
local function Field(s)
    if s == nil then return "" end
    s = tostring(s)
    if s:find(",", 1, true) then return '"' .. s:gsub('"', '""') .. '"' end
    return s
end

local function Row(e, n)
    local itemString = e.link and e.link:match("item:[%-%d:]+") or ("item:" .. e.id)
    local subType, equipLoc
    if C_Item and C_Item.GetItemInfoInstant and e.link then
        local _, _, sub, loc = C_Item.GetItemInfoInstant(e.link)
        if ns.Plain(sub) and type(sub) == "string" then subType = sub end
        if ns.Plain(loc) and type(loc) == "string" then equipLoc = loc end
    end
    local note = e.note or (e.roll and L["roll %d"]:format(e.roll))
    return concat({
        Field(e.who), date("%Y/%m/%d", e.at), date("%H:%M:%S", e.at), e.at .. "-" .. n,
        Field(e.link or itemString), Field(e.id), itemString, Field(RESPONSE[e.how] or e.how), "",
        Field(e.class), Field(e.inst), Field(e.boss), "", "", "", "", "",
        Field(RESPONSE_ID[e.how] or ""), "false", Field(subType), Field(equipLoc), Field(note), Field(ns.db.me),
    }, ",")
end

-- The CSV for the awards since `since` (nil = all), and how many there are.
function ns.ExportCSV(since)
    local lines, count = { HEADER }, 0
    for n, e in ipairs(ns.db.log) do
        if e.id and (not since or e.at >= since) then
            count = count + 1
            lines[#lines + 1] = Row(e, n)
        end
    end
    return concat(lines, "\n"), count
end

local frame, box

local function CreateWindow()
    local f = ns.Window("NoctisLootCouncilExport", L["Loot log for oxm.gg"], WIDTH, HEIGHT)
    frame = f
    f.hint = ns.Label(f)
    f.hint:SetPoint("TOPLEFT", f, "TOPLEFT", 18, -36)
    f.hint:SetPoint("RIGHT", f, "RIGHT", -18, 0)
    box = ns.CopyBox(f, "NoctisLootCouncilExportBox", WIDTH - 52)
    box.scroll:SetPoint("TOPLEFT", f, "TOPLEFT", 18, -62)
    box.scroll:SetPoint("BOTTOMRIGHT", f, "BOTTOMRIGHT", -34, 14)
    f:HookScript("OnHide", function()
        box:ClearFocus()
        box.text = nil
        box:SetText("")
    end)
end

function ns.ShowExport(all)
    local text, count = ns.ExportCSV(not all and ns.NightStart() or nil)
    if count == 0 then
        ns.Say(all and L["The loot log is empty."] or L["No awards tonight. /nlc export all exports the whole log."])
        return
    end
    if not frame then CreateWindow() end
    frame.hint:SetText(L["%d awards. Press Ctrl+C to copy, then paste it into oxm.gg's RCLootCouncil import."]:format(count))
    frame:Show()
    box:Fill(text)
end

ns.Command("export", function(text)
    ns.ShowExport(text:lower() == "all")
end, L["[all]: tonight's awards (or all) as RCLootCouncil CSV, to paste into oxm.gg"])
