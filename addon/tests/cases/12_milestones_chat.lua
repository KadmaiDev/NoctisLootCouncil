-- Level milestones in game (MilestonesChat.lua): your own chat window. Nothing goes to guild chat.

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

test("tell is off until turned on: nothing said, nothing sent", function()
    Online()
    clearPrinted()
    Levels(20)
    eq(printed(), "")
    eq(#GuildLines(), 0)
    eq(#wow.addon, 0)
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

test("guild chat is gone: an old save's setting is dropped and nothing is posted or sent", function()
    local ns = Online({ milestones = { on = true, onlineSince = 5, guilds = {
        ["Noctis|Forever"] = { name = "Noctis", realm = "Forever", guildChat = true } } } })
    eq(ns.db.milestones.onlineSince, nil)
    eq(ns.db.milestones.guilds["Noctis|Forever"].guildChat, nil)
    Levels(20)
    eq(#ns.db.milestones.guilds["Noctis|Forever"].levels, 1) -- still noted for Discord
    eq(#wow.sent, 0)
    eq(#wow.addon, 0)
    clearPrinted()
    wow.type("/nlc milestones guildchat on") -- not a command any more: the help
    assert(printed():find("level milestones (officers):", 1, true), printed())
    assert(not printed():find("guildchat", 1, true), printed())
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
