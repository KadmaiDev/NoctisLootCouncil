-- The loot master's window.

local SASH = wow.link(18000, "Sash of the Unseen", 4)
local CHOKER = wow.link(17109, "Choker of Enlightenment", 4)
local GLOVES = wow.link(16805, "Felheart Gloves", 4)
local VESPERA = { "Vespera", "Ashward", rank = "Raider", class = "WARLOCK" }
local ODO = { "Odo", "Fenwick", rank = "Trial", class = "MAGE" }
local BRAN = { "Bran", "Holloway", rank = "Social", class = "MAGE" }

local function window() return NoctisLootCouncilLoot end

-- Visible rows with this item.
local function dropRow(link)
    for _, f in ipairs(wow.frames) do
        if f.drop and f.drop.link == link and f:IsShown() then return f end
    end
end

local function lootBoss()
    local ns = start()
    wow.leader = true
    wow.raid({ VESPERA, ODO, BRAN })
    wow.type("/nlc council " .. SASH .. " Warlock priority")
    wow.type("/nlc roll " .. CHOKER)
    clearPrinted()
    wow.kill(663, "Lucifron")
    local corpse = wow.npc(12118)
    wow.open({ { SASH, 4, corpse }, { CHOKER, 4, corpse }, { GLOVES, 4, corpse } })
    return ns
end

test("it opens by itself when the loot master loots a boss, listing each drop's decision", function()
    lootBoss()
    assert(window():IsShown())
    eq(dropRow(SASH).state:GetText(), "Lucifron · Council item · Warlock priority")
    eq(dropRow(SASH).start:GetText(), "Council")
    eq(dropRow(CHOKER).state:GetText(), "Lucifron · Roll item")
    eq(dropRow(GLOVES).state:GetText(), "Lucifron · New · first time seen, so it's rolled")
end)

test("a roll from the window: standings with why each is placed, ignored rolls, and the result", function()
    local ns = lootBoss()
    ns.db.log[1] = { id = 1, link = "x", who = "Bran Holloway", at = wow.clock + 1, how = "ms" }
    dropRow(CHOKER).start:Click()
    eq(window().rollItem:GetText(), CHOKER)
    eq(window().rollTime:GetText(), "0:30")
    assert(not dropRow(CHOKER).start:IsShown(), "running: no start button")
    wow.roll("Vespera Ashward", 40)
    wow.roll("Odo Fenwick", 95)
    wow.roll("Bran Holloway", 99)
    wow.roll("Kadmai Moonwhisper", 12, 50)
    local rows = {}
    for _, f in ipairs(wow.frames) do
        if f.why and f:IsShown() then rows[tonumber(f.n:GetText())] = f end
    end
    eq(rows[1].name:GetText(), "Vespera Ashward")
    eq(rows[1].why:GetText(), "leading")
    eq(rows[2].name:GetText(), "Odo Fenwick")
    eq(rows[2].why:GetText(), "trial: after members")
    eq(rows[3].kind:GetText(), "second main spec")
    eq(rows[3].why:GetText(), "won a main-spec item tonight")
    assert(window().ignored:GetText():find("Kadmai Moonwhisper rolled 12 (1-50)", 1, true), window().ignored:GetText())
    eq(window().leader:GetText(), "When the time is up: Vespera Ashward wins, announced in raid chat and logged.")
    wow.wait(30)
    eq(dropRow(CHOKER).state:GetText(), "Lucifron · Done · Vespera Ashward, main spec 40")
    eq(window().rollItem:GetText(), "Nothing running")
end)

test("Make it council turns a running roll into a council", function()
    local ns = lootBoss()
    dropRow(GLOVES).start:Click()
    window().toCouncil:Click()
    assert(wow.said():find("Roll for " .. GLOVES .. " called off.", 1, true))
    eq(ns.CouncilSession().link, GLOVES)
    assert(window().openCouncil:IsShown())
end)

test("Council instead and Roll instead override the decision", function()
    local ns = lootBoss()
    dropRow(SASH).other:Click()
    eq(ns.CurrentRoll().link, SASH)
    SlashCmdList.NOCTISLOOTCOUNCIL("cancel")
    dropRow(CHOKER).other:Click()
    eq(ns.CouncilSession().link, CHOKER)
end)

