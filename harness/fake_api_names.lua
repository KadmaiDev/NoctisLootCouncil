-- Lists what the fake client (addon/tests/wow.lua) provides, as JSON on stdout: the global
-- functions and C_ namespace functions it defines, and the events it knows. Run from the addon
-- folder: luajit ../harness/fake_api_names.lua
package.path = "tests/?.lua;" .. package.path
local before = {}
for k in pairs(_G) do before[k] = true end
local wow = require("wow")
wow.load({})

local globals, namespaces = {}, {}
for k, v in pairs(_G) do
    if type(k) == "string" and not before[k] then
        if type(v) == "function" then
            globals[#globals + 1] = k
        elseif type(v) == "table" and k:match("^C_") then
            local fns = {}
            for name, f in pairs(v) do
                if type(f) == "function" then fns[#fns + 1] = name end
            end
            table.sort(fns)
            namespaces[k] = fns
        end
    end
end
table.sort(globals)

local events = {}
local src = assert(io.open("tests/wow.lua")):read("*a")
local known = src:match("local KNOWN_EVENTS = (%b{})")
for name in known:gmatch("([%u_]+) = true") do events[#events + 1] = name end

local function list(t)
    local out = {}
    for i, v in ipairs(t) do out[i] = '"' .. v .. '"' end
    return "[" .. table.concat(out, ",") .. "]"
end
local ns = {}
for k, v in pairs(namespaces) do ns[#ns + 1] = '"' .. k .. '":' .. list(v) end
io.write('{"globals":', list(globals), ',"namespaces":{', table.concat(ns, ","), '},"events":', list(events), "}\n")
