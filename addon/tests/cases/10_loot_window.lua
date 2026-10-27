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
