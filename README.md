# Noctis Loot Council

Loot rolls and loot council for the Noctis guild on **World of Warcraft: Forever**. Type `/nlc`.

Work in progress. What it does so far:

## The list of raid drops

Forever hides its raid loot from data miners at launch, so nobody knows the drops in advance. Noctis Loot Council keeps a list of every drop seen in a raid (rare quality and up), with the boss it came from and how many times it has dropped, and fills it in as you raid.

- **When an item drops for the first time**, whoever opens the loot window is told, so the raid can decide on the spot whether it's a council or roll item.
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

## Still to come

The rolls (main spec, second main spec, off spec), the council vote, the loot log, sharing the list between officers, and windows for all of it.
