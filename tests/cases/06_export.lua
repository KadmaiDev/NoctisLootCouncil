-- The loot log as RCLootCouncil's CSV, for oxm.gg, and the window it's copied from.

local SASH = wow.link(18000, "Sash of the Unseen", 4)
local HELM = wow.link(16866, "Helm of Might", 4)
local VESPERA = { "Vespera", "Ashward", rank = "Raider", class = "WARLOCK" }

local HEADER = "player,date,time,id,item,itemID,itemString,response,votes,class,instance,boss,"
    .. "difficultyID,mapID,groupSize,gear1,gear2,responseID,isAwardReason,subType,equipLoc,note,owner"

local function lines(text)
    local out = {}
    for line in (text .. "\n"):gmatch("(.-)\n") do out[#out + 1] = line end
    return out
end

-- Splits a CSV line as a CSV reader would (quoted fields may hold commas and "").
local function fields(line)
    local out, i = {}, 1
    while i <= #line + 1 do
        if line:sub(i, i) == '"' then
            local j, s = i + 1, ""
            while true do
                local q = line:find('"', j, true)
                if line:sub(q + 1, q + 1) == '"' then
                    s, j = s .. line:sub(j, q), q + 2
                else
                    s, i = s .. line:sub(j, q - 1), q + 2
                    break
                end
            end
            out[#out + 1] = s
        else
            local c = line:find(",", i, true) or #line + 1
            out[#out + 1] = line:sub(i, c - 1)
            i = c + 1
        end
    end
    return out
end

test("a roll award as RCLootCouncil's CSV row", function()
    local ns = start()
    wow.equip[18000] = { "Armor", "Cloth", "INVTYPE_WAIST" }
    wow.raid({ VESPERA })
    wow.kill(663, "Lucifron")
    wow.type("/nlc start " .. SASH)
    wow.roll("Vespera Ashward", 91)
    wow.wait(30)
    local text, count = ns.ExportCSV()
    eq(count, 1)
    local l = lines(text)
    eq(l[1], HEADER)
    local f = fields(l[2])
    eq(#f, 23, "a value for every column")
    local at = ns.db.log[1].at
    eq(f[1], "Vespera Ashward")
    eq(f[2], os.date("%Y/%m/%d", at))
    eq(f[3], os.date("%H:%M:%S", at))
    eq(f[4], at .. "-1")
    eq(f[5], SASH)
    eq(f[6], "18000")
    eq(f[7], "item:18000::::::::60:::::::::")
    eq(f[8], "Main spec")
    eq(f[10], "WARLOCK")
    eq(f[11], "Molten Core")
    eq(f[12], "Lucifron")
    eq(f[18], "1")
    eq(f[19], "false")
    eq(f[20], "Cloth")
    eq(f[21], "INVTYPE_WAIST")
    eq(f[22], "roll 91")
    eq(f[23], "Kadmai Moonwhisper")
end)

test("a council award keeps its reason; commas and quotes are escaped as RCLootCouncil does", function()
    local ns = start()
    ns.db.log[1] = { id = 18000, link = SASH, who = "Ilsa Marrow", at = wow.clock, how = "council",
        note = 'Warlock priority, "biggest upgrade"' }
    local f = fields(lines(ns.ExportCSV())[2])
    eq(#f, 23)
    eq(f[8], "Council")
    eq(f[22], 'Warlock priority, "biggest upgrade"')
    assert(lines(ns.ExportCSV())[2]:find('"Warlock priority, ""biggest upgrade"""', 1, true))
end)

test("/nlc export shows tonight's awards in a box, selected for copying; all shows the log", function()
    local ns = start()
    ns.db.log = {
        { id = 16866, link = HELM, who = "Old Win", at = wow.clock - 20 * 3600, how = "ms", roll = 50 },
        { id = 18000, link = SASH, who = "Vespera Ashward", at = wow.clock, how = "os", roll = 12 },
    }
    wow.type("/nlc export")
    local f = NoctisLootCouncilExport
    assert(f:IsShown())
    local box = NoctisLootCouncilExportBox
    eq(#lines(box:GetText()), 2, "header and tonight's award")
    assert(box:GetText():find("Vespera Ashward", 1, true))
    assert(f.hint:GetText():find("1 awards", 1, true), f.hint:GetText())
    box:Run("OnTextChanged", true) -- typing puts it back
    eq(#lines(box:GetText()), 2)
    f:Hide()
    eq(box:GetText(), "")
    wow.type("/nlc export all")
    eq(#lines(box:GetText()), 3)
end)

test("/nlc export with nothing to export says so instead of opening an empty box", function()
    start()
    wow.type("/nlc export")
    assert(printed():find("No awards tonight", 1, true), printed())
    eq(NoctisLootCouncilExport, nil)
end)

test("/nlc scale sets our windows' size, kept between 50% and 300%", function()
    local ns = start()
    ns.db.log[1] = { id = 18000, link = SASH, who = "A", at = wow.clock, how = "ms" }
    wow.type("/nlc scale 150")
    wow.type("/nlc export")
    eq(NoctisLootCouncilExport:GetScale(), 1.5)
    wow.type("/nlc scale 900")
    eq(ns.db.scale, 3)
    wow.type("/nlc scale default")
    eq(ns.db.scale, nil)
    eq(NoctisLootCouncilExport:GetScale(), 1)
end)
