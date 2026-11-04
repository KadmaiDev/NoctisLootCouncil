-- Level milestones in game (MilestonesChat.lua): your own chat window, and guild chat with one
-- announcer.

-- Shared by the milestones cases: log in with this saved data (default: milestones turned on),
-- this guild roster and player; the clock carries on from the last load, as between sessions.
local function start(saved, roster, player)
    if saved == nil then saved = { milestones = { on = true } } end
    wow.saved = saved
    local resume = wow.clock and wow.now and (wow.clock + math.floor(wow.now))
    local ns = wow.load(FILES)
    if resume then wow.clock = resume end
    wow.roster = roster or {}
    if player then wow.player = player end
    wow.login()
    return ns
end

-- The server sends the roster and the addon reads it once the burst has settled.
local function arrives(roster)
    wow.rosterArrives(roster)
    wow.wait(3)
end


local function Roster(vespera, extra)
    local r = {
        { name = "Vespera Ashward", level = vespera or 19, class = "DRUID", rank = "Raider", online = true },
        { name = "Kadmai Moonwhisper", level = 41, class = "HUNTER", rank = "Officer", online = true },
        { name = "Seren Vale", level = 60, class = "PRIEST", rank = "Officer", online = true },
    }
    for k, v in pairs(extra or {}) do r[3][k] = v end
    return r
end

