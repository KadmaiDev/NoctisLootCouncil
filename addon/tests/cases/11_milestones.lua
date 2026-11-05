-- Level milestones (Milestones.lua): reading the guild roster, members and level-ups between
-- reads, only when turned on and only on an officer.

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


local function Roster()
    return {
        { name = "Vespera Ashward", level = 19, class = "DRUID", rank = "Raider", online = true },
        { name = "Thorn Gale", level = 60, class = "WARRIOR", rank = "Officer" },
        { name = "Kadmai Moonwhisper", level = 41, class = "HUNTER", rank = "Officer", online = true },
    }
end

local function Noctis(ns) return ns.db.milestones.guilds["Noctis|Forever"] end

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
    ns = start(saved, r, { "Alt", "Elsewhere", guild = "Other Guild", rank = "Officer", class = "MAGE" })
    arrives()
    eq(#ns.db.milestones.guilds["Noctis|Forever"].levels, 0)
    eq(ns.db.milestones.guilds["Other Guild|Forever"].members["vespera ashward"].level, 25)
    saved = ns.db
    ns = start(saved, Roster(), { "Lone", "Wolf", class = "ROGUE" })
    arrives()
    eq(ns.db.milestones.guilds["|Forever"], nil)
    local n = 0
    for _ in pairs(ns.db.milestones.guilds) do n = n + 1 end
    eq(n, 2)
end)

test("a guild on another realm is told apart by its realm", function()
    local ns = start(nil, Roster(),
        { "Kadmai", "Moonwhisper", guild = "Noctis", rank = "Officer", class = "HUNTER", guildRealm = "Elsewhere" })
    arrives()
    assert(ns.db.milestones.guilds["Noctis|Elsewhere"])
    eq(ns.db.milestones.guilds["Noctis|Forever"], nil)
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

test("/nlc milestones says what it has noted", function()
    local ns = start(nil, Roster())
    clearPrinted()
    wow.type("/nlc milestones")
    assert(printed():find("hasn't been read yet", 1, true), printed())
    arrives()
    local r = Roster()
    r[1].level = 20
    arrives(r)
    clearPrinted()
    wow.type("/nlc milestones")
    assert(printed():find("Noctis (Forever): 3 members, roster read just now; 1 level-ups noted", 1, true), printed())
    assert(printed():find("Vespera Ashward|r 19 to 20", 1, true), printed())
    assert(printed():find("after you log out or /reload", 1, true), printed())
    start(ns.db, nil, { "Lone", "Wolf", class = "ROGUE" })
    clearPrinted()
    wow.type("/nlc milestones status")
    assert(printed():find("isn't in a guild", 1, true), printed())
end)

test("/nlc milestones scan asks the server for the roster", function()
    start(nil, Roster())
    local before = wow.rosterRequests
    wow.type("/nlc milestones scan")
    eq(wow.rosterRequests, before + 1)
end)

test("a damaged milestones save is repaired at load, keeping what's sound", function()
    local ns = start({ milestones = {
        on = "yes", tell = true, levels = { 30, "x", 1, 10 },
        guilds = {
            ["Noctis|Forever"] = {
                name = "Noctis", scanned = "today",
                members = { ["vespera ashward"] = { name = "Vespera Ashward", level = 12, seen = 1, rank = 3 },
                    broken = { name = "No Level", seen = 1 }, [4] = { name = "x", level = 1, seen = 1 } },
                levels = { { name = "Vespera Ashward", from = 11, to = 12, at = 1, class = 7 }, "x",
                    { name = "Half", from = 1 } },
            },
            ["Nameless|Forever"] = { realm = "Forever" },
            [3] = {},
        },
    } })
    local db = ns.db.milestones
    eq(db.on, nil)
    eq(db.tell, true)
    eq(table.concat(db.levels, ","), "10,30")
    local g = db.guilds["Noctis|Forever"]
    eq(g.realm, "")
    eq(g.scanned, nil)
    eq(g.members["vespera ashward"].level, 12)
    eq(g.members["vespera ashward"].rank, nil)
    eq(g.members.broken, nil)
    eq(g.members[4], nil)
    eq(#g.levels, 1)
    eq(g.levels[1].class, nil)
    eq(db.guilds["Nameless|Forever"], nil)
    eq(db.guilds[3], nil)
end)

test("off until turned on: no roster asked for, read or saved", function()
    local ns = start({}, Roster())
    wow.fire("PLAYER_ENTERING_WORLD", true, false)
    arrives()
    eq(wow.rosterRequests, 0)
    eq(ns.db.milestones, nil)
    clearPrinted()
    wow.type("/nlc milestones")
    assert(printed():find("level milestones are off. Officers: /nlc milestones on", 1, true), printed())
    clearPrinted()
    wow.type("/nlc milestones tell on")
    assert(printed():find("are off", 1, true), printed())
    eq(ns.db.milestones, nil)
    wow.type("/nlc milestones on")
    eq(ns.db.milestones.on, true)
    eq(wow.rosterRequests, 1)
    arrives()
    eq(Noctis(ns).members["thorn gale"].level, 60)
end)

test("on, but not an officer: nothing is asked for, read or said", function()
    local raider = { "Vespera", "Ashward", guild = "Noctis", rank = "Raider", class = "DRUID" }
    local ns = start({}, Roster(), raider)
    clearPrinted()
    wow.type("/nlc milestones on")
    assert(printed():find("isn't an officer in Noctis, so it stays quiet here", 1, true), printed())
    wow.type("/nlc milestones tell on")
    clearPrinted()
    wow.type("/nlc milestones")
    assert(printed():find("isn't an officer in Noctis, so nothing is read or said here", 1, true), printed())
    wow.fire("PLAYER_ENTERING_WORLD", true, false)
    arrives()
    local r = Roster()
    r[2].level = 61
    wow.wait(60)
    arrives(r)
    wow.wait(600)
    eq(wow.rosterRequests, 0)
    eq(next(ns.db.milestones.guilds), nil)
    eq(#wow.addon, 0)
    eq(#wow.sent, 0)
    clearPrinted()
    wow.type("/nlc milestones scan")
    assert(printed():find("isn't an officer", 1, true), printed())
end)

test("a rank with officer notes counts, a demotion stops it, and a game that can't tell means no", function()
    local ns = start(nil, Roster())
    C_GuildInfo.IsGuildOfficer = function() return nil end
    assert(ns.IsGuildOfficer()) -- CanViewOfficerNote says yes
    wow.player.officer = false  -- demoted
    arrives()
    eq(next(ns.db.milestones.guilds), nil)
    C_GuildInfo.IsGuildOfficer = function() error("no") end
    C_GuildInfo.CanViewOfficerNote = nil
    wow.player.officer = true
    eq(ns.IsGuildOfficer(), false)
end)

test("off again: the roster isn't read, and what was noted stays", function()
    local ns = start(nil, Roster())
    arrives()
    wow.type("/nlc milestones off")
    eq(ns.db.milestones.on, nil)
    local asked = wow.rosterRequests
    local r = Roster()
    r[1].level = 20
    wow.wait(120)
    arrives(r)
    eq(wow.rosterRequests, asked)
    eq(Noctis(ns).members["vespera ashward"].level, 19)
end)
