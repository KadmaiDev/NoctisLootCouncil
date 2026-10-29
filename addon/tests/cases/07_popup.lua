-- Addon messages, the raider's pop-up and the upgrade % it shows and sends.

local SASH = wow.link(18000, "Sash of the Unseen", 4)
local BELT = wow.link(16818, "Netherwind Belt", 4)
local HELM = wow.link(16866, "Helm of Might", 4)
local SEREN = { "Seren", "Vale", rank = "Officer", class = "PRIEST", assist = true }
local DORAN = { "Doran", "Pike", rank = "Officer", class = "WARRIOR" }

-- The player as a raider in Seren's raid (Seren is the loot master).
local function raider()
    local ns = start()
    wow.player.class = "WARLOCK"
    wow.raid({ SEREN, DORAN })
    clearPrinted()
    return ns
end

local function popup() return NoctisLootCouncilPopup end

test("messages: fields with tabs and line breaks survive the trip", function()
    local ns = start()
    local f = ns.Decode(ns.Encode("B", 12, "a\tb", "line\nnext", "back\\slash", ""))
    eq(f[1], "B")
    eq(f[2], "12")
    eq(f[3], "a\tb")
    eq(f[4], "line\nnext")
    eq(f[5], "back\\slash")
    eq(f[6], "")
end)

test("a roll from the loot master opens the pop-up; Main spec rolls 1-100 and closes it", function()
    raider()
    wow.message("Seren Vale", "RAID", "S", 101, HELM, "roll", 30)
    assert(popup():IsShown())
    eq(popup().item:GetText(), HELM)
    assert(not popup().note:IsShown(), "no note on a roll item")
    popup().ms:Click()
    eq(wow.rolled[1], 1)
    eq(wow.rolled[2], 100)
    assert(not popup():IsShown())
end)

test("Off spec rolls 1-99; Pass just closes; the loot master ending it closes it too", function()
    raider()
    wow.message("Seren Vale", "RAID", "S", 101, HELM, "roll", 30)
    popup().os:Click()
    eq(wow.rolled[2], 99)
    wow.rolled = nil
    wow.message("Seren Vale", "RAID", "S", 102, HELM, "roll", 30)
    popup().pass:Click()
    eq(wow.rolled, nil)
    wow.message("Seren Vale", "RAID", "S", 103, HELM, "roll", 30)
    wow.message("Seren Vale", "RAID", "E", 103)
    assert(not popup():IsShown())
end)

test("the pop-up closes itself when time is up", function()
    raider()
    wow.message("Seren Vale", "RAID", "S", 101, HELM, "roll", 30)
    wow.wait(29)
    assert(popup():IsShown())
    eq(popup().timer:GetText(), "1 s")
    wow.wait(1)
    assert(not popup():IsShown())
end)

