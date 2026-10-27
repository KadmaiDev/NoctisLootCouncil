-- Decisions from Discord. Officers decide council or roll (and a priority note) in Discord;
-- the companion app on an officer's PC writes them into a small addon of its own,
-- NoctisLootDecisions, which sets the global NoctisLootDecisions when the game loads it. At
-- login the newest decisions are applied to the list, once: an item decided in game since
-- keeps that decision until Discord changes something again.
--
--   NoctisLootDecisions = { at = time(), items = { [itemID] = { h = "council"|"roll", note, name } } }
--
-- The other direction needs nothing here: the companion app reads the saved file.
local ADDON, ns = ...
if ns.disabled then return end
local L = ns.L

local type, pairs, date = type, pairs, date

local HANDLING = { council = true, roll = true }

-- Applies a decisions table. Returns the counts of council and roll items, or nil if it's
-- not newer than the decisions already applied (or isn't decisions at all).
function ns.ApplyDecisions(d)
    if type(d) ~= "table" or type(d.at) ~= "number" or type(d.items) ~= "table" then return nil end
    local db = ns.db
    if db.decisionsAt and d.at <= db.decisionsAt then return nil end
    local council, roll = 0, 0
    for id, dec in pairs(d.items) do
        if type(id) == "number" and type(dec) == "table" and HANDLING[dec.h] then
            local name = type(dec.name) == "string" and dec.name or nil
            local item = db.items[id] or ns.AddUnseen(id, nil, name)
            item.handling = dec.h
            item.note = type(dec.note) == "string" and dec.note ~= "" and dec.note or nil
            if dec.h == "council" then council = council + 1 else roll = roll + 1 end
        end
    end
    db.decisionsAt = d.at
    return council, roll
end

ns.On("PLAYER_LOGIN", function()
    if not ns.db then return end
    local council, roll = ns.ApplyDecisions(NoctisLootDecisions)
    if council then
        ns.Say(L["Decisions from %s: %d council, %d roll."]:format(date("%d %b, %H:%M", ns.db.decisionsAt), council, roll))
    end
end)