test("not the loot master: it doesn't open by itself; /nlc autoopen off stops it too", function()
    start()
    wow.raid({ VESPERA })
    wow.kill(663, "Lucifron")
    wow.open({ { SASH, 4, wow.npc(12118) } })
    eq(window(), nil)
    start()
    wow.leader = true
    wow.type("/nlc autoopen off")
    wow.kill(663, "Lucifron")
    wow.open({ { SASH, 4, wow.npc(12118) } })
    eq(window(), nil)
    wow.type("/nlc show")
    assert(window():IsShown())
end)

test("the item list and loot log tabs", function()
    local ns = lootBoss()
    wow.wait(1)
    ns.db.log[1] = { id = 18000, link = SASH, who = "Ilsa Marrow", at = wow.clock, how = "council", note = "Warlock priority" }
    window().tabs.items:Click()
    local text = NoctisLootCouncilLootText:GetText()
    assert(text:find("Lucifron", 1, true) and text:find("Warlock priority", 1, true), text)
    assert(not window().dropsPane:IsShown())
    window().tabs.log:Click()
    text = NoctisLootCouncilLootText:GetText()
    assert(text:find("Ilsa Marrow · " .. SASH .. " · council · Warlock priority", 1, true), text)
    window().tabs.drops:Click()
    assert(window().dropsPane:IsShown())
end)

