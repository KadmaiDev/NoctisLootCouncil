# Sync format: addon ⇄ companion app ⇄ bot

The game can't reach the internet. Data leaves it through the addon's saved file (written at
`/reload` or logout) and comes back through a small addon the companion app writes, which
the game loads at login. The bot is the source of truth for decisions; the addon is the
source of truth for what happened in the raid.

```
addon ──saved file──▶ companion app ──POST /api/upload──▶ bot ──▶ Discord
addon ◀─NoctisLootDecisions addon── companion app ◀──GET /api/decisions── bot
```

## 1. The addon's saved file (read by the companion app)

`<WoW>\_forever_\WTF\Account\<account>\SavedVariables\NoctisLootCouncil.lua`, a Lua
assignment `NoctisLootCouncilDB = { ... }` written by the client: keys are `["string"]` or
`[number]`, values are strings (Lua-escaped: `\"`, `\\`, `\n`), numbers, booleans and nested
tables, one field per line, each followed by a comma, sometimes with `-- [n]` comments after
list entries. The client keeps the previous file as `NoctisLootCouncil.lua.bak` (ignore it).
Several accounts may each have one; read every `WTF\Account\*\SavedVariables\NoctisLootCouncil.lua`.

Fields the companion uses (others may exist; ignore them):

| Field | Shape | Meaning |
|---|---|---|
| `v` | number | format version, 1 |
| `me` | string | the character who last logged in with it ("First Last") |
| `items` | `{ [itemID] = item }` | every item in the list |
| item `link` | string | the game's item link (`|cffa335ee|Hitem:18000::...|h[Name]|h|r`), or `item:18000` if the game never loaded it |
| item `q` | number | quality (3 rare, 4 epic, 5 legendary) |
| item `first`, `last` | number | unix time first / last seen (or added) |
| item `seen` | number | copies seen dropping in our raids (0 = added before it dropped) |
| item `from` | `{ [source] = count }` | where it dropped: `e<encounterID>` a boss, `n<npcID>` trash, `o<objectID>` a chest |
| item `inst` | number | instance ID it dropped in |
| item `handling` | `"council"` / `"roll"` / nil | the decision as the addon has it |
| item `note` | string / nil | e.g. "Warlock priority" |
| item `slot` | string / nil | equip slot as the game names it: `INVTYPE_HEAD`, `INVTYPE_WAIST`, `INVTYPE_WEAPON`, ... (nil if the game knew nothing of it, or it isn't worn) |
| item `sub` | string / nil | armour or weapon type: "Cloth", "Plate", "Swords", ... |
| `decisionsAt` | number / nil | the `at` of the newest decisions the addon has applied (section 4) |
| `encounters` | `{ [encounterID] = { name, inst } }` | bosses |
| `instances` | `{ [instanceID] = name }` | raids |
| `drops` | list of `{ id, at, src, inst, n }` | each sighting that added to `seen`: item ID, unix time, source (as in `from`, may be missing), instance, copies |
| `log` | list of awards, oldest first | see below |

An award (`log` entry):

| Field | Shape | Meaning |
|---|---|---|
| `id` | number | item ID |
| `link` | string | item link |
| `who` | string | winner, "First Last" |
| `class` | string / nil | winner's class file name: `WARRIOR`, `MAGE`, ... |
| `at` | number | unix time |
| `how` | string | `ms` main spec roll, `ms2` second main spec, `os` off spec, `council` council award |
| `roll` | number / nil | the winning roll |
| `note` | string / nil | the council's reason, or the winner's bid tags and note |
| `tags` | string / nil | council awards: the winner's bid tags, e.g. "BIS, Big upgrade" |
| `inst` | string / nil | raid name, e.g. "Molten Core" |
| `boss` | string / nil | boss name, if the award followed a kill |
| `nms`, `nos` | number / nil | how many wanted it main spec / off spec |

## 2. Upload: companion → bot

`POST /api/upload`, header `Authorization: Bearer <token>` (a per-officer token the bot hands
out with `/loot token`), JSON body:

```json
{
  "uploader": "Kadmai Moonwhisper",
  "decisions_at": 1793078967,
  "items": { "18000": { "link": "...", "name": "Sash of the Unseen", "q": 4, "first": 1793000000,
             "last": 1793070000, "seen": 1, "from": { "e663": 1 }, "inst": 409,
             "handling": "council", "note": "Warlock priority", "slot": "INVTYPE_WAIST", "sub": "Cloth" } },
  "encounters": { "663": { "name": "Lucifron", "inst": 409 } },
  "instances": { "409": "Molten Core" },
  "drops": [ { "id": 18000, "at": 1793070000, "src": "e663", "inst": 409, "n": 1 } ],
  "awards": [ { "id": 18000, "link": "...", "who": "Ilsa Marrow", "class": "WARLOCK", "at": 1793070100,
                "how": "council", "note": "Warlock priority; biggest upgrade", "inst": "Molten Core",
                "boss": "Lucifron", "nms": 4, "nos": 1, "tags": "BIS" } ]
}
```

`name` is taken from the link's `[...]`. Keys of JSON objects are strings. The companion sends
the whole file each time; the bot de-duplicates:

- **Awards:** one per (`who` lower-cased, `id`, `at`).
- **Drops:** several officers may upload the same raid, and their clocks and the moment each
  saw the drop differ by seconds to minutes. Two drops are the same drop when they have the
  same `id` and `src` (missing counts as "") and their `at` are within 15 minutes; the bot
  keeps the largest `n` any upload reported. An item's drop count in our raids is the sum
  over its distinct drops. (A fixed half-hour bucket would count a drop seen at 20:29 by one
  officer and 20:31 by another twice.)
- **Items:** name, link, quality, sources and first/last are merged (union of sources, min
  first, max last). An item the bot has never seen with `seen > 0` is **new in our raids**:
  the bot posts it for a vote (and shows how many wanted it, from the awards).
- **In-game decisions:** `handling`/`note` from an upload are used only for items the bot
  has no decision for (the bot shows them as "set in game by <uploader>"). Discord decisions
  always win. After a decision is taken back in Discord, the uploader's game still has the old
  one until it applies decisions that say `"none"`, so the bot ignores an item's uploaded
  handling while `decisions_at` is older than the time it was taken back.

Answer: `200 {"ok": true, "new_items": n, "new_awards": n}`; `401` bad token; `400` bad body.

## 3. Decisions: bot → companion

`GET /api/decisions`, same header. Answer:

```json
{ "at": 1793078967,
  "items": { "18000": { "handling": "council", "note": "Warlock priority", "name": "Sash of the Unseen" } } }
```

`at` is the time of the newest decision change. Every item with a decision is listed;
`handling` is `"council"`, `"roll"`, or `"none"` for an item whose decision was taken back in
Discord (so the game forgets it too). Items never decided are not listed, so a decision made
in game and not yet uploaded survives. `note` is the priority text, may be missing.

## 4. The decisions addon: companion → game

The companion writes its own addon folder, so updating the main addon never deletes it:

`<WoW>\_forever_\Interface\AddOns\NoctisLootDecisions\NoctisLootDecisions.toc` and
`NoctisLootDecisions_Camelot.toc` (identical):

```
## Interface: 16001
## Title: Noctis Loot Decisions
## Notes: Council and roll decisions from Discord, written by the Noctis Loot companion app. Don't edit; it's rewritten.
## Version: 1793078967
Decisions.lua
```

`Decisions.lua`:

```lua
-- Written by the Noctis Loot companion app. Don't edit; it's rewritten.
NoctisLootDecisions = {
  at = 1793078967,
  items = {
    [18000] = { h = "council", note = "Warlock priority", name = "Sash of the Unseen" },
    [16866] = { h = "roll" },
    [17109] = { h = "none" },
  },
}
```

Strings are written as Lua strings with `\\`, `\"`, `\n` escaped and anything outside printable
ASCII kept as UTF-8 bytes. Write to a temporary file and rename over the old one, so the game
never loads half a file. The new decisions reach the game at the next `/reload` or login.

The addon applies them at login when `at` is newer than the last decisions it applied
(`db.decisionsAt`): each listed item gets that handling and note (items not in its list are
added as not seen yet); `"none"` clears an item's handling and note and adds nothing. Items
decided only in game keep their decision. It then says
"Decisions from 27 Oct, 18:40: 34 council, 112 roll."
