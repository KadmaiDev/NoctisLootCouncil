-- Reading the guild roster: members, and level-ups between reads.

local function Roster()
    return {
        { name = "Vespera Ashward", level = 19, class = "DRUID", rank = "Raider", online = true },
        { name = "Thorn Gale", level = 60, class = "WARRIOR", rank = "Officer" },
        { name = "Kadmai Moonwhisper", level = 41, class = "HUNTER", rank = "Officer", online = true },
    }
end

local function Noctis(ns) return ns.db.guilds["Noctis|Forever"] end

test("the first read notes everyone and counts no level-ups", function()
    local ns = start(nil, Roster())
    arrives()
    local g = Noctis(ns)
    eq(g.name, "Noctis")
    eq(g.realm, "Forever")
    eq(g.scanned, time() - 1) -- read 2 seconds into arrives()'s 3
    eq(g.members["thorn gale"].level, 60)
    eq(g.members["vespera ashward"].class, "DRUID")
    eq(g.members["vespera ashward"].rank, "Raider")
    eq(#g.levels, 0)
end)

test("a level-up between two reads is noted, from the level last seen", function()
    local ns = start(nil, Roster())
    arrives()
    local before = time() - 1
    wow.wait(600)
    local r = Roster()
    r[1].level = 20
    arrives(r)
    local g = Noctis(ns)
    eq(#g.levels, 1)
    local e = g.levels[1]
    eq(e.name, "Vespera Ashward")
    eq(e.class, "DRUID")
    eq(e.from, 19)
    eq(e.to, 20)
    eq(e.at, time() - 1)
    eq(e.since, before)
    eq(g.members["vespera ashward"].level, 20)
end)

test("several levels at once are one level-up, across a save and a new session", function()
    local ns = start(nil, Roster())
    arrives()
    local saved = ns.db
    wow.wait(86400)
    local r = Roster()
    r[1].level = 31
    ns = start(saved, r)
    arrives()
    local g = Noctis(ns)
    eq(#g.levels, 1)
    eq(g.levels[1].from, 19)
    eq(g.levels[1].to, 31)
end)

test("a name with a realm on the end is the same member", function()
    local ns = start(nil, Roster())
    arrives()
    local r = Roster()
    r[1].name, r[1].level = "Vespera Ashward-Forever", 20
    arrives(r)
    local g = Noctis(ns)
    eq(#g.levels, 1)
    eq(g.levels[1].name, "Vespera Ashward")
    eq(g.members["vespera ashward-forever"], nil)
end)

test("members the client hasn't loaded, or sends as secrets, are skipped", function()
    local r = Roster()
    r[4] = { name = "Half Loaded", level = 0 }
    r[5] = { name = wow.SECRET, level = 30 }
    r[6] = { name = "Hidden Level", level = wow.SECRET }
    r[7] = { name = nil, level = 20 }
    local ns = start(nil, r)
    arrives()
    local g = Noctis(ns)
    eq(g.members["half loaded"], nil)
    eq(g.members["hidden level"], nil)
    local n = 0
    for _ in pairs(g.members) do n = n + 1 end
    eq(n, 3)
end)

test("a lower level (a character made again) isn't a level-up", function()
    local ns = start(nil, Roster())
    arrives()
    local r = Roster()
    r[2].level = 1
    arrives(r)
    local g = Noctis(ns)
    eq(#g.levels, 0)
    eq(g.members["thorn gale"].level, 1)
end)

test("each guild is kept apart, and a character outside any guild notes nothing", function()
    local ns = start(nil, Roster())
    arrives()
    local saved = ns.db
    local r = Roster()
    r[1].level = 25 -- the other guild happens to have a Vespera too
    ns = start(saved, r, { "Alt", "Elsewhere", guild = "Other Guild", rank = "Member", class = "MAGE" })
    arrives()
    eq(#ns.db.guilds["Noctis|Forever"].levels, 0)
    eq(ns.db.guilds["Other Guild|Forever"].members["vespera ashward"].level, 25)
    saved = ns.db
    ns = start(saved, Roster(), { "Lone", "Wolf", class = "ROGUE" })
    arrives()
    eq(ns.db.guilds["|Forever"], nil)
    local n = 0
    for _ in pairs(ns.db.guilds) do n = n + 1 end
    eq(n, 2)
end)

test("a guild on another realm is told apart by its realm", function()
    local ns = start(nil, Roster(),
        { "Kadmai", "Moonwhisper", guild = "Noctis", rank = "Officer", class = "HUNTER", guildRealm = "Elsewhere" })
    arrives()
    assert(ns.db.guilds["Noctis|Elsewhere"])
    eq(ns.db.guilds["Noctis|Forever"], nil)
end)

test("the roster is asked for at login and every minute after", function()
    start(nil, Roster())
    eq(wow.rosterRequests, 1)
    wow.wait(60)
    eq(wow.rosterRequests, 2)
    wow.wait(600)
    eq(wow.rosterRequests, 12)
end)

test("a burst of roster updates is read once", function()
    local ns = start(nil, Roster())
    local scans, scan = 0, ns.Scan
    ns.Scan = function() scans = scans + 1 return scan() end
    for _ = 1, 5 do wow.rosterArrives() end
    wow.wait(3)
    eq(scans, 1)
    wow.rosterArrives()
    wow.wait(3)
    eq(scans, 2)
end)

test("level-ups older than 30 days are dropped", function()
    local ns = start(nil, Roster())
    arrives()
    local r = Roster()
    r[1].level = 20
    arrives(r)
    wow.wait(31 * 86400)
    r[1].level = 21
    arrives(r)
    local g = Noctis(ns)
    eq(#g.levels, 1)
    eq(g.levels[1].to, 21)
end)

test("/nms says what it has noted", function()
    local ns = start(nil, Roster())
    clearPrinted()
    wow.type("/nms")
    assert(printed():find("hasn't been read yet", 1, true), printed())
    arrives()
    local r = Roster()
    r[1].level = 20
    arrives(r)
    clearPrinted()
    wow.type("/nms")
    assert(printed():find("Noctis (Forever): 3 members, roster read just now; 1 level-ups noted", 1, true), printed())
    assert(printed():find("Vespera Ashward|r 19 to 20", 1, true), printed())
    assert(printed():find("after you log out or /reload", 1, true), printed())
    start(ns.db, nil, { "Lone", "Wolf", class = "ROGUE" })
    clearPrinted()
    wow.type("/nms status")
    assert(printed():find("isn't in a guild", 1, true), printed())
end)

test("/nms scan asks the server for the roster", function()
    start(nil, Roster())
    local before = wow.rosterRequests
    wow.type("/nms scan")
    eq(wow.rosterRequests, before + 1)
end)
