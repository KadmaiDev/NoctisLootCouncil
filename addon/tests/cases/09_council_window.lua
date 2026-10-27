-- The council window.

local SASH = wow.link(18000, "Sash of the Unseen", 4)
local BELT = wow.link(16818, "Netherwind Belt", 4)
local SEREN = { "Seren", "Vale", rank = "Officer", class = "PRIEST" }
local DORAN = { "Doran", "Pike", rank = "Officer", class = "WARRIOR" }
local ILSA = { "Ilsa", "Marrow", rank = "Raider", class = "WARLOCK" }
local VESPERA = { "Vespera", "Ashward", rank = "Raider", class = "WARLOCK" }
local ODO = { "Odo", "Fenwick", rank = "Trial", class = "MAGE" }

local function lootMaster()
    local ns = start()
    wow.raid({ SEREN, DORAN, ILSA, VESPERA, ODO })
    wow.type("/nlc councillors Seren Vale, Doran Pike, Kadmai Moonwhisper")
    wow.type("/nlc council " .. SASH .. " Warlock priority")
    wow.cache[16818] = { "Netherwind Belt", 4 }
    clearPrinted()
    return ns
end

local function bid(who, resp, tags, note, gain, gear)
    wow.message(who, "WHISPER", "B", wow.ns.CouncilSession().sid, resp, tags or "", note or "", gain or "", gear or "")
end

local function window() return NoctisLootCouncilCouncil end

test("it opens for the loot master with the item, its priority and the time left to bid", function()
    lootMaster()
    wow.type("/nlc start " .. SASH)
    assert(window():IsShown())
    eq(window().item:GetText(), SASH)
    eq(window().priority:GetText(), "Warlock priority")
    eq(window().phase:GetText(), "Bids close in 0:30")
    wow.wait(5)
    eq(window().phase:GetText(), "Bids close in 0:25")
end)

test("candidates: main spec first, with what they wear, upgrade, earlier loot, tags and note", function()
    local ns = lootMaster()
    ns.db.log[1] = { id = 1, link = "x", who = "Ilsa Marrow", at = wow.clock - 4 * 86400, how = "ms" }
    wow.type("/nlc start " .. SASH)
    bid("Ilsa Marrow", "ms", "BIS", "last piece of my set", "14.2", "16818")
    bid("Vespera Ashward", "os")
    wow.roll("Odo Fenwick", 70)
    local text = {}
    for _, f in ipairs(wow.frames) do
        if f.kind == "FontString" and f.text and f:IsVisible() then text[#text + 1] = f.text end
    end
    local all = table.concat(text, "\n")
    assert(all:find("Ilsa Marrow", 1, true), all)
    assert(all:find("Netherwind Belt", 1, true), all)
    assert(all:find("+14%", 1, true), all)
    assert(all:find("1 item, 4 days ago", 1, true), all)
    assert(all:find('BIS  "last piece of my set"', 1, true), all)
    assert(all:find("Odo Fenwick · trial", 1, true), all)
    assert(all:find("no addon: rolled 70", 1, true), all)
    assert(all:find("Off spec, not candidates: Vespera Ashward", 1, true), all)
end)

-- The row frame showing this candidate.
local function rowOf(name)
    for _, f in ipairs(wow.frames) do
        if f.bid and f.bid.name == name and f:IsShown() then return f end
    end
end

test("voting from the window: the button sends the vote, and again takes it back", function()
    local ns = lootMaster()
    wow.type("/nlc start " .. SASH)
    bid("Ilsa Marrow", "ms")
    bid("Vespera Ashward", "ms")
    assert(not rowOf("Ilsa Marrow").vote:IsShown(), "no voting during bids")
    wow.wait(30)
    local row = rowOf("Ilsa Marrow")
    assert(row.vote:IsShown())
    row.vote:Click()
    eq(ns.CouncilSession().votes["kadmai moonwhisper"], "ilsa marrow")
    eq(row.vote:GetText(), "Voted")
    eq(row.votes:GetText(), "1")
    assert(window().council:GetText():find("Kadmai Moonwhisper (you) · voted", 1, true), window().council:GetText())
    row.vote:Click()
    eq(ns.CouncilSession().votes["kadmai moonwhisper"], nil)
end)

test("the loot master's Award needs a reason, then awards with it", function()
    local ns = lootMaster()
    wow.type("/nlc start " .. SASH)
    bid("Ilsa Marrow", "ms")
    bid("Vespera Ashward", "ms")
    wow.wait(30)
    local row = rowOf("Vespera Ashward")
    row.award:Click()
    assert(printed():find("Give a reason first", 1, true))
    eq(ns.CouncilSession().phase, "vote")
    window().reason:SetText("Ilsa won the last one")
    row.award:Click()
    eq(ns.db.log[1].who, "Vespera Ashward")
    eq(window().phase:GetText(), "Awarded to Vespera Ashward.")
end)

test("Roll off is between the most-voted candidates", function()
    local ns = lootMaster()
    wow.type("/nlc start " .. SASH)
    bid("Ilsa Marrow", "ms")
    bid("Vespera Ashward", "ms")
    bid("Odo Fenwick", "ms")
    wow.wait(30)
    wow.message("Seren Vale", "WHISPER", "V", ns.CouncilSession().sid, "ilsa marrow")
    wow.message("Doran Pike", "WHISPER", "V", ns.CouncilSession().sid, "odo fenwick")
    eq(window().rolloff:GetText(), "Roll off: Ilsa, Odo")
    window().rolloff:Click()
    assert(wow.said():find("Roll-off for " .. SASH .. " between Ilsa Marrow, Odo Fenwick", 1, true), wow.said())
end)

test("a council member's window: no Award, and they sit out their own bid", function()
    local ns = start()
    wow.raid({ SEREN, ILSA })
    wow.message("Seren Vale", "RAID", "S", 301, 18000, "council", 30, "Seren Vale", "Seren Vale,Kadmai Moonwhisper", SASH)
    assert(window():IsShown())
    wow.message("Ilsa Marrow", "WHISPER", "B", 301, "ms", "", "", "", "")
    wow.message("Kadmai Moonwhisper", "WHISPER", "B", 301, "ms", "", "", "", "")
    wow.message("Seren Vale", "WHISPER", "P", 301, "vote", 300)
    local row = rowOf("Ilsa Marrow")
    assert(not row.award:IsShown())
    assert(not row.vote:IsShown(), "a candidate can't vote")
    assert(window().council:GetText():find("(you) · sits out", 1, true), window().council:GetText())
    assert(not window().reason:IsShown())
end)
