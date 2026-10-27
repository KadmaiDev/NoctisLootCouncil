-- How big an upgrade a council item is for you, sent with your bid so the council sees it
-- next to your tags and note. Ported from Alts Forever (Upgrades.lua, Talents.lua): an
-- item's score is its stats times what each stat is worth to your role; the upgrade is the
-- new item's score minus what you wear in that slot (the weaker ring or trinket, main and off
-- hand together for a two-hander), as a % of the score of everything you wear. Against the
-- whole set, not the item replaced: a weak old item made tiny gains look huge (+583% for +1
-- Agility over an armour-only belt, Alts Forever, 2026-10-16).
--
-- Only plain stats count: on-use and proc effects, set bonuses and resistances score
-- nothing, so trinkets and resistance gear read low; the council goes by tags and notes then.
-- The weights are Alts Forever's levelling ones until the officers settle raid weights.
--
-- Your role: /nlc role (melee, ranged, caster, healer, tank, feral) for this character, else
-- the talent tab with most points, else the class default.
local ADDON, ns = ...
if ns.disabled then return end
local L = ns.L

local pairs, ipairs, type, pcall, sort, max, floor = pairs, ipairs, type, pcall, table.sort, math.max, math.floor
local Plain = ns.Plain

local WEAPON_CLASS, ARMOR_CLASS = 2, 4
local NEW = math.huge -- nothing you wear scores yet

local STATS = {
    ITEM_MOD_STRENGTH_SHORT = "str", ITEM_MOD_AGILITY_SHORT = "agi", ITEM_MOD_STAMINA_SHORT = "sta",
    ITEM_MOD_INTELLECT_SHORT = "int", ITEM_MOD_SPIRIT_SHORT = "spi",
    ITEM_MOD_ATTACK_POWER_SHORT = "ap", ITEM_MOD_RANGED_ATTACK_POWER_SHORT = "rap",
    ITEM_MOD_SPELL_POWER_SHORT = "sp", ITEM_MOD_SPELL_HEALING_DONE_SHORT = "heal",
    ITEM_MOD_POWER_REGEN0_SHORT = "mp5", ITEM_MOD_MANA_REGENERATION_SHORT = "mp5",
    ITEM_MOD_CRIT_RATING_SHORT = "crit", ITEM_MOD_CRIT_MELEE_RATING_SHORT = "crit",
    ITEM_MOD_CRIT_RANGED_RATING_SHORT = "crit", ITEM_MOD_HIT_RATING_SHORT = "hit",
    ITEM_MOD_HIT_MELEE_RATING_SHORT = "hit", ITEM_MOD_HIT_RANGED_RATING_SHORT = "hit",
    ITEM_MOD_CRIT_SPELL_RATING_SHORT = "spellcrit", ITEM_MOD_HIT_SPELL_RATING_SHORT = "spellhit",
    ITEM_MOD_DEFENSE_SKILL_RATING_SHORT = "def", ITEM_MOD_DODGE_RATING_SHORT = "dodge",
    ITEM_MOD_PARRY_RATING_SHORT = "parry", ITEM_MOD_BLOCK_RATING_SHORT = "block",
    ITEM_MOD_BLOCK_VALUE_SHORT = "blockvalue",
    RESISTANCE0_NAME = "armor", ITEM_MOD_DAMAGE_PER_SECOND_SHORT = "dps",
}