local function GuildLines()
    local out = {}
    for _, s in ipairs(wow.sent) do
        if s[2] == "GUILD" then out[#out + 1] = s[1] end
    end
    return out
end

local function Hellos(kind)
    local n = 0
    for _, a in ipairs(wow.addon) do
        if a.prefix == "NoctisMS" and a.channel == "GUILD" and a.text:match("^" .. kind .. "\t") then n = n + 1 end
    end
    return n
end

-- Logs in (the loading screen included) with Vespera at 19, read once.
local function Online(saved, player)
    local ns = start(saved, Roster(), player)
    wow.fire("PLAYER_ENTERING_WORLD", true, false)
    arrives()
    return ns
end

-- Vespera reaches `level` a minute later, while we watch.
local function Levels(level, extra)
    wow.wait(60)
    arrives(Roster(level, extra))
    wow.wait(9)
end

local function Seren(kind, since)
    wow.fire("CHAT_MSG_ADDON", "NoctisMS", kind .. "\t" .. since, "GUILD", "Seren Vale", "", 0, 0, "", 0)
end

local CONGRATS = "Congratulations to Vespera Ashward on reaching level 20!"

test("both are off until turned on: nothing said, nothing sent", function()
    Online()
    clearPrinted()
    Levels(20)
    eq(printed(), "")
    eq(#GuildLines(), 0)
    eq(Hellos("[HRB]"), 0)
end)

test("tell: a line in your own chat for a milestone, nothing for other levels, and catch-ups marked", function()
    local ns = Online()
    wow.type("/nlc milestones tell on")
    eq(ns.db.milestones.tell, true)
    clearPrinted()
    Levels(20)
    assert(printed():find("Vespera Ashward reached level 20.", 1, true), printed())
    assert(not printed():find("caught up", 1, true), printed())
    clearPrinted()
    Levels(21)
    eq(printed(), "")
    eq(#GuildLines(), 0) -- only you see it
    -- Away for a day: the level-up found at the next login is a catch-up.
    local saved = ns.db
    wow.wait(86400)
    start(saved, Roster(30))
    clearPrinted()
    arrives()
    assert(printed():find("Vespera Ashward reached level 30. |cff9d9d9d(caught up: last seen at level 21", 1, true), printed())
    wow.type("/nlc milestones tell off")
    eq(ns.db.milestones.tell, nil)
end)

test("guild chat on, alone: says hello and congratulates a fresh milestone once", function()
    local ns = Online()
    wow.type("/nlc milestones guildchat on")
    eq(ns.db.milestones.guilds["Noctis|Forever"].guildChat, true)
    eq(Hellos("H"), 1)
    Levels(20)
    eq(table.concat(GuildLines(), "\n"), CONGRATS)
    clearPrinted()
    wow.type("/nlc milestones guildchat")
    assert(printed():find("you're the one posting (0 other officers", 1, true), printed())
end)

test("guild chat leaves out catch-ups found after time away", function()
    local ns = Online()
    wow.type("/nlc milestones guildchat on")
    local saved = ns.db
    wow.wait(86400)
    start(saved, Roster(20))
    wow.fire("PLAYER_ENTERING_WORLD", true, false)
    arrives()
    wow.wait(9)
    eq(#GuildLines(), 0)
end)

test("the officer online longest posts; the others stay quiet and take over when they log off", function()
    Online()
    wow.type("/nlc milestones guildchat on")
    Seren("H", time() - 3600) -- online an hour longer than us
    eq(Hellos("R"), 1)        -- we answer, so Seren's addon knows about us
    Levels(20)
    eq(#GuildLines(), 0)
    clearPrinted()
    wow.type("/nlc milestones guildchat")
    assert(printed():find("Seren Vale is posting", 1, true), printed())
    -- Seren logs off: the roster says so, and we post the next one.
    Levels(30, { online = false })
    eq(table.concat(GuildLines(), "\n"), "Congratulations to Vespera Ashward on reaching level 30!")
end)

test("an announcer who goes quiet (a crash) or says goodbye is replaced", function()
    Online()
    wow.type("/nlc milestones guildchat on")
    Seren("H", time() - 3600)
    wow.wait(700) -- no heartbeat from Seren for over 11 minutes
    arrives()
    Levels(20)
    eq(#GuildLines(), 1)
    Seren("H", time() - 3600)
    Levels(30)
    eq(#GuildLines(), 1) -- back, and longest online again
    Seren("B", time() - 3600)
    Levels(40)
    eq(#GuildLines(), 2)
end)

test("a newer officer leaves it to us", function()
    Online()
    wow.type("/nlc milestones guildchat on")
    Seren("H", time() + 10)
    Levels(20)
    eq(#GuildLines(), 1)
end)

test("without addon messages, each waits a moment and stays quiet if someone else said it", function()
    Online()
    wow.addonResult = 9
    wow.type("/nlc milestones guildchat on")
    wow.wait(60)
    arrives(Roster(20))
    wow.fire("CHAT_MSG_GUILD", CONGRATS, "Seren Vale", "", "", "", "", 0, 0, "", 0, 1, nil, 0)
    wow.wait(9)
    eq(#GuildLines(), 0)
    Levels(30)
    eq(table.concat(GuildLines(), "\n"), "Congratulations to Vespera Ashward on reaching level 30!")
end)

test("guild chat is per guild: an alt elsewhere doesn't post", function()
    local ns = Online()
    wow.type("/nlc milestones guildchat on")
    local saved = ns.db
    ns = start(saved, Roster(), { "Secret", "Alt", guild = "Other Guild", rank = "Officer", class = "MAGE" })
    wow.fire("PLAYER_ENTERING_WORLD", true, false)
    arrives()
    Levels(20)
    eq(#GuildLines(), 0)
    eq(ns.db.milestones.guilds["Other Guild|Forever"].guildChat, nil)
end)

test("a /reload keeps your place as announcer; a new login doesn't", function()
    local ns = Online()
    local first = ns.onlineSince
    eq(ns.db.milestones.onlineSince, first)
    local saved = ns.db
    wow.wait(600)
    ns = start(saved, Roster())
    wow.fire("PLAYER_ENTERING_WORLD", false, true)
    eq(ns.onlineSince, first)
    saved = ns.db
    wow.wait(600)
    ns = start(saved, Roster())
    wow.fire("PLAYER_ENTERING_WORLD", true, false)
    assert(ns.onlineSince > first)
    wow.fire("PLAYER_ENTERING_WORLD", false, false) -- a later loading screen changes nothing
    eq(ns.db.milestones.onlineSince, ns.onlineSince)
end)

test("hellos go out every five minutes while guild chat is on", function()
    Online()
    wow.type("/nlc milestones guildchat on")
    local before = Hellos("H")
    wow.wait(900)
    eq(Hellos("H"), before + 3)
    wow.type("/nlc milestones guildchat off")
    eq(Hellos("B"), 1)
    wow.wait(900)
    eq(Hellos("H"), before + 3)
end)

test("when the game won't let addons post, the officer is told instead", function()
    Online()
    wow.type("/nlc milestones guildchat on")
    wow.lockdown = true
    clearPrinted()
    Levels(20)
    eq(#GuildLines(), 0)
    assert(printed():find("couldn't post this in guild chat: " .. CONGRATS, 1, true), printed())
end)

test("/nlc milestones levels sets the milestones told about in game", function()
    local ns = Online()
    wow.type("/nlc milestones tell on")
    wow.type("/nlc milestones levels 25, 5,25")
    eq(table.concat(ns.Levels(), ","), "5,25")
    clearPrinted()
    Levels(20)
    eq(printed(), "")
    Levels(25)
    assert(printed():find("reached level 25.", 1, true), printed())
    clearPrinted()
    wow.type("/nlc milestones levels ten")
    assert(printed():find("whole numbers", 1, true), printed())
    wow.type("/nlc milestones levels default")
    eq(ns.db.milestones.levels, nil)
end)
