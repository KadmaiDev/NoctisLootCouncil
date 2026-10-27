# Noctis Loot Council

Loot rolls and loot council for the Noctis guild on **World of Warcraft: Forever**. Type `/nlc`.

Work in progress. What it does so far:

## The list of raid drops

Forever hides its raid loot from data miners at launch, so nobody knows the drops in advance. Noctis Loot Council keeps a list of every drop seen in a raid (rare quality and up), with the boss it came from and how many times it has dropped, and fills it in as you raid.

- **When an item drops for the first time**, whoever opens the loot window is told. New items are rolled; once the guild knows how big an upgrade it is, `/nlc council` makes it a council item from its next drop.
- **When it drops again**, they're told what was decided last time, with any note ("Priest priority").
- Drops are seen in the loot window, in "receives loot" chat lines and in group loot roll windows, so raiders without the loot window still fill in the list. A drop seen several ways counts once.
- The boss is learned from the first corpse or chest opened after a kill, so later kills are recognised from the corpse alone.

| Command | |
|---|---|
| `/nlc loot [text]` | list every raid drop seen, by boss (or only those whose name contains the text) |
| `/nlc council <item> [note]` | make it a council item |
| `/nlc roll <item> [note]` | make it a roll item |
| `/nlc undecided <item>` | neither |
| `/nlc note <item> [text]` | a note shown when it drops |
| `/nlc forget <item>` | remove it from the list |
| `/nlc quality [0-5]` | lowest quality recorded (3 = rare, the default; 4 = epic) |
| `/nlc dungeons on\|off` | record dungeon drops too, for trying it out |

`<item>` can be a shift-clicked item link, an item ID, or the item's name.

**Items can be decided before they drop for us.** Most loot will be known from other guilds' kills and the community's lists first, so `/nlc council`, `/nlc roll` and `/nlc note` also take a link or item ID of an item not in the list yet. It's added as "not seen in our raids yet", and when it first drops, the loot master is told the decision.

## Rolls

The loot master starts a roll with `/nlc start <item>`. The raid is told in raid chat: `/roll` for main spec, `/roll 99` for off spec, 30 seconds. Raiders don't need the addon. When time is up, the winner is announced and logged.

Who wins, by the guild's rules:

1. **Main spec** beats **second main spec** (a main-spec win already tonight), which beats **off spec**.
2. Within those, **members beat trials**: a trial wins only if no member rolled the same kind of roll. Socials count as members.
3. Then the **highest roll**. A tie for first is rolled again by those tied.

Only each player's first roll counts. Main-spec wins count as "tonight's" for 12 hours, or until `/nlc newnight`.

| Command | |
|---|---|
| `/nlc start <item>` | start a roll |
| `/nlc stop` | end it now and announce the winner |
| `/nlc cancel` | call it off |
| `/nlc wins` | tonight's main-spec wins |
| `/nlc newnight` | start a new raid night |
| `/nlc undo` | remove the last award |
| `/nlc trials [rank, rank]` | the guild ranks that are trials (default: any rank with "trial" in its name) |

## Still to come

A roll pop-up for raiders with the addon, the council vote, the loot log export, sharing the list between officers, and windows for all of it.
