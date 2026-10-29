-- One player's game for the raid realm (harness/realm/realm.py): the real addon on the fake
-- WoW: Forever client (addon/tests/wow.lua), driven over stdin/stdout. Run from the addon folder:
--   luajit ../harness/realm/client.lua
--
-- Each line in is a command, fields separated by tabs (with \\, \t and \n escaped). While it
-- runs, what the player's game sends to the world comes out as "out" lines:
--   out chat <chatType> <text>              a chat line (raid chat, raid warning)
--   out addon <prefix> <text> <channel> <target>
--   out roll <low> <high>                   /roll: the realm picks the number and tells everyone
--   out print <text>                        what the addon printed in the player's chat frame
-- and then "ok <json>" (the command's result) or "err <message>".
package.path = "tests/?.lua;" .. package.path
io.stdout:setvbuf("full")

wow = require("wow")

local FILES = {}
for line in io.lines("NoctisLootCouncil.toc") do
    line = line:match("^%s*(.-)%s*$")
    if line ~= "" and not line:match("^#") then FILES[#FILES + 1] = line end
end

-- Fields --------------------------------------------------------------------

local function esc(s)
    return (tostring(s):gsub("\\", "\\\\"):gsub("\t", "\\t"):gsub("\n", "\\n"))
end
local function unesc(s)
    return (s:gsub("\\(.)", function(c) return c == "t" and "\t" or c == "n" and "\n" or c end))
end
local function split(line)
    local out = {}
    for field in (line .. "\t"):gmatch("(.-)\t") do out[#out + 1] = unesc(field) end
    return out
end
local function emit(...)
    local parts = { "out" }
    for i = 1, select("#", ...) do parts[#parts + 1] = esc(select(i, ...)) end
    io.stdout:write(table.concat(parts, "\t"), "\n")
end

-- A typed argument: s:text, n:number, b:1/0, z: (nil).
local function typed(a)
    local t, v = a:sub(1, 1), a:sub(3)
    if t == "n" then return tonumber(v) elseif t == "b" then return v == "1" elseif t == "z" then return nil end
    return v
end

-- JSON, for results -------------------------------------------------------------

local function json(v, seen)
    local t = type(v)
    if t == "nil" then return "null"
    elseif t == "boolean" then return tostring(v)
    elseif t == "number" then
        if v ~= v or v == math.huge or v == -math.huge then return "null" end
        return v == math.floor(v) and string.format("%d", v) or string.format("%.17g", v)
    elseif t == "string" then
        return '"' .. v:gsub('[%c"\\]', function(c)
            if c == '"' then return '\\"' elseif c == "\\" then return "\\\\" end
            return string.format("\\u%04x", c:byte())
        end) .. '"'
    elseif t == "table" then
        seen = seen or {}
        if seen[v] then return "null" end
        seen[v] = true
        local n = #v
        local isList = n > 0 or next(v) == nil
        if isList then
            for k in pairs(v) do
                if type(k) ~= "number" or k < 1 or k > n or k ~= math.floor(k) then isList = false break end
            end
        end
        local parts = {}
        if isList then
            for i = 1, n do parts[i] = json(v[i], seen) end
            seen[v] = nil
            return "[" .. table.concat(parts, ",") .. "]"
        end
        for k, x in pairs(v) do
            if type(x) ~= "function" and type(x) ~= "userdata" then
                parts[#parts + 1] = json(tostring(k)) .. ":" .. json(x, seen)
            end
        end
        table.sort(parts)
        seen[v] = nil
        return "{" .. table.concat(parts, ",") .. "}"
    end
    return "null"
end

-- The saved file, as the client writes it ----------------------------------------

local function luaString(s) return '"' .. s:gsub("\\", "\\\\"):gsub('"', '\\"'):gsub("\n", "\\n") .. '"' end
local function serialize(v, indent, out)
    local t = type(v)
    if t == "string" then out[#out + 1] = luaString(v)
    elseif t == "number" then out[#out + 1] = v == math.floor(v) and string.format("%d", v) or string.format("%.17g", v)
    elseif t == "boolean" then out[#out + 1] = tostring(v)
    elseif t == "table" then
        out[#out + 1] = "{\n"
        local n = #v
        for i = 1, n do
            out[#out + 1] = indent .. "\t"
            serialize(v[i], indent .. "\t", out)
            out[#out + 1] = ", -- [" .. i .. "]\n"
        end
        local keys = {}
        for k, x in pairs(v) do
            local listed = type(k) == "number" and k >= 1 and k <= n and k == math.floor(k)
            local storable = type(x) == "string" or type(x) == "number" or type(x) == "boolean" or type(x) == "table"
            if not listed and storable and (type(k) == "string" or type(k) == "number") then keys[#keys + 1] = k end
        end
        table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
        for _, k in ipairs(keys) do
            out[#out + 1] = indent .. "\t" .. (type(k) == "string" and "[" .. luaString(k) .. "]" or "[" .. k .. "]") .. " = "
            serialize(v[k], indent .. "\t", out)
            out[#out + 1] = ",\n"
        end
        out[#out + 1] = indent .. "}"
    else
        out[#out + 1] = "nil"
    end
end

-- Finding things on screen ---------------------------------------------------------

-- Visible frames whose text is `label`, newest first (a window opened later is on top).
local function visibleWithText(label, kinds)
    local out = {}
    for i = #wow.frames, 1, -1 do
        local f = wow.frames[i]
        if (not kinds or kinds[f.kind]) and f.text == label and f:IsVisible() then out[#out + 1] = f end
    end
    return out
end

-- Whether a frame, or anything made on it, shows text containing `needle`.
local function shows(frame, needle)
    for _, f in ipairs(wow.frames) do
        local p = f
        while p do
            if p == frame then
                if type(f.text) == "string" and f.text:find(needle, 1, true) and f:IsVisible() then return true end
                break
            end
            p = p.parent
        end
    end
    return false
end

local BUTTONS = { Button = true, CheckButton = true }

local commands = {}

-- load <first> <last> <class> <rank> <guild> <clock> <saved file> <decisions file>
function commands.load(first, last, class, rank, guild, clock, savedPath, decisionsPath)
    NoctisLootCouncilDB = nil
    if savedPath ~= "" and io.open(savedPath) then dofile(savedPath) end
    wow.saved = NoctisLootCouncilDB
    local ns = wow.load(FILES)
    wow.player = { first, last, guild = guild ~= "" and guild or nil, rank = rank, class = class }
    wow.clock = tonumber(clock)
    -- What the game sends to the world goes to the realm, which delivers it (to us too).
    C_ChatInfo.SendChatMessage = function(text, chatType, _, target)
        assert(#text <= 255, "chat line over 255 characters")
        wow.sent[#wow.sent + 1] = { text, chatType }
        emit("chat", chatType or "SAY", text, target or "")
    end
    C_ChatInfo.SendAddonMessage = function(prefix, text, channel, target)
        assert(#text <= 255, "addon message over 255 bytes")
        if wow.addonResult and wow.addonResult ~= 0 then return wow.addonResult end
        emit("addon", prefix, text, channel, target or "")
        return 0
    end
    RandomRoll = function(low, high) emit("roll", low, high) end
    print = function(msg)
        wow.printed[#wow.printed + 1] = msg
        emit("print", tostring(msg))
    end
    NoctisLootDecisions = nil
    if decisionsPath ~= "" and io.open(decisionsPath) then dofile(decisionsPath) end
    wow.login()
    return ns.db and ns.db.me
end

-- raid <First,Last,CLASS,rank,guild,leader> ...  (the others in the raid; guild "" = outside the
-- guild; leader "1" = leads the raid, so their addon's session messages count)
function commands.raid(...)
    local members = {}
    for _, m in ipairs({ ... }) do
        local first, last, class, rank, guild, leader = m:match("^(.-),(.-),(.-),(.-),(.-),(.*)$")
        members[#members + 1] = { first, last, class = class, rank = rank, guild = guild ~= "" and guild or false,
            leader = leader == "1" }
    end
    wow.raid(members)
end

function commands.leader(on) wow.leader = on == "1" end
function commands.fire(event, ...)
    local args = { ... }
    for i = 1, #args do args[i] = typed(args[i]) end
    wow.fire(event, unpack(args, 1, #args))
end
function commands.wait(seconds) wow.wait(tonumber(seconds)) end
function commands.type(line) wow.type(line) end
function commands.close() wow.close() end

-- open <link> <quality> <guid> ...   the loot window
function commands.open(...)
    local a, slots = { ... }, {}
    for i = 1, #a, 3 do slots[#slots + 1] = { a[i], tonumber(a[i + 1]), a[i + 2] } end
    wow.open(slots)
end

-- click <label> [<text shown in the same row or window>]: presses a visible button.
function commands.click(label, near)
    for _, f in ipairs(visibleWithText(label, BUTTONS)) do
        if not near or near == "" or shows(f.parent, near) then
            if f.disabled then error("button " .. label .. " is disabled") end
            f:Click()
            return true
        end
    end
    error("no visible button " .. label .. (near and near ~= "" and (" near " .. near) or ""))
end

-- check <label>: ticks the check box labelled `label` (the pop-up's tags).
function commands.check(label)
    for i = #wow.frames, 1, -1 do
        local f = wow.frames[i]
        if f.kind == "CheckButton" and f.label and f.label.text == label and f:IsVisible() then
            f:SetChecked(not f:GetChecked())
            f:Run("OnClick")
            return f:GetChecked()
        end
    end
    error("no visible check box " .. label)
end

-- settext <frame name> <text>: types into a named edit box.
function commands.settext(name, text)
    local f = _G[name]
    if not f then error("no frame " .. name) end
    f:SetText(text)
    f:Run("OnTextChanged", true)
end

function commands.equip(id, itemType, subtype, loc, class, sub)
    wow.equip[tonumber(id)] = { itemType, subtype, loc, class = tonumber(class), sub = tonumber(sub) }
end
function commands.gear(slot, link) wow.gear[tonumber(slot)] = link end
function commands.stats(id, ...)
    local s = {}
    for _, kv in ipairs({ ... }) do
        local k, v = kv:match("^(.-)=(.*)$")
        s[k] = tonumber(v)
    end
    wow.stats[tonumber(id)] = s
end
function commands.itemloads(id, name, q) wow.itemLoads(tonumber(id), name, tonumber(q)) end

-- save <path>: the game writes the saved file (at logout or /reload).
function commands.save(path)
    local out = { "\nNoctisLootCouncilDB = " }
    serialize(NoctisLootCouncilDB, "", out)
    out[#out + 1] = "\n"
    local f = assert(io.open(path, "wb"))
    f:write(table.concat(out))
    f:close()
end

-- query <expression>: its value as JSON (ns is the addon's namespace).
function commands.query(expr)
    local fn = assert(loadstring("local ns = wow.ns; return " .. expr))
    return fn()
end

-- What's on screen: every visible text, newest frame first.
function commands.screen()
    local out = {}
    for i = #wow.frames, 1, -1 do
        local f = wow.frames[i]
        if type(f.text) == "string" and f.text ~= "" and f:IsVisible() then out[#out + 1] = f.text end
    end
    return out
end

for line in io.lines() do
    local fields = split(line)
    local name = table.remove(fields, 1)
    local cmd = commands[name]
    local ok, result
    if not cmd then
        ok, result = false, "unknown command " .. tostring(name)
    else
        ok, result = xpcall(function() return cmd(unpack(fields)) end, debug.traceback)
    end
    if ok then
        io.stdout:write("ok\t", json(result), "\n")
    else
        io.stdout:write("err\t", esc(result), "\n")
    end
    io.stdout:flush()
end