local WEIGHTS = {
    hunter = { agi = 2.4, ap = 1, rap = 1, sta = 0.4, int = 0.3, spi = 0.05, crit = 22, hit = 16,
        armor = 0.02, dps = 2, rdps = 14 },
    rogue = { agi = 2, str = 1, ap = 1, sta = 0.4, crit = 20, hit = 18, armor = 0.02, dps = 10, rdps = 1 },
    warrior = { str = 2, agi = 1.4, ap = 1, sta = 0.5, crit = 20, hit = 18, armor = 0.02, dps = 12, rdps = 1 },
    paladin = { str = 2, agi = 1, ap = 1, sta = 0.5, int = 0.4, sp = 0.3, crit = 18, hit = 16,
        armor = 0.02, dps = 12 },
    enhancement = { str = 2, agi = 1.2, ap = 1, sta = 0.5, int = 0.4, crit = 18, hit = 16, armor = 0.02, dps = 12 },
    feral = { str = 2, agi = 1.6, ap = 1, sta = 0.8, crit = 18, hit = 16, armor = 0.05, def = 0.5, dodge = 6 },
    tank = { sta = 1.5, str = 1, agi = 1, armor = 0.1, def = 1.5, dodge = 12, parry = 10, block = 6,
        blockvalue = 0.5, ap = 0.3, hit = 8, dps = 4, rdps = 0.5 },
    caster = { sp = 1, int = 0.5, spi = 0.3, sta = 0.4, mp5 = 1.5, spellcrit = 10, spellhit = 12, rdps = 3 },
    healer = { heal = 1, sp = 0.9, int = 0.6, spi = 0.5, sta = 0.3, mp5 = 2, spellcrit = 8, rdps = 1 },
}

local ROLE_WORDS = {
    hunter = "ranged", rogue = "melee", warrior = "melee", paladin = "melee", enhancement = "melee",
    feral = "feral", tank = "tank", caster = "caster", healer = "healer",
}

-- Per class: the role of each talent tab, the default, armour subclasses, weapon subclasses.
local CLASSES = {
    WARRIOR = { tabs = { "warrior", "warrior", "tank" }, default = "warrior", dualWield = true,
        armor = { [1] = 1, [2] = 1, [3] = 1, [4] = 1, [6] = 1 },
        weapons = { 0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 13, 15, 16, 18 } },
    PALADIN = { tabs = { "healer", "tank", "paladin" }, default = "paladin",
        armor = { [1] = 1, [2] = 1, [3] = 1, [4] = 1, [6] = 1, [7] = 1 },
        weapons = { 0, 1, 4, 5, 6, 7, 8 } },
    HUNTER = { tabs = { "hunter", "hunter", "hunter" }, default = "hunter", dualWield = true,
        armor = { [1] = 1, [2] = 1, [3] = 1 },
        weapons = { 0, 1, 2, 3, 6, 7, 8, 10, 13, 15, 16, 18 } },
    ROGUE = { tabs = { "rogue", "rogue", "rogue" }, default = "rogue", dualWield = true,
        armor = { [1] = 1, [2] = 1 },
        weapons = { 2, 3, 4, 7, 13, 15, 16, 18 } },
    PRIEST = { tabs = { "healer", "healer", "caster" }, default = "caster",
        armor = { [1] = 1 }, weapons = { 4, 10, 15, 19 } },
    SHAMAN = { tabs = { "caster", "enhancement", "healer" }, default = "enhancement",
        armor = { [1] = 1, [2] = 1, [3] = 1, [6] = 1, [9] = 1 },
        weapons = { 0, 1, 4, 5, 10, 13, 15 } },
    MAGE = { tabs = { "caster", "caster", "caster" }, default = "caster",
        armor = { [1] = 1 }, weapons = { 7, 10, 15, 19 } },
    WARLOCK = { tabs = { "caster", "caster", "caster" }, default = "caster",
        armor = { [1] = 1 }, weapons = { 7, 10, 15, 19 } },
    DRUID = { tabs = { "caster", "feral", "healer" }, default = "feral",
        armor = { [1] = 1, [2] = 1, [8] = 1 }, weapons = { 4, 5, 10, 13, 15 } },
}
for _, cls in pairs(CLASSES) do
    local set = {}
    for _, sub in ipairs(cls.weapons) do set[sub] = true end
    cls.weapons = set
end

