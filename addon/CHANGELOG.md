# Changelog

## Noctis Loot Council 0.1.1

- **Council votes come with a reason.** Each council member ticks why they vote, from the guild's rules: class fit, biggest upgrade, less loot so far, reliability, effort (at least one). The loot log says why the winner got it: "council vote, 3 of 4: biggest upgrade, less loot so far", with their bid tags and note.
- **A council item that goes to an off-spec roll-off** is logged with the winning roll, like any other roll ("off-spec roll, 90").
- **`/nlc undo` reaches Discord**: an award taken back after it was uploaded leaves the #loot-log post at the next upload, instead of staying there next to the correction.
- **Bids and votes stay private.** They never go raid-wide: if the game won't whisper them, a bid becomes a roll (without its tags and note) and a council member is told their vote didn't arrive.
- **Only the loot master runs the council.** Pop-ups, council sessions and their next steps only count from the raid's leader, an assistant or the master looter, and from the loot master they name; a vote without a reason doesn't count.
- **The council window pages** through more than eight candidates, so every one can be voted for.
- **No roll starts while a council item is open** (its rolls would be taken as bids), and a council roll-off that's called off, or a tie nobody re-rolls, goes back to the vote for the loot master to decide.
- **Long roll-off and tie announcements** go over several lines of raid chat instead of not at all.
- **A council item decided in Discord before it ever dropped** is counted at its first drop, even when it's only seen in chat.
- Fixed: candidates' names in the council window are in their class colour, and the pop-up shows a council item's name once the game has loaded it.

## Noctis Loot Council 0.1.0

The first release, a beta: it hasn't been used in a real raid yet. Type `/nlc` for the commands.

- **A list of every raid drop seen**, with its boss and how often it has dropped, filled in by everyone in the raid who has the addon. The loot master is told when an item drops for the first time, and what was decided last time when it drops again.
- **Council or roll, decided per item**, in game (`/nlc council`, `/nlc roll`) or by the officers in Discord. An item can be decided before it has ever dropped for the guild.
- **Rolls**: main spec beats second main spec beats off spec, members beat trials, then the highest roll. Raiders without the addon just `/roll`; those with it get Main spec and Off spec buttons.
- **The council**: private bids with tags, a note and an upgrade %, votes from the council in their own window, and a roll-off for a split vote.
- **The loot master's window** (`/nlc show`): tonight's drops, the running roll, the item list and the loot log.
- **Export** for oxm.gg (`/nlc export`), in RCLootCouncil's CSV format.
- Window size with `/nlc scale`, EllesmereUI's and ElvUI's look, and the Gamepad UI.
