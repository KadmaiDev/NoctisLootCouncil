# Noctis Loot Council

Loot rolls and loot council for the Noctis guild on **World of Warcraft: Forever**. Type `/nlc`.

Work in progress: 0.1.0 is a beta that hasn't been used in a real raid yet ([changelog](CHANGELOG.md)). Install it from CurseForge, or unzip `NoctisLootCouncil-<version>.zip` from the repository's Releases into `<WoW>\_forever_\Interface\AddOns` (the folder must be named `NoctisLootCouncil`). What it does so far:

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

The loot master starts a roll with `/nlc start <item>` (or a button in the loot window). The raid is told in raid chat: `/roll` for main spec, `/roll 99` for off spec, 30 seconds, with a reminder 10 seconds before the end. Raiders don't need the addon; those who have it get a pop-up whose **Main spec** and **Off spec** buttons roll for them. When time is up, the winner is announced and logged.

Who wins, by the guild's rules:

1. **Main spec** beats **second main spec** (a main-spec win already tonight), which beats **off spec**.
2. Within those, **members beat trials**: a trial wins only if no member rolled the same kind of roll. Socials count as members.
3. Then the **highest roll**. A tie for first is rolled again by those tied.

Only each player's first roll counts. Main-spec wins count as "tonight's" for 12 hours, or until `/nlc newnight`.

| Command | |
|---|---|
| `/nlc start <item> [roll\|council]` | start its roll, or the council for a council item |
| `/nlc stop` | end it now (or close the council's bids, or count its votes) |
| `/nlc cancel` | call it off |
| `/nlc wins` | tonight's main-spec wins |
| `/nlc newnight` | start a new raid night |
| `/nlc undo` | remove the last award (from Discord's #loot-log too, after the next upload) |
| `/nlc trials [rank, rank]` | the guild ranks that are trials (default: any rank with "trial" in its name) |
| `/nlc popup on\|off` | the Main spec / Off spec / Pass pop-up |

## The council

Council items go to the loot council instead of a roll.

1. **Bids, 30 seconds.** The pop-up asks Main spec / Off spec / Pass, with optional tags (BIS, Big upgrade, Sidegrade, Situational) and a short note. The bid goes to the loot master and the council only, with your **upgrade %** (the item's stats for your role against what you wear, as a share of all your gear) and what you wear in that slot. Raiders without the addon bid by rolling.
2. **The council votes**, up to 5 minutes, one vote each, ticking at least one reason from the rules: class fit, biggest upgrade, less loot so far, reliability, effort. A council member who bid on the item sits it out.
3. **The most votes wins**, and the loot log says why: the votes and the reasons at least half of the winner's voters gave ("council vote, 3 of 4: biggest upgrade, less loot so far"), with the winner's bid tags and note. A split vote goes to a roll-off between the tied. One main-spec bid wins without a vote; only off-spec bids roll off; no bids, and the loot master disenchants or banks it. The loot master can also award it with a reason.

The council window shows each candidate's gear, upgrade, earlier loot, tags, note and votes.

| Command | |
|---|---|
| `/nlc councillors First Last, First Last` | who votes (on the loot master's addon) |
| `/nlc award First Last, reason` | award the council item to a candidate |
| `/nlc councilwindow` | open the council window again |
| `/nlc role [melee\|ranged\|caster\|healer\|tank\|feral\|auto]` | the role your upgrade % is worked out for |

The upgrade % only counts plain stats: trinkets with use or proc effects, set bonuses and resistance gear score low, so the council goes by tags and notes for those.

## Windows, export and Discord

- **`/nlc show`** opens the loot master's window: tonight's drops with their decision and a button to start each, the running roll with everyone's standing, the item list and the loot log. It opens by itself when the loot master loots a boss (`/nlc autoopen off` stops that).
- **`/nlc export [all]`** puts tonight's awards (or all of them) in a box to copy, in RCLootCouncil's CSV format, for oxm.gg's RCLootCouncil import.
- **Decisions from Discord**: officers vote council or roll in Discord; the Noctis Loot companion app writes them into a small `NoctisLootDecisions` addon that this one reads at login, and uploads the saved loot log back.
- **`/nlc scale [50-300]`** sets the size of the windows. They take EllesmereUI's or ElvUI's look if you use one, and work with the Gamepad UI.
