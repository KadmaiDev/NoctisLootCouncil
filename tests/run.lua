-- Test runner. From the addon folder: luajit tests/run.lua
package.path = "tests/?.lua;" .. package.path
wow = require("wow")

-- The addon's files, in load order, read from the .toc so the two never differ.
FILES = {}
for line in io.lines("NoctisLootCouncil.toc") do
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

-- Loads the addon (with this saved data, if any) and logs in.
function start(saved)
    wow.saved = saved
    local ns = wow.load(FILES)
    wow.login()
    return ns
end

function printed() return table.concat(wow.printed, "\n") end

function clearPrinted() wow.printed = {} end

CASES = { "01_files.lua", "02_discovery.lua", "03_commands.lua", "04_rolls.lua", "05_sync.lua", "06_export.lua", "07_popup.lua", "08_council.lua", "09_council_window.lua", "10_loot_window.lua" }
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
