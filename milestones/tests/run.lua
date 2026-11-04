-- Test runner. From the milestones folder: luajit tests/run.lua
-- The fake client is Noctis Loot Council's (addon/tests/wow.lua), shared so both addons are
-- tested against the same idea of the game.
package.path = "../addon/tests/?.lua;" .. package.path
wow = require("wow")

ADDON_NAME, SAVED = "NoctisMilestones", "NoctisMilestonesDB"
FILES = {}
for line in io.lines(ADDON_NAME .. ".toc") do
    line = line:match("^%s*(.-)%s*$")
    if line ~= "" and not line:match("^#") then FILES[#FILES + 1] = line end
end
tests, passed, failed = {}, 0, 0

function test(name, fn) tests[#tests + 1] = { name = name, fn = fn } end

function eq(actual, expected, msg)
    if actual ~= expected then
        error((msg or "values differ") .. ": expected " .. tostring(expected) .. ", got " .. tostring(actual), 2)
    end
end

-- Loads the addon (with this saved data, if any) and logs in. roster, if given, is the guild;
-- player, if given, who logs in (else Kadmai Moonwhisper of Noctis).
function start(saved, roster, player)
    wow.saved = saved
    local ns = wow.load(FILES, ADDON_NAME, SAVED)
    wow.roster = roster or {}
    if player then wow.player = player end
    wow.login(ADDON_NAME)
    return ns
end

-- The server sends the roster and the addon reads it once the burst has settled.
function arrives(roster)
    wow.rosterArrives(roster)
    wow.wait(3)
end

function printed() return table.concat(wow.printed, "\n") end

function clearPrinted() wow.printed = {} end

CASES = { "01_files.lua", "02_roster.lua" }
for _, file in ipairs(CASES) do assert(loadfile("tests/cases/" .. file))() end

for _, t in ipairs(tests) do
    local ok, err = pcall(t.fn)
    if ok then
        passed = passed + 1
        io.write("  ok    ", t.name, "\n")
    else
        failed = failed + 1
        io.write("  FAIL  ", t.name, "\n        ", tostring(err), "\n")
    end
end
io.write(("\n%d passed, %d failed\n"):format(passed, failed))
os.exit(failed == 0 and 0 or 1)