local SLOTS = {
    INVTYPE_HEAD = { 1 }, INVTYPE_NECK = { 2 }, INVTYPE_SHOULDER = { 3 }, INVTYPE_CHEST = { 5 },
    INVTYPE_ROBE = { 5 }, INVTYPE_WAIST = { 6 }, INVTYPE_LEGS = { 7 }, INVTYPE_FEET = { 8 },
    INVTYPE_WRIST = { 9 }, INVTYPE_HAND = { 10 }, INVTYPE_FINGER = { 11, 12 }, INVTYPE_TRINKET = { 13, 14 },
    INVTYPE_CLOAK = { 15 }, INVTYPE_WEAPON = { 16, 17 }, INVTYPE_2HWEAPON = { 16 },
    INVTYPE_WEAPONMAINHAND = { 16 }, INVTYPE_WEAPONOFFHAND = { 17 }, INVTYPE_SHIELD = { 17 },
    INVTYPE_HOLDABLE = { 17 }, INVTYPE_RANGED = { 18 }, INVTYPE_RANGEDRIGHT = { 18 },
    INVTYPE_THROWN = { 18 }, INVTYPE_RELIC = { 18 },
}
local RANGED = { INVTYPE_RANGED = true, INVTYPE_RANGEDRIGHT = true, INVTYPE_THROWN = true }
local OFF_HAND_ITEMS = { INVTYPE_SHIELD = true, INVTYPE_HOLDABLE = true }

---------------------------------------------------------------------------
-- Your role
---------------------------------------------------------------------------
local spec -- the talent tab with most points, read at login and when talents change

local function MyClass()
    local _, class = UnitClass("player")
    return Plain(class) and CLASSES[class] and class or nil
end

