-- The files themselves: rules that keep the addon safe in the game.

local function Read(path)
    local f = assert(io.open(path, "rb"))
    local s = f:read("*a")
    f:close()
    return s
end

test("the two .toc files are identical", function()
    eq(Read("NoctisMilestones.toc"), Read("NoctisMilestones_Camelot.toc"))
end)

test("every file after Core stops when another copy is running", function()
    for _, file in ipairs(FILES) do
        if file ~= "Locales.lua" and file ~= "Core.lua" then
            assert(Read(file):find("local ADDON, ns = %.%.%.\r?\nif ns%.disabled then return end"), file)
        end
    end
end)

test("a second copy stays off, takes no command, and says so", function()
    start()
    local before = SlashCmdList.NOCTISMILESTONES
    local ns2 = {}
    for _, file in ipairs(FILES) do assert(loadfile(file))("NoctisMilestonesDev", ns2) end
    assert(ns2.disabled)
    eq(SlashCmdList.NOCTISMILESTONES, before)
    wow.fire("PLAYER_LOGIN")
    assert(printed():find("two copies are enabled (NoctisMilestones and NoctisMilestonesDev)", 1, true), printed())
end)

test("no OnUpdate handlers", function()
    for _, file in ipairs(FILES) do
        for line in Read(file):gmatch("[^\n]*OnUpdate[^\n]*") do
            assert(line:match("^%s*%-%-"), file .. ": " .. line)
        end
    end
end)

test("no English text reaches the player without going through the translation table", function()
    local sinks = { "SetText%(", "Say%(", "print%(" }
    for _, file in ipairs(FILES) do
        local n = 0
        for line in io.lines(file) do
            n = n + 1
            local code = line:gsub("%-%-.*$", "")
            for _, sink in ipairs(sinks) do
                for literal in code:gmatch(sink .. '%s*"([^"]*)"') do
                    local plain = literal:gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", ""):gsub("[%s:]+$", "")
                    if plain:find("%a%a") and plain ~= "Noctis Milestones" then
                        error(file .. ":" .. n .. ": untranslated text: " .. literal)
                    end
                end
            end
        end
    end
end)

test("a damaged save is repaired at load, keeping what's sound", function()
    local ns = start({
        v = "x", me = 5,
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
    })
    local db = ns.db
    eq(db.v, 1)
    eq(db.me, "Kadmai Moonwhisper")
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
