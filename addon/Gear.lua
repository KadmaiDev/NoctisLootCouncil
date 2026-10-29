-- What you wear in a council item's slots, sent with your bid so the council sees what it
-- would replace.
local ADDON, ns = ...
if ns.disabled then return end

local ipairs, type, tostring, concat = ipairs, type, tostring, table.concat
local Plain = ns.Plain

local SLOTS = {
    INVTYPE_HEAD = { 1 }, INVTYPE_NECK = { 2 }, INVTYPE_SHOULDER = { 3 }, INVTYPE_CHEST = { 5 },
    INVTYPE_ROBE = { 5 }, INVTYPE_WAIST = { 6 }, INVTYPE_LEGS = { 7 }, INVTYPE_FEET = { 8 },
    INVTYPE_WRIST = { 9 }, INVTYPE_HAND = { 10 }, INVTYPE_FINGER = { 11, 12 }, INVTYPE_TRINKET = { 13, 14 },
    INVTYPE_CLOAK = { 15 }, INVTYPE_WEAPON = { 16, 17 }, INVTYPE_2HWEAPON = { 16 },
    INVTYPE_WEAPONMAINHAND = { 16 }, INVTYPE_WEAPONOFFHAND = { 17 }, INVTYPE_SHIELD = { 17 },
    INVTYPE_HOLDABLE = { 17 }, INVTYPE_RANGED = { 18 }, INVTYPE_RANGEDRIGHT = { 18 },
    INVTYPE_THROWN = { 18 }, INVTYPE_RELIC = { 18 },
}

local function Worn(slot)
    local link = GetInventoryItemLink and GetInventoryItemLink("player", slot)
    if Plain(link) and type(link) == "string" then return link end
end

-- The item IDs you wear in an item's slots, comma-separated (0 for an empty slot).
function ns.WornIDs(link)
    local _, _, _, loc = C_Item.GetItemInfoInstant(link)
    local ids = {}
    for _, slot in ipairs(SLOTS[loc] or {}) do
        local w = Worn(slot)
        ids[#ids + 1] = w and tostring(ns.ItemID(w) or 0) or "0"
    end
    return concat(ids, ",")
end
