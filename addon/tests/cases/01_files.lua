-- The files themselves: rules that keep the addon safe in the game.

local function Read(path)
    local f = assert(io.open(path, "rb"))
    local s = f:read("*a")
    f:close()
    return s
end

test("the two .toc files are identical", function()
    eq(Read("NoctisLootCouncil.toc"), Read("NoctisLootCouncil_Camelot.toc"))
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
    local before = SlashCmdList.NOCTISLOOTCOUNCIL
    local ns2 = {}
    for _, file in ipairs(FILES) do assert(loadfile(file))("NoctisLootCouncilDev", ns2) end
    assert(ns2.disabled)
    eq(SlashCmdList.NOCTISLOOTCOUNCIL, before)
    wow.fire("PLAYER_LOGIN")
    assert(printed():find("two copies are enabled (NoctisLootCouncil and NoctisLootCouncilDev)", 1, true), printed())
end)

test("no Blizzard global is assigned (it would taint it)", function()
    for _, file in ipairs(FILES) do
        local src = Read(file)
        for _, name in ipairs({ "StaticPopupDialogs", "UISpecialFrames", "ChatFrame_OpenChat", "SendChatMessage", "RandomRoll" }) do
            assert(not src:find("\n%s*" .. name .. "%s*="), file .. " assigns " .. name)
        end
    end
end)

test("no OnUpdate handlers", function()
    for _, file in ipairs(FILES) do
        for line in Read(file):gmatch("[^\n]*OnUpdate[^\n]*") do
            assert(line:match("^%s*%-%-"), file .. ": " .. line)
        end
    end
end)

test("no English text reaches the player without going through the translation table", function()
    local sinks = { "AddLine%(", "SetText%(", "Say%(", "print%(" }
    for _, file in ipairs(FILES) do
        local n = 0
        for line in io.lines(file) do
            n = n + 1
            local code = line:gsub("%-%-.*$", "")
            for _, sink in ipairs(sinks) do
                for literal in code:gmatch(sink .. '%s*"([^"]*)"') do
                    local plain = literal:gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", ""):gsub("[%s:]+$", "")
                    if plain:find("%a%a") and plain ~= "Noctis Loot Council" then
                        error(file .. ":" .. n .. ": untranslated text: " .. literal)
                    end
                end
            end
        end
    end
end)

test("a damaged save is repaired at load, keeping what's sound", function()
    local good = wow.link(1001, "Good Helm")
    local ns = start({
        v = "x", minQuality = "high", dungeons = 1,
        items = { [1001] = { link = good, q = 4, seen = 2, from = { e10 = 2, [5] = 1, bad = "x" }, note = 7 },
            ["1002"] = { link = "x" }, [1003] = "broken" },
        encounters = { [10] = { name = "Lucifron", inst = "409" }, x = {} },
        bossSources = { n100 = 10, n101 = "10" },
        instances = { [409] = "Molten Core", [1] = 5 },
    })
    local db = ns.db
    eq(db.v, 1)
    eq(db.minQuality, nil)
    eq(db.dungeons, nil)
    eq(db.items[1001].link, good)
    eq(db.items[1001].note, nil)
    eq(db.items[1001].from.e10, 2)
    eq(db.items[1001].from.bad, nil)
    eq(db.items[1001].from[5], nil)
    eq(db.items["1002"], nil)
    eq(db.items[1003], nil)
    eq(db.encounters[10].name, "Lucifron")
    eq(db.encounters[10].inst, nil)
    eq(db.encounters.x, nil)
    eq(db.bossSources.n100, 10)
    eq(db.bossSources.n101, nil)
    eq(db.instances[409], "Molten Core")
    eq(db.instances[1], nil)
end)

test("names: first name and surname joined, and compared in either form", function()
    local ns = start()
    eq(ns.PlayerName(), "Kadmai Moonwhisper")
    eq(ns.NameKey("Kadmai Moonwhisper"), "kadmai moonwhisper")
    eq(ns.NameKey("Kadmai Moonwhisper-ClassicPvE"), "kadmai moonwhisper")
    eq(ns.NameKey(wow.SECRET), nil)
    eq(ns.NameKey(""), nil)
end)