test("the loot master's own roll: everyone in the raid gets the pop-up, the loot master too", function()
    local ns = start()
    wow.raid({ SEREN })
    wow.type("/nlc start " .. HELM)
    local s = wow.messages("S")[1]
    eq(s.channel, "RAID")
    eq(s[3], HELM)
    eq(s[4], "roll")
    assert(popup():IsShown())
    popup().ms:Click() -- the loot master's roll counts like anyone's
    wow.wait(30)
    assert(wow.said():find("Kadmai Moonwhisper wins", 1, true), wow.said())
    eq(#wow.messages("E"), 1)
end)

test("a message from someone outside the group is ignored", function()
    raider()
    wow.message("Stranger Danger", "WHISPER", "S", 101, HELM, "roll", 30)
    eq(popup(), nil)
end)

test("council item: tags and a note, and Main spec sends the bid to the loot master and council only", function()
    local ns = raider()
    wow.equip[18000] = { "Armor", "Cloth", "INVTYPE_WAIST", class = 4, sub = 1 }
    wow.equip[16818] = { "Armor", "Cloth", "INVTYPE_WAIST", class = 4, sub = 1 }
    wow.stats[18000] = { ITEM_MOD_SPELL_POWER_SHORT = 20, ITEM_MOD_INTELLECT_SHORT = 10, ITEM_MOD_STAMINA_SHORT = 10, ITEM_MOD_HIT_SPELL_RATING_SHORT = 1 }
    wow.stats[16818] = { ITEM_MOD_SPELL_POWER_SHORT = 12, ITEM_MOD_INTELLECT_SHORT = 8, ITEM_MOD_STAMINA_SHORT = 10 }
    wow.stats[1] = { ITEM_MOD_SPELL_POWER_SHORT = 680 } -- the rest of the gear
    wow.gear[6] = BELT
    wow.gear[1] = wow.link(1, "Everything Else", 4)
    wow.message("Seren Vale", "RAID", "S", 201, 18000, "council", 30, "Seren Vale", "Seren Vale,Doran Pike", SASH)
    assert(popup():IsShown())
    assert(popup().note:IsShown())
    -- 41 against 20, of 700 in all: +3%
    assert(popup().info:GetText():find("+3%", 1, true), popup().info:GetText())
    popup().chips[1]:SetChecked(true) -- BIS
    popup().chips[3]:SetChecked(true) -- Sidegrade
    popup().note:SetText("first upgrade in weeks")
    popup().ms:Click()
    eq(wow.rolled, nil, "no roll for a council item")
    local bids = wow.messages("B")
    eq(#bids, 2)
    eq(bids[1].channel, "WHISPER")
    eq(bids[1].target, "Seren Vale")
    eq(bids[2].target, "Doran Pike")
    eq(bids[1][2], "201")
    eq(bids[1][3], "ms")
    eq(bids[1][4], "BIS,Sidegrade")
    eq(bids[1][5], "first upgrade in weeks")
    eq(bids[1][6], "3.0")
    eq(bids[1][7], "16818")
end)

test("a council item without its link in the message is looked up by its ID", function()
    raider()
    wow.message("Seren Vale", "RAID", "S", 201, 18000, "council", 30, "Seren Vale", "Seren Vale")
    eq(popup().item:GetText(), "item:18000")
    eq(wow.requested[#wow.requested], 18000)
end)

test("if whispers can't be sent, the bid never goes raid-wide: it becomes a roll instead", function()
    raider()
    wow.whisperFails = true
    wow.message("Seren Vale", "RAID", "S", 201, 18000, "council", 30, "Seren Vale", "Doran Pike", SASH)
    popup().chips[1]:SetChecked(true)
    popup().note:SetText("private note")
    popup().os:Click()
    for _, b in ipairs(wow.messages("B")) do
        assert(b.channel == "WHISPER", "a bid went " .. tostring(b.channel))
    end
    eq(wow.rolled[1], 1)
    eq(wow.rolled[2], 99, "an off-spec roll")
    assert(printed():find("Couldn't send your bid privately to Seren Vale, Doran Pike, so it's a roll instead", 1, true), printed())
end)

test("if the game blocks addon messages, the loot master is told once and rolls still work", function()
    local ns = start()
    wow.raid({ SEREN })
    wow.addonResult = 11
    wow.type("/nlc start " .. HELM)
    wow.roll("Seren Vale", 60)
    wow.wait(30)
    assert(wow.said():find("Seren Vale wins", 1, true), wow.said())
    local _, n = printed():gsub("wouldn't send our addon's messages", "")
    eq(n, 1)
end)

test("/nlc popup off: no pop-up", function()
    raider()
    wow.type("/nlc popup off")
    wow.message("Seren Vale", "RAID", "S", 101, HELM, "roll", 30)
    eq(popup(), nil)
end)

test("upgrade %: can't use it, no upgrade, and nothing worn yet", function()
    local ns = raider()
    wow.equip[16866] = { "Armor", "Plate", "INVTYPE_HEAD", class = 4, sub = 4 }
    wow.stats[16866] = { ITEM_MOD_STRENGTH_SHORT = 20 }
    eq(ns.MyUpgrade(HELM), nil, "a warlock can't wear plate")
    wow.equip[18000] = { "Armor", "Cloth", "INVTYPE_WAIST", class = 4, sub = 1 }
    wow.stats[18000] = { ITEM_MOD_SPELL_POWER_SHORT = 20 }
    eq(ns.MyUpgrade(SASH), math.huge, "nothing worn scores yet")
    eq(ns.UpgradeText(math.huge), "new")
    wow.equip[16818] = { "Armor", "Cloth", "INVTYPE_WAIST", class = 4, sub = 1 }
    wow.stats[16818] = { ITEM_MOD_SPELL_POWER_SHORT = 40 }
    wow.gear[6] = BELT
    eq(ns.MyUpgrade(SASH), 0, "worse than the belt worn")
end)

test("/nlc role: the role the upgrade % is worked out for", function()
    local ns = raider()
    wow.player.class = "DRUID"
    eq(ns.MyRole(), "feral", "a druid's default")
    wow.type("/nlc role healer")
    eq(ns.MyRole(), "healer")
    wow.type("/nlc role ranged")
    assert(printed():find("Not a role for your class", 1, true))
    wow.type("/nlc role auto")
    eq(ns.MyRole(), "feral")
end)

test("pop-ups only open for someone running the loot, and a council's only from the loot master it names", function()
    raider()
    wow.raid({ SEREN, DORAN })
    wow.message("Doran Pike", "RAID", "S", 101, HELM, "roll", 30)
    assert(not popup() or not popup():IsShown(), "Doran neither leads nor assists")
    wow.message("Seren Vale", "RAID", "S", 201, 18000, "council", 30, "Doran Pike", "Doran Pike", SASH)
    assert(not popup() or not popup():IsShown(), "Seren naming Doran as loot master")
    wow.message("Seren Vale", "RAID", "S", 101, HELM, "roll", 30)
    assert(popup():IsShown())
    wow.message("Doran Pike", "RAID", "E", 101)
    assert(popup():IsShown(), "only Seren can close it")
    wow.message("Seren Vale", "RAID", "E", 101)
    assert(not popup():IsShown())
end)

test("a council item without its link: the cached link if the client has it, else the link once it loads", function()
    raider()
    wow.cache[18000] = { "Sash of the Unseen", 4 }
    wow.message("Seren Vale", "RAID", "S", 201, 18000, "council", 30, "Seren Vale", "Seren Vale")
    assert(popup().item:GetText():find("[Sash of the Unseen]", 1, true), popup().item:GetText())
    wow.message("Seren Vale", "RAID", "E", 201)
    wow.cache[18000] = nil
    wow.message("Seren Vale", "RAID", "S", 202, 18000, "council", 30, "Seren Vale", "Seren Vale")
    eq(popup().item:GetText(), "item:18000")
    wow.itemLoads(18000, "Sash of the Unseen", 4)
    assert(popup().item:GetText():find("[Sash of the Unseen]", 1, true), popup().item:GetText())
end)

test("an appointed master looter who neither leads nor assists runs the loot too", function()
    raider()
    wow.message("Doran Pike", "RAID", "S", 101, HELM, "roll", 30)
    assert(not popup() or not popup():IsShown(), "not before Doran is master looter")
    wow.masterLooter = { raid = 3 } -- raid1 is the player, raid2 Seren, raid3 Doran
    wow.message("Doran Pike", "RAID", "S", 102, HELM, "roll", 30)
    assert(popup():IsShown())
    popup().pass:Click()
    wow.message("Doran Pike", "RAID", "S", 201, 18000, "council", 30, "Doran Pike", "Doran Pike", SASH)
    assert(popup():IsShown())
    eq(popup().title:GetText(), "Council item")
end)