test("Disenchant gives an item nobody wants to the disenchanter: announced, logged, never a win", function()
    local ns = lootBoss()
    dropRow(GLOVES).de:Click()
    assert(printed():find("No disenchanter set: /nlc disenchanter First Last.", 1, true), printed())
    eq(#ns.db.log, 0)
    wow.type("/nlc disenchanter Someone Else")
    clearPrinted()
    dropRow(GLOVES).de:Click()
    assert(printed():find("Someone Else isn't in the group", 1, true), printed())
    eq(#ns.db.log, 0)
    wow.type("/nlc disenchanter bran") -- a first name is enough when only one raider has it
    dropRow(GLOVES).de:Click()
    local e = ns.db.log[1]
    eq(e.who, "Bran Holloway")
    eq(e.how, "de")
    eq(e.class, "MAGE")
    eq(e.boss, "Lucifron")
    assert(wow.said():find(GLOVES .. " goes to Bran Holloway to disenchant.", 1, true), wow.said())
    eq(dropRow(GLOVES).state:GetText(), "Lucifron · Done · Bran Holloway, disenchanted")
    assert(not dropRow(GLOVES).de:IsShown(), "done: no Disenchant button")
    assert(not dropRow(GLOVES).start:IsShown())
    assert(not ns.WonTonight("bran holloway"), "a disenchant isn't a win")
    clearPrinted()
    wow.type("/nlc wins")
    assert(printed():find("No main-spec wins tonight.", 1, true), printed())
    window().tabs.log:Click()
    assert(NoctisLootCouncilLootText:GetText():find("Bran Holloway · " .. GLOVES .. " · disenchanted", 1, true))
    window().tabs.drops:Click()
    wow.type("/nlc undo")
    eq(#ns.db.log, 0)
    assert(dropRow(GLOVES).de:IsShown(), "undone: it can be handed out again")
end)

test("no Disenchant while the item is being rolled; the disenchanter is kept between sessions", function()
    local ns = lootBoss()
    wow.type("/nlc disenchanter Bran Holloway")
    dropRow(CHOKER).start:Click()
    assert(not dropRow(CHOKER).de:IsShown())
    clearPrinted()
    ns.Disenchant(17109, CHOKER)
    assert(printed():find("is still being decided: call it off first.", 1, true), printed())
    eq(#ns.db.log, 0)
    eq(ns.db.disenchanter, "Bran Holloway")
    wow.type("/nlc disenchanter none")
    eq(ns.db.disenchanter, nil)
end)

test("a drop of two copies stays open until both are handed out: two disenchants, or a win then a disenchant", function()
    local ns = start()
    wow.leader = true
    wow.raid({ VESPERA, ODO, BRAN })
    wow.type("/nlc disenchanter Bran Holloway")
    wow.kill(663, "Lucifron")
    local corpse = wow.npc(12118)
    wow.open({ { GLOVES, 4, corpse }, { GLOVES, 4, corpse } })
    eq(#ns.tonight, 1)
    eq(ns.tonight[1].n, 2)
    dropRow(GLOVES).de:Click()
    eq(dropRow(GLOVES).state:GetText(), "Lucifron · 1 of 2 handed out · Bran Holloway, disenchanted · New · first time seen, so it's rolled")
    assert(dropRow(GLOVES).de:IsShown(), "a copy is left")
    dropRow(GLOVES).de:Click()
    eq(dropRow(GLOVES).state:GetText(), "Lucifron · Done · Bran Holloway, disenchanted; Bran Holloway, disenchanted")
    assert(not dropRow(GLOVES).de:IsShown())
    local a, b = ns.db.log[1], ns.db.log[2]
    eq(a.who .. a.id, b.who .. b.id)
    assert(a.at ~= b.at, "the same second: the bot would take them for one award")

    ns = start()
    wow.leader = true
    wow.raid({ VESPERA, ODO, BRAN })
    wow.type("/nlc disenchanter Bran Holloway")
    wow.kill(663, "Lucifron")
    corpse = wow.npc(12118)
    wow.open({ { GLOVES, 4, corpse }, { GLOVES, 4, corpse } })
    dropRow(GLOVES).start:Click()
    wow.roll("Vespera Ashward", 40)
    wow.wait(30)
    eq(dropRow(GLOVES).state:GetText(), "Lucifron · 1 of 2 handed out · Vespera Ashward, main spec 40 · New · first time seen, so it's rolled")
    assert(dropRow(GLOVES).start:IsShown() and dropRow(GLOVES).de:IsShown(), "the second copy can be rolled or disenchanted")
    dropRow(GLOVES).de:Click()
    eq(dropRow(GLOVES).state:GetText(), "Lucifron · Done · Vespera Ashward, main spec 40; Bran Holloway, disenchanted")
end)

test("two drops of one item: an award closes the older one only", function()
    local ns = lootBoss()
    wow.type("/nlc disenchanter Bran Holloway")
    dropRow(GLOVES).de:Click()
    wow.wait(1)
    wow.kill(664, "Magmadar")
    wow.open({ { GLOVES, 4, wow.npc(11982) } })
    eq(#ns.tonight, 4)
    local older, newer
    for _, f in ipairs(wow.frames) do
        if f.drop and f.drop.link == GLOVES and f:IsShown() then
            if f.drop.boss == "Lucifron" then older = f else newer = f end
        end
    end
    eq(older.state:GetText(), "Lucifron · Done · Bran Holloway, disenchanted")
    assert(newer.de:IsShown(), "Magmadar's copy is still to hand out")
end)

test("award times stay in order and unique, across items, seconds and /nlc undo", function()
    local ns = lootBoss()
    wow.type("/nlc disenchanter Bran Holloway")
    -- Two of A and one of B in one second, then A again in the next.
    ns.Disenchant(16805, GLOVES)
    ns.Disenchant(16805, GLOVES)
    ns.Disenchant(18000, SASH)
    wow.wait(1)
    ns.Disenchant(16805, GLOVES)
    -- Undo the last and hand it out again in the same second: not the undone award's time.
    wow.type("/nlc undo")
    ns.Disenchant(16805, GLOVES)
    local log, seen = ns.db.log, {}
    eq(#log, 4)
    for i, e in ipairs(log) do
        local key = e.who .. "|" .. e.id .. "|" .. e.at
        assert(not seen[key], "two awards with one identity: " .. key)
        seen[key] = true
        if i > 1 then assert(e.at > log[i - 1].at, "the log stays in time order") end
    end
    local u = ns.db.undone[1]
    assert(not seen[u.who .. "|" .. u.id .. "|" .. u.at], "the re-award reused the undone award's time")
end)
