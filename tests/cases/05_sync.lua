-- What the companion app reads (drops, a full loot log, who we are) and the decisions it
-- writes back from Discord.

local SASH = wow.link(18000, "Sash of the Unseen", 4)
local HELM = wow.link(16866, "Helm of Might", 4)
local VESPERA = { "Vespera", "Ashward", rank = "Raider", class = "WARLOCK" }
local BRAN = { "Bran", "Holloway", rank = "Social", class = "MAGE" }

test("the saved file says who logged in, for the companion app's uploads", function()
    local ns = start()
    eq(ns.db.me, "Kadmai Moonwhisper")
end)

test("each drop that adds to an item's count is kept, with its time, boss and copies", function()
    local ns = start()
    wow.kill(663, "Lucifron")
    local corpse = wow.npc(12118)
    wow.open({ { SASH, 4, corpse }, { SASH, 4, corpse } })
    wow.receives("Vespera Ashward", SASH) -- the same drop seen in chat: not another
    eq(#ns.db.drops, 1)
    local d = ns.db.drops[1]
    eq(d.id, 18000)
    eq(d.src, "e663")
    eq(d.inst, 409)
    eq(d.n, 2)
    eq(d.at, wow.clock)
end)

test("an award records the winner's class, the raid, the boss and how many wanted it", function()
    local ns = start()
    wow.raid({ VESPERA, BRAN })
    wow.kill(663, "Lucifron")
    wow.type("/nlc start " .. SASH)
    wow.roll("Vespera Ashward", 40)
    wow.roll("Bran Holloway", 80, 99)
    wow.roll("Kadmai Moonwhisper", 20)
    wow.wait(30)
    local e = ns.db.log[1]
    eq(e.who, "Vespera Ashward")
    eq(e.class, "WARLOCK")
    eq(e.inst, "Molten Core")
    eq(e.boss, "Lucifron")
    eq(e.nms, 2)
    eq(e.nos, 1)
end)

test("outside an instance and long after a kill, an award has no raid or boss", function()
    local ns = start()
    wow.raid({ VESPERA })
    wow.kill(663, "Lucifron")
    wow.wait(700)
    wow.instance = { "Orgrimmar", "none", 0, "", 5, 0, false, 1 }
    wow.type("/nlc start " .. SASH)
    wow.roll("Vespera Ashward", 40)
    wow.wait(30)
    eq(ns.db.log[1].inst, nil)
    eq(ns.db.log[1].boss, nil)
end)

local DECISIONS = {
    at = 1793078967,
    items = {
        [18000] = { h = "council", note = "Warlock priority", name = "Sash of the Unseen" },
        [16866] = { h = "roll" },
        [17109] = { h = "maybe" },  -- not a decision
        ["x"] = { h = "roll" },     -- not an item ID
    },
}

local function withDecisions(saved, decisions)
    wow.saved = saved
    local ns = wow.load(FILES)
    NoctisLootDecisions = decisions
    wow.login()
    return ns
end

test("decisions from Discord are applied at login, adding items we haven't seen", function()
    local ns = withDecisions({ items = { [16866] = { link = HELM, seen = 3, first = 1, last = 2, handling = "council", note = "old" } } }, DECISIONS)
    local sash = ns.db.items[18000]
    eq(sash.handling, "council")
    eq(sash.note, "Warlock priority")
    eq(sash.seen, 0)
    eq(ns.ItemName(sash), "Sash of the Unseen")
    eq(ns.db.items[16866].handling, "roll")
    eq(ns.db.items[16866].note, nil, "Discord's decision replaces the note too")
    eq(ns.db.items[16866].seen, 3)
    eq(ns.db.items[17109], nil)
    eq(ns.db.decisionsAt, 1793078967)
    assert(printed():find("Decisions from " .. os.date("%d %b, %H:%M", 1793078967) .. ": 1 council, 1 roll.", 1, true), printed())
end)

test("the same decisions aren't applied twice, so a change made in game since survives", function()
    local ns = withDecisions(nil, DECISIONS)
    wow.type("/nlc roll 18000")
    wow.saved = ns.db
    clearPrinted()
    ns = withDecisions(ns.db, DECISIONS)
    eq(ns.db.items[18000].handling, "roll")
    assert(not printed():find("Decisions from", 1, true), printed())
    local newer = { at = DECISIONS.at + 60, items = { [18000] = { h = "council" } } }
    ns = withDecisions(ns.db, newer)
    eq(ns.db.items[18000].handling, "council")
end)

test("\"none\" from Discord undoes a decision and its note, and adds nothing new", function()
    local ns = withDecisions({ items = { [16866] = { link = HELM, seen = 3, first = 1, last = 2, handling = "council", note = "old" } } },
        { at = 1793078967, items = { [16866] = { h = "none" }, [17109] = { h = "none" } } })
    eq(ns.db.items[16866].handling, nil)
    eq(ns.db.items[16866].note, nil)
    eq(ns.db.items[16866].seen, 3)
    eq(ns.db.items[17109], nil)
    eq(ns.db.decisionsAt, 1793078967)
end)

test("items record their slot and armour type, for the Discord posts", function()
    local ns = start()
    wow.equip[18000] = { "Armor", "Cloth", "INVTYPE_WAIST" }
    wow.equip[16866] = { "Armor", "Plate", "INVTYPE_HEAD" }
    wow.kill(663, "Lucifron")
    wow.open({ { SASH, 4, wow.npc(12118) } })
    eq(ns.db.items[18000].slot, "INVTYPE_WAIST")
    eq(ns.db.items[18000].sub, "Cloth")
    wow.type("/nlc council 16866")
    eq(ns.db.items[16866].slot, "INVTYPE_HEAD")
    eq(ns.db.items[16866].sub, "Plate")
    wow.type("/nlc council 17109") -- the client knows nothing about it
    eq(ns.db.items[17109].slot, nil)
end)

test("the game loads an item decided in Discord: its real link replaces the placeholder", function()
    local ns = withDecisions(nil, DECISIONS)
    eq(ns.db.items[18000].link, "item:18000 [Sash of the Unseen]")
    wow.itemLoads(18000, "Sash of the Unseen", 4)
    eq(ns.db.items[18000].link, SASH)
    eq(ns.db.items[18000].q, 4)
end)

test("no decisions addon, or a broken one, changes nothing", function()
    local ns = withDecisions(nil, nil)
    eq(ns.db.decisionsAt, nil)
    ns = withDecisions(nil, { at = "soon", items = {} })
    eq(ns.db.decisionsAt, nil)
    ns = withDecisions(nil, { at = 5, items = "x" })
    eq(ns.db.decisionsAt, nil)
end)

test("a damaged save keeps sound drops and award fields", function()
    local ns = start({
        drops = { { id = 1, at = 2, n = 1, src = 5 }, { id = 1 }, "x" },
        log = { { who = "A B", at = 1, how = "council", class = 3, note = "BIS", nms = 2, boss = "Lucifron" } },
    })
    eq(#ns.db.drops, 1)
    eq(ns.db.drops[1].src, nil)
    local e = ns.db.log[1]
    eq(e.class, nil)
    eq(e.note, "BIS")
    eq(e.nms, 2)
    eq(e.boss, "Lucifron")
end)