-- Points per tab from { posX, rank } nodes: Forever's talents are one trait tree with the
-- three tabs side by side, so a talent's tab is its column group (Alts Forever, measured).
local TAB_GAP, MIN_POINTS = 1500, 10
function ns.TabPoints(nodes)
    local xs, seen = {}, {}
    for _, n in ipairs(nodes) do
        if not seen[n[1]] then
            seen[n[1]] = true
            xs[#xs + 1] = n[1]
        end
    end
    sort(xs)
    local tabOf, tab = {}, 1
    for i, x in ipairs(xs) do
        if i > 1 and x - xs[i - 1] > TAB_GAP then tab = tab + 1 end
        tabOf[x] = tab > 3 and 3 or tab
    end
    local points = { 0, 0, 0 }
    for _, n in ipairs(nodes) do
        local t = tabOf[n[1]]
        points[t] = points[t] + n[2]
    end
    return points
end

local function SpecFromPoints(points)
    local best, total, tie = 1, 0, false
    for t = 1, 3 do
        total = total + points[t]
        if t > 1 then
            if points[t] > points[best] then best, tie = t, false
            elseif points[t] == points[best] then tie = true end
        end
    end
    if total < MIN_POINTS or tie then return nil end
    return best
end

local function ReadSpec()
    local T = C_Traits
    if not (T and T.GetConfigsByType) then return end
    local kind = Enum and Enum.TraitConfigType and Enum.TraitConfigType.CamelotCombat or 4
    local ok, list = pcall(T.GetConfigsByType, kind)
    local config = ok and type(list) == "table" and list[1]
    if not Plain(config) then return end
    local info = T.GetConfigInfo(config)
    local tree = info and type(info.treeIDs) == "table" and info.treeIDs[1]
    if not Plain(tree) then return end
    local nodes = {}
    for _, id in ipairs(T.GetTreeNodes(tree) or {}) do
        local node = T.GetNodeInfo(config, id)
        local x, rank = node and node.posX, node and node.currentRank
        if Plain(x) and Plain(rank) then nodes[#nodes + 1] = { x, rank } end
    end
    if #nodes > 0 then spec = SpecFromPoints(ns.TabPoints(nodes)) end
end
ns.On("PLAYER_ENTERING_WORLD", function() pcall(ReadSpec) end)
ns.On("TRAIT_CONFIG_UPDATED", function() pcall(ReadSpec) end)

function ns.MyRole()
    local class = MyClass()
    if not class then return nil end
    local cls, chosen = CLASSES[class], ns.db.roles and ns.db.roles[ns.PlayerName() or ""]
    if chosen then
        for _, r in ipairs(cls.tabs) do if r == chosen then return chosen end end
        if chosen == cls.default then return chosen end
    end
    return spec and cls.tabs[spec] or cls.default
end

---------------------------------------------------------------------------
-- Scores
---------------------------------------------------------------------------
-- An item's score for a role, or nil if the game hasn't loaded it yet.
function ns.ItemScore(link, role)
    local w = WEIGHTS[role]
    if not w or not C_Item or not C_Item.GetItemStats then return nil end
    local _, _, _, loc = C_Item.GetItemInfoInstant(link)
    local stats = C_Item.GetItemStats(link)
    if type(stats) ~= "table" then return nil end
    local dps = RANGED[loc] and "rdps" or "dps"
    local score = 0
    for name, value in pairs(stats) do
        local key = STATS[name]
        if key == "dps" then key = dps end
        local weight = key and w[key]
        if weight and Plain(value) and type(value) == "number" then score = score + value * weight end
    end
    return score
end

local function Worn(slot)
    local link = GetInventoryItemLink and GetInventoryItemLink("player", slot)
    if Plain(link) and type(link) == "string" then return link end
end

-- Your upgrade from an item, as a % of your gear's score: a number (math.huge if nothing you
-- wear scores), 0 if it's no upgrade, nil if you can't use it or it isn't loaded yet.
function ns.MyUpgrade(link)
    local class = MyClass()
    local role = ns.MyRole()
    if not class or not role or not Plain(link) then return nil end
    local cls = CLASSES[class]
    local _, _, _, loc, _, itemClass, sub = C_Item.GetItemInfoInstant(link)
    local slots = SLOTS[loc]
    if not slots then return nil end
    if itemClass == ARMOR_CLASS and sub ~= 0 and not cls.armor[sub] then return nil end
    if itemClass == WEAPON_CLASS and not cls.weapons[sub] then return nil end
    local new = ns.ItemScore(link, role)
    if not new then return nil end
    local total = 0
    for slot = 1, 18 do
        local w = slot ~= 4 and Worn(slot)
        if w then total = total + (ns.ItemScore(w, role) or 0) end
    end
    local function Score(slot)
        local w = Worn(slot)
        return w and ns.ItemScore(w, role) or 0
    end
    local mainLoc = Worn(16) and select(4, C_Item.GetItemInfoInstant(Worn(16)))
    local best
    for _, slot in ipairs(slots) do
        local ok = true
        if slot == 17 and loc == "INVTYPE_WEAPON" then
            ok = cls.dualWield and not (Worn(17) and OFF_HAND_ITEMS[select(4, C_Item.GetItemInfoInstant(Worn(17)))])
        end
        if ok then
            local worn = loc == "INVTYPE_2HWEAPON" and Score(16) + Score(17) or Score(slot)
            if loc ~= "INVTYPE_2HWEAPON" and mainLoc == "INVTYPE_2HWEAPON" and (slot == 16 or slot == 17) then
                worn = Score(16) -- one hand against a two-hander: the two-hander's whole score
            end
            local gain = total > 0 and (new - worn) * 100 / total or NEW
            if not best or gain > best then best = gain end
        end
    end
    if not best then return nil end
    return max(best, 0)
end

-- The item IDs you wear in an item's slots, comma-separated (0 for an empty slot), for the
-- council to see what it would replace.
function ns.WornIDs(link)
    local _, _, _, loc = C_Item.GetItemInfoInstant(link)
    local ids = {}
    for _, slot in ipairs(SLOTS[loc] or {}) do
        local w = Worn(slot)
        ids[#ids + 1] = w and tostring(ns.ItemID(w) or 0) or "0"
    end
    return table.concat(ids, ",")
end

-- "+3%" (or "new" when nothing you wear scores), rounded to a whole %.
function ns.UpgradeText(gain)
    if not gain then return nil end
    if gain == NEW then return L["new"] end
    return ("+%d%%"):format(floor(gain + 0.5))
end

ns.Command("role", function(text)
    local word = text:lower()
    local class = MyClass()
    ns.db.roles = ns.db.roles or {}
    local me = ns.PlayerName() or "?"
    if word == "auto" then
        ns.db.roles[me] = nil
    elseif word ~= "" and class then
        local found
        local cls = CLASSES[class]
        for _, r in ipairs(cls.tabs) do if ROLE_WORDS[r] == word then found = r end end
        if not found then
            ns.Say(L["Not a role for your class: %s."]:format(text))
            return
        end
        ns.db.roles[me] = found
    end
    local role = ns.MyRole()
    ns.Say(L["Upgrades are worked out for you as: %s."]:format(role and ROLE_WORDS[role] or "?"))
end, L["[melee|ranged|caster|healer|tank|feral|auto]: the role your upgrade % is worked out for"])
