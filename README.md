# Noctis Loot

The Noctis guild's loot system for WoW: Forever: loot rolls and a loot council in game, decisions and the loot log in Discord. Three programs, one repo, each packaged for the people who use it:

| | Folder | Who gets it | How |
|---|---|---|---|
| **Noctis Loot Council**, the addon (`/nlc`) | [`addon/`](addon/README.md) | everyone in the raid | CurseForge (a beta, once approved), or the zip on [Releases](../../releases) |
| **The companion app** | `companion/` | officers, on their Windows PCs | `NoctisLootCompanion.exe` from [Releases](../../releases), built by GitHub Actions |
| **The loot bot** | `bot/` | the server | `docker compose up -d --build` (below) |

- The **addon** runs the rolls and the council in game and keeps the list of raid drops; its README is the player's guide.
- The **loot bot**, always on, keeps the official item list, runs the officers' votes in Discord and posts the loot log. It also serves a small HTTP API.
- The **companion app**, a small window and a tray icon, uploads what the addon saw in the raid and writes the latest decisions where the game can load them.
- **Level milestones**, an officers' part of the addon (off until turned on), notes guild members' level-ups from the guild roster; the companion sends them and the bot congratulates them in Discord ([Level milestones](#level-milestones)). The same roster can keep a channel listing the guild's characters by class ([Guild roster channel](#guild-roster-channel)).

### How it hangs together

The game can't reach the internet, so data moves through files: the companion app carries it between the addon's files and the bot, and the bot keeps the official list and talks to Discord.

```mermaid
flowchart TB
  subgraph game["In the game · WoW: Forever"]
    direction LR
    raiders["<b>Raiders' addons</b><br/>Main spec / Off spec / Pass pop-up;<br/>tags and a note on council items"]
    lm["<b>Loot master's addon</b><br/>drop list · rolls · council window · loot log"]
    saved[("<b>Saved file</b><br/>drops, awards, interest, bid tags")]
    decided[("<b>NoctisLootDecisions</b><br/>council / roll list and priorities")]
  end
  subgraph pc["Officers' PCs"]
    companion["<b>Companion app</b><br/>watches the saved file, uploads what's new,<br/>writes the latest decisions"]
  end
  subgraph server["Server"]
    bot["<b>Loot bot</b> · always on<br/>the official item list, officers' votes,<br/>raiders' suggestions, every officer's<br/>uploads merged, the loot log"]
  end
  subgraph discord["Discord"]
    direction LR
    officers["<b>loot-officers</b> (private)<br/>votes, priority"]
    items["<b>loot-items</b> (public)<br/>status, suggestions"]
    log["<b>loot-log</b><br/>every award, with the reason"]
    prio["<b>loot-priorities</b><br/>council items, before each raid"]
  end
  oxm["<b>oxm.gg</b><br/>loot history and roster"]

  raiders -- "rolls in raid chat; bids and notes" --> lm
  lm -- "roll call, results, pop-up" --> raiders
  lm -- "/reload or logout" --> saved
  decided -- "loaded at login" --> lm
  saved -- reads --> companion
  companion -- writes --> decided
  companion -- "POST /api/upload" --> bot
  bot -- "GET /api/decisions" --> companion
  bot -- "items" --> officers
  bot -- "items" --> items
  officers -- "votes, priority" --> bot
  items -- "suggestions" --> bot
  bot -- "awards" --> log
  bot -- "priorities" --> prio
  lm -. "/nlc export, RCLootCouncil CSV" .-> oxm
```

Rolls work from raid chat alone: raiders without the addon type `/roll` or `/roll 99`, and the pop-up is a shortcut on top. Bid tags and notes need the addon and go only to the loot master and the council.

The exact file and API formats are in [`docs/sync-format.md`](docs/sync-format.md). A change to them changes the addon and the bot together, in one commit.

### The weekly flow

1. **Between raids, in Discord.** An officer posts a known item with `/loot add`. In the private **#loot-officers** channel officers vote **Council** or **Roll** and set a priority ("Warlock priority"); an option wins once it has 3 votes (and more than the other). To discuss an item, an officer starts a thread on its post (Discord's own Create Thread). In the public **#loot-items** channel raiders see every item's status and can press **Suggest for council**; officers see who suggested it, and it never changes anything by itself. Each post shows the item's icon and links to its Wowhead page (Forever's when Wowhead has it). Items seen on Wowhead or in other guilds' raids can go on the list before they drop for us (`/loot add` with a link, `/loot import`); raiders see those behind a spoiler.
2. **Before the raid.** An officer runs `/loot priorities`: the council items and their priorities go to **#loot-priorities**. The companion app has already written the latest decisions into the game's AddOns folder; the loot master types `/reload` and the addon says "Decisions from 27 Oct, 18:40: 34 council, 112 roll."
3. **In the raid.** The addon applies the decisions. Items nobody has decided are rolled.
4. **After the raid.** The loot master logs out or types `/reload`. The companion app uploads the night. The bot posts the awards to **#loot-log** (one post per raid and night) and every item that dropped for the first time to **#loot-officers** ("NEW IN OUR RAID LAST NIGHT", who won it, how many wanted it) and **#loot-items**, for a vote.

Decisions made in Discord always win. A decision set in game (`/nlc council ...`) is used only for items Discord hasn't decided, and is shown as "Set in game by *character*".

---

## Setting up the bot

### 1. Create the Discord application

1. Go to https://discord.com/developers/applications, **New Application**, name it "Noctis Loot".
2. **Bot** tab: **Reset Token** and copy the token (it goes in `.env` as `DISCORD_TOKEN`). No privileged intents are needed (Message Content only if you use `CHANNEL_IN_GAME_CHAT`, below).
3. **OAuth2 → URL Generator**: scopes **`bot`** and **`applications.commands`**; bot permissions **View Channels, Send Messages, Embed Links, Attach Files, Read Message History**. (Attach Files is for the drawn item titles on #loot-items and #loot-officers. Manage Messages isn't needed: the bot only edits its own posts.) Open the generated link and add the bot to the server. The same link by hand, with your application ID:
   `https://discord.com/oauth2/authorize?client_id=APPLICATION_ID&scope=bot+applications.commands&permissions=117760`

### 2. Channels and the officer role

- Create **#loot-officers** (private: officers only), **#loot-items**, **#loot-priorities** and **#loot-log**. Give the bot access to the private channel (channel settings → Permissions → add the bot's role with View Channel, Send Messages, Embed Links, Attach Files, Read Message History).
- Only members with the officer role can vote, set priorities and use the officer commands (server admins without the role can't vote).
- Suggested pinned post for #loot-items (post and pin it yourself), from the mockup:
  > The officers decide which items are council items. If you think a roll item matters enough to be councilled, press **Suggest for council**. It's counted for the officers' next look at the list and never changes anything during a raid.

### 3. Configure

Copy `.env.example` to `.env` and fill it in. Turn on Developer Mode in Discord (Settings → Advanced) to copy IDs with a right-click.

| Setting | |
|---|---|
| `DISCORD_TOKEN` | the bot token |
| `GUILD_ID` | your server's ID |
| `OFFICER_ROLE_ID` | the officers' role |
| `CHANNEL_LOOT_OFFICERS`, `CHANNEL_LOOT_ITEMS`, `CHANNEL_LOOT_PRIORITIES`, `CHANNEL_LOOT_LOG` | channel IDs |
| `CHANNEL_IN_GAME_CHAT` | optional: the channel the game's guild chat link posts in. The bot deletes that link's "Sent a message to guild chat but has not yet linked their Discord account." lines there, as they arrive and when it starts; nothing else in the channel is touched, and no text is kept. Needs **Message Content Intent** on (Bot tab; turn it on first, or the bot can't connect) and **Manage Messages** in that channel |
| `API_HOST`, `API_PORT` | where the API listens (default `127.0.0.1:8080`) |
| `VOTES_TO_DECIDE` | votes an option needs (default 3) |
| `DB_PATH` | the SQLite database (default `data/noctis-loot.db`) |
| `WCL_CLIENT_ID`, `WCL_CLIENT_SECRET` | optional, for `/loot wcl`: a client from warcraftlogs.com → API clients (any redirect URL, not a public client) |
| `TIMEZONE` | for raid nights and dates in posts (default `Europe/London`; a raid night runs until 06:00) |
| `RELEASE_CHECK` | `0` turns off the companion's update notice (the bot asks GitHub for the newest companion release about once an hour; default on) |

### 4. Run it

**Docker (recommended).** The server doesn't need git: `python tools/package.py bot` makes `dist/NoctisLootBot.zip`, a `NoctisLootBot` folder with just what Docker needs and a short README. Unpack it on the server, fill in `.env` there, then in that folder:

```sh
docker compose up -d --build
docker compose logs -f
```

To update, unpack a new zip over the folder (it never contains a `.env`, so yours stays) and run the same command. The database lives in the `noctis-loot_loot-data` volume, which `docker compose down` keeps (`down -v` would delete it). The API is published on the host's `127.0.0.1:8080` only, for the reverse proxy or tunnel. Anything for one server only, such as another host port, goes in a `docker-compose.override.yml` next to the compose file; git ignores it, like `.env`.

On Windows with Docker Desktop, Docker only runs while a user is signed in: turn on "Start Docker Desktop when you sign in" and make sure that account signs in after a reboot.

**systemd instead.** See the instructions at the top of [`deploy/noctis-loot-bot.service`](deploy/noctis-loot-bot.service): a venv in `/opt/noctis-loot-bot`, a `noctis` system user, `API_HOST=127.0.0.1`.

**By hand** (Python 3.11): `pip install -r requirements.txt`, then `python -m bot`.

Slash commands are registered on your server at start-up, so they appear straight away.

### 5. Put the API behind your reverse proxy

The companion apps reach the bot over the internet, so put the API behind the existing reverse proxy with HTTPS (the token is a password). Only `/api/` needs forwarding; uploads can reach a few MB late in a season.

Caddy:

```
loot.example.org {
    reverse_proxy /api/* 127.0.0.1:8080
}
```

nginx (inside the `server` block that already has your certificate):

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    client_max_body_size 32m;
}
```

Check it from outside: `https://loot.example.org/api/health` should answer `{"ok": true}`. The companion app's "bot address" is then `https://loot.example.org`.

**No reverse proxy yet, and 443 reaches the host** (even if 80 is taken or blocked): run the stock `caddy` image next to the bot in a `docker-compose.override.yml`, publishing 443, with the Caddyfile below minus the `dns` and `propagation_*` lines and with `issuer acme { disable_http_challenge }` in the `tls` block. Let's Encrypt then checks the host on 443 itself (the TLS-ALPN challenge), and the bot address is `https://loot.example.org`.

**Your ISP blocks incoming 80 and 443** (some home connections do): run Caddy next to the bot in a `docker-compose.override.yml`, on another port, and get the certificate by Let's Encrypt's DNS challenge, which needs no incoming connection. If your DNS host has no API Caddy supports, delegate just the challenge to Duck DNS: build Caddy with `xcaddy build --with github.com/caddy-dns/duckdns`, add a CNAME from `_acme-challenge.loot.example.org` to a free `something.duckdns.org`, forward the router's port 8443 to the host's 443, and use:

```
loot.example.org {
	tls {
		dns duckdns {$DUCKDNS_TOKEN} {
			override_domain {$DUCKDNS_DOMAIN}
		}
		propagation_delay 30s
		propagation_timeout -1
	}
	handle /api/* {
		reverse_proxy bot:8080
	}
	handle {
		respond 404
	}
}
```

The bot address is then `https://loot.example.org:8443`. Keep the Duck DNS token in an env file next to the override, out of git like `.env`.

### Backups

Everything is in the one SQLite file. A consistent copy while the bot runs: `sqlite3 data/noctis-loot.db ".backup backup.db"` (Docker: `docker compose exec bot python -c "import sqlite3; sqlite3.connect('/data/noctis-loot.db').backup(sqlite3.connect('/data/backup.db'))"`).

---

## Using it in Discord

| | Who | |
|---|---|---|
| `/loot add <item> [name] [slot] [source] [quality] [found]` | officers | Puts an item on the list and posts it to #loot-officers and #loot-items. `item` is a Wowhead link, an in-game link or the item ID; the name, slot and quality come from Wowhead's Forever data (Classic's when Forever's doesn't have it), or type the name if Wowhead doesn't know the item. Slot ("Waist · Cloth") and source ("Molten Core, Gehennas") are optional text. `found` says where an item that hasn't dropped for us was seen (Wowhead, another guild's raid). Using it again on the same item updates the details. |
| `/loot import [text] [file] [found]` | officers | Puts items found outside our raids on the list, so they can be decided before they drop for us. Paste Wowhead links, in-game links or IDs in `text`, or attach another guild's RCLootCouncil or oxm.gg CSV export in `file` (their item IDs, raids and bosses are used; who won is not). Just for you, it first shows what it would add, with **Import** and **Cancel**. Items already on the list are left alone, except that one without a source gets the CSV's. |
| **Council** / **Roll** buttons | officers | One vote each, press the other button to change it. Decided once an option has `VOTES_TO_DECIDE` votes and more than the other. |
| **Set priority** button | officers | A short text such as "Warlock priority", shown in #loot-items, #loot-priorities and in game. Empty clears it. |
| **Suggest for council** button | everyone | On roll and undecided items in #loot-items. Press again to take it back. |
| `/loot priorities [raid] [day]` | officers | Posts the council items and priorities to #loot-priorities, then the paragraph about everything else being rolled. `day` is the heading ("Thursday 30 Oct"; default today). |
| `/loot status [item]` | everyone | Just for you: what's decided, or one item. |
| `/loot token` | officers | Just for you: a token for the companion app. Running it again replaces the old one. |
| `/milestones settings [guild] [channel] [levels] [announce]` | officers | Just for you: shows or changes the [level milestones](#level-milestones). |
| `/roster settings [channel] [min_level] [hide_ranks] [alt_ranks] [show]` | officers | Just for you: shows or changes the [guild roster channel](#guild-roster-channel). |
| `/loot wcl <link>` | officers | Links a Warcraft Logs report to its night's #loot-log post: "Warcraft Logs" under the heading, and each boss heading to that boss's kill (the last one before its loot went out). The post that takes it is the one on the report's night whose loot falls in the report's time; a report linked before the upload is used once the loot comes. Linking another report that holds that night's loot replaces it. The report must be public or unlisted. Needs `WCL_CLIENT_ID` and `WCL_CLIENT_SECRET`. |

The posts are edited in place as votes, priorities, suggestions and uploads change things; restarting the bot never reposts. If a post is deleted, the bot posts it again on the next change.

An item that hasn't dropped for us yet is behind a spoiler on #loot-items and #loot-priorities (its name, picture and details; tap to see them), for raiders who'd rather not see loot before it drops. Its status, priority and Suggest button stay visible. The officers' post shows it plainly, with where it was found. The spoiler goes once it drops in our raid.

### Level milestones

The bot congratulates guild members in a channel of your choice when they reach level 10, 20, 30, 40, 50 and 60: "Vespera Ashward reached level 40", in their class colour, with their class and rank. Reaching the top level also says how many in the guild got there before them.

It takes three things: officers who want to help turn it on in the addon, the companion app (which sends what the addon noticed), and one officer setting it up in Discord:

```
/nlc milestones on                                                      (in game, each officer)
/milestones settings guild:Noctis channel:#milestones announce:True     (in Discord, once)
```

- **In game** it's off for everyone until `/nlc milestones on` (it then counts for every character on that WoW account), and even then it only works on characters whose guild rank is an officer's (the game's own permission: officer chat or officer notes). On anyone else's character it doesn't read the roster, save it or say anything. While it's on, the addon reads the guild roster every minute, so it sees anyone's level, not only yours. `/nlc milestones off` stops it.

- **guild** is the in-game guild's name. An officer's characters in other guilds are kept apart by the addon, and the companion sends only this guild's roster, so forgetting to switch the addon off on an alt does no harm.
- **levels** changes which levels are congratulated, e.g. `levels:10, 20, 30, 40, 50, 60`.
- **announce:False** stops it; while it's off, uploads are ignored. Turning it on announces only what's noticed from then on.
- Give the bot View Channel and Send Messages in the channel.

Things to know:

- The game writes the addon's file when you log out or `/reload`, so congratulations arrive then, not the moment someone levels. Each post says when the level-up was noticed.
- A level is seen only while an officer with the addon is online. Someone who went from 18 to 31 in between gets one post, for 30.
- Each milestone is posted once, whichever officer noticed it first, and never after a higher one. Level-ups noticed more than 7 days before they reach the bot aren't posted.
- The first time the addon reads a guild it notes everyone's level and posts nothing.

In game, the addon can also tell you, off until you turn it on (`/nlc milestones` alone shows where things stand):

- `/nlc milestones tell on`: a line in your own chat window when someone reaches a milestone. Nothing is sent; only you see it. Level-ups found at login after time away say so ("caught up: last seen at level 18").
- `/nlc milestones sound on`: a sound when someone reaches a milestone, your cue to `/reload`, since the companion can only send it to Discord after the game saves. Turning it on plays it once so you know what to listen for. It uses your sound effects volume.
- `/nlc milestones levels 10, 20, 30` changes the levels told about in game (`/nlc milestones levels default` puts back 10 to 60). The bot's levels are set in Discord.

### Guild roster channel

The bot can keep one post in a channel listing the guild's characters, laid out like a Raid-Helper sign-up: a gold embed titled "Noctis · Guild roster", a row of counters (members, how many at the top level, when the roster was last read), the count per rank, then a column per class, three side by side in alphabetical order, each headed with the class's icon, name and count and listing its characters by level (`60` **Thorgar Ironvale**). It's edited in place as people level, join or leave. A class too long for its column carries on just below it; only a guild too big for one Discord message (25 columns or 6000 characters) gets a second post under the first. The roster comes with the level milestones upload, so milestones must be on with a guild (above), and only companions from 0.2.4 send what it needs.

```
/roster settings channel:#roster hide_ranks:Trial show:True     (in Discord, once)
```

- **channel** is any channel you pick; the bot sets no permissions there, so it's for officers unless the channel is open to others. Give the bot View Channel and Send Messages. Changing it moves the posts: the old ones are deleted.
- **min_level** lists characters at that level and above (default 10). **hide_ranks** leaves out these ranks, e.g. `Trial` (`none` shows every rank).
- **alt_ranks** lists these ranks apart, e.g. `Alt, Officer Alt`: the roster becomes "Mains", with an "Alts" post under it (`none` puts everyone back in one roster).
- **show:False** stops updating; the posts stay as they are.
- Someone has left once a later roster read by any officer doesn't have them. When the roster grows into a second post or shrinks back to one, or a post was deleted, the bot deletes its roster posts and posts them again.
- The class icons are Wowhead's, uploaded once as the bot's own emojis (`class_warrior`, ...); until they're there (or while Wowhead isn't answering) the columns are headed without them, and the post is edited when they arrive.
---

## For officers: the companion app

A small window, and an owl in the tray by the clock. It checks the addon's saved file every 30 seconds, uploads it when it changes, and keeps the decisions addon up to date. Closing the window keeps it running in the tray; **Quit** is in the tray icon's menu.

**Install:** download `NoctisLootCompanion.exe` from the [latest release](../../releases/latest), put it in a folder of its own (its settings and log go beside it) and run it. It needs Windows 10 or 11: the window is Windows' own WebView2. The `.exe` isn't code-signed, so Windows may say it "protected your PC": **More info**, then **Run anyway**. [Checking the .exe](#checking-the-exe) shows how to make sure it's the one built from this code.

The first run asks for three things, then **Connect** checks them with the bot before saving:

1. **The WoW: Forever folder.** It suggests one it found, usually `C:\Program Files (x86)\World of Warcraft\_forever_`; **Browse…** picks another.
2. **The bot address**, e.g. `https://loot.example.org`. Your guild's release fills it in; otherwise ask whoever runs the bot.
3. **Your token**: type `/loot token` in Discord and paste it.

**Start with Windows**, on unless you untick it, starts it in the tray when you sign in.

The window then shows whether it's connected to the bot, the last upload, which decisions the game has, the folder it watches and what it's done lately. **Upload now** sends the saved file again straight away, and the gear opens the settings. The tray icon pops up a notification when it uploads something new, when it writes new decisions, and when it needs a new token.

**Version and updates:** the window's header and the tray icon's tooltip show the version (the `.exe`'s Properties → Details too). When a newer one is released, the window shows "Companion 0.2.3 is out" with a link to its page on GitHub to copy, and the tray tells you once. It downloads nothing and opens nothing: you download the new `.exe` and put it in place of the old one (quit first, from the tray), and your settings stay. **Not now** hides the notice until the next version. The companion doesn't ask GitHub itself: the bot does, and adds the version number to the decisions it sends anyway, so there's no extra check; the link is built into the app, so it always points at this project's releases. If `/loot token` is used again for your Discord account, the old token stops working: the window turns red and asks for the new one. Uploads wait until then; nothing is lost.

It keeps its settings and token in `companion.ini`, and its log in `companion.log`, next to the app (or in `%APPDATA%\NoctisLoot\` if that folder isn't writable). Starting it again while it runs brings up the window of the copy that's running.

**From the code:** install Python 3.11 from python.org, download this project, and in its folder run `python -m pip install -r requirements-companion.txt`, then `python -m companion`. Without those packages, or with `--console`, it runs in the console instead and asks its questions there; `--setup` asks them again, and `--once` does one pass and exits.

What it does each pass:

- For every `WTF\Account\*\SavedVariables\NoctisLootCouncil.lua` that changed since it last uploaded: reads it and sends it to the bot. (The game writes it at `/reload` and logout.)
- If you turned milestones on in game: from each of those files, sends your guild's roster and level-ups (only while the bot has milestones on), for the milestones and the guild roster channel.
- Fetches the decisions, and if they changed, writes `Interface\AddOns\NoctisLootDecisions\` (two `.toc` files and `Decisions.lua`). The game loads it at the next `/reload` or login. It shows in the AddOns list as "Noctis Loot Decisions", beside the main addon with its icon; leave it enabled.

### What it reads, writes and sends

All of it is in a few short files: `companion/savedfile.py` (what it takes from the saved file), `companion/client.py` (the only part that talks to the network), and `companion/ui.py` with `companion/page.html` (the window). A test, `tests/companion/test_what_it_touches.py`, fails if:

- any part but `client.py` imports networking;
- any part but `ui.py` uses code from outside Python's standard library (the window uses pywebview, pystray and Pillow, at the versions pinned in `requirements-companion.txt`);
- it starts other programs or runs code it's given;
- the window's page could load anything from the internet.

It **reads**:

- `WTF\Account\*\SavedVariables\NoctisLootCouncil.lua`, the addon's saved file, for each account on the PC. Its milestones part is there only if you typed `/nlc milestones on`; without it, or while it's off, the companion does nothing about milestones and doesn't even ask the bot about them.
- Nothing else in the game folder.
- At setup only: whether WoW is in the usual folders, and where Battle.net installed it (from the registry), to suggest the `_forever_` folder.

It **writes**:

- `Interface\AddOns\NoctisLootDecisions\` (two `.toc` files and `Decisions.lua`). Nothing else in the game folder.
- `companion.ini` (your settings and token) and `companion.log`, next to the app or in `%APPDATA%\NoctisLoot\`, with `companion.lock` and `companion.show` beside them, which keep it to one copy.
- With **Start with Windows** on: one value, `Noctis Loot companion`, under `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`, which starts it in the tray at sign-in. Turning it off removes the value.

It **talks to** the bot address in `companion.ini`, and nowhere else:

- `POST /api/upload`, with what the saved file holds about raid loot: the items (name, link, quality, where and when they dropped, the decision and note), the drops it saw and the awards (who won what, their class, how, the roll, the note and bid tags) and those taken back with `/nlc undo`, and the name of the character that uploaded. The account folder's name stays on your PC.
- `GET /api/decisions`: the council and roll decisions, and the newest companion version (for the update notice).
- With milestones on in game only: `GET /api/milestones` (whether the bot is taking level-ups, and for which guild; asked at most every 10 minutes), then, while it is, `POST /api/milestones` with that guild's roster as your addon saw it (each member's name, class, level, rank and when your addon last saw them in the roster, and when it last read the roster, so the bot can tell who has left), the level-ups it noticed (who, from which level to which, when) and the name of the character that uploaded. The rosters of any other guild your characters are in stay on your PC.

All of these carry your token. It tells the bot the upload is yours, and does nothing else: the bot accepts it for these requests only, and it gives no access to your Discord or Battle.net account. `/loot token` replaces it.

The window loads nothing: its page, pictures and font are inside the app, shown by WebView2 in private mode (no cookies or history kept), and the page's Content-Security-Policy refuses to load anything from anywhere. There's no auto-update and no analytics. A new version is a new download, when you choose: the update notice only tells you one is out. To see the connections for yourself, Resource Monitor's Network tab (or Sysinternals TCPView) shows it connecting to the bot alone.

### Checking the .exe

The released `.exe` isn't built on anyone's PC. GitHub Actions builds it from the commit a release's tag points at, after the companion's tests pass (`.github/workflows/companion-release.yml`), and publishes it on the Releases page. Two checks:

- **Your download is the released file.** In PowerShell, in the folder you saved it to, `Get-FileHash NoctisLootCompanion.exe` should print the SHA-256 shown on the release (also in its `SHA256SUMS.txt`).
- **The released file was built from this code.** GitHub signs a build provenance for each `.exe`, naming the repository, the commit and the workflow. With the [GitHub CLI](https://cli.github.com), `gh attestation verify NoctisLootCompanion.exe -R <owner>/<repository>` (as in this repository's address) prints them, and fails if the file was changed after GitHub built it. The release notes give the exact command.

The one thing in the `.exe` that isn't in the code is the bot address it fills in at setup, if the repository's `COMPANION_BOT_URL` setting has one. Setup shows it, and you can change it.

**Building it yourself:** `python -m pip install -r requirements-dev.txt`, then `python tools/package.py companion` builds `dist\NoctisLootCompanion.exe`. To fill in your bot's address for your officers (they can still change it), first create `companion\_guild.py` with one line, `BOT_URL = "https://loot.example.org"`; git ignores that file.

---

## Trying it without Discord

```
python -m bot --new-token "Test"     # prints a token
python -m bot --api-only             # just the API on 127.0.0.1:8080
python -m companion                  # bot address http://127.0.0.1:8080, the token above
```

## Development

```
python -m pip install -r requirements-dev.txt
python -m pytest                          # the bot, the companion and the harness (below)
cd addon && luajit tests/run.lua          # the addon, against a fake WoW: Forever client
python tools/package.py all               # dist/: the addon zip, NoctisLootCompanion.exe, NoctisLootBot.zip
python addon/tools/install_dev.py "<WoW>\_forever_"   # a dev copy of the addon in game
```

**Releasing the addon:** bump `## Version` in both `.toc` files, put a `## Noctis Loot Council <version>` section at the top of `addon/CHANGELOG.md`, commit and push, then `python tools/release_addon.py --upload`. It runs the addon's tests, builds the zip (only the `.toc` and `.lua` files, the LICENSE and the icon: CurseForge rejects scripts), uploads it to CurseForge for WoW Forever as a beta, then tags `addon-v<version>` and makes a GitHub release with the same zip and that changelog section. It needs the CurseForge API token in `CURSE_API_KEY` and refuses unless everything is committed and pushed. `--versions` lists CurseForge's Forever game versions, for when the live client gets its own.

**Releasing the companion:** set `__version__` in `companion/__init__.py`, commit and push, then `git tag companion-v<version>` and `git push origin companion-v<version>`. The workflow refuses a tag that doesn't match the version. Set the repository variable `COMPANION_BOT_URL` (Settings, Secrets and variables, Actions, Variables) to prefill your bot's address.

The rules (vote tally, upload merge and de-duplication, post wording) are plain modules with no Discord import (`bot/rules.py`, `bot/upload.py`, `bot/store.py`, `bot/render.py`) and are tested directly; the API is tested with aiohttp's test client against a temporary database; the poster against fake channels; the companion end to end against the real API, and what its window shows and does without a window (`tests/companion/test_controller.py`).

### The test harness

`python -m pytest` also runs the three programs together, with Discord and the game faked (`harness/`, `tests/harness/`):

- **A fake Discord** (`harness/fake_discord.py`): a local server that speaks enough of Discord's REST API and gateway for the real bot to connect to it unchanged. Tests type slash commands, press buttons and fill in forms as officers and raiders, then read what the bot posted.
- **A raid realm** (`harness/realm/`): several players, each running the real addon in its own LuaJIT process on the fake WoW: Forever client from the addon's tests. The realm passes addon messages between them, rolls their `/roll`s and keeps their clocks together. Each player has their own PC folder, so the real companion app reads their saved files and writes their decisions just as it would on an officer's PC.
- **Scenarios**: a whole week (officers decide in Discord, the companion brings it into the game, a raid night with council votes and rolls, two officers upload, the bot posts the night and the new items, next week's game knows), plus checks of each part. With `dist/NoctisLootCompanion.exe` built, one scenario runs the built app.
- **Forever's API**: `harness/forever_api.json` lists the functions and events the Forever client has (from [forever-addon-kit](https://github.com/Thunderz96/forever-addon-kit) and [forever-addon-dev](https://github.com/imperial64/forever-addon-dev), MIT). A test fails if the fake client offers, or the addon uses, one the game doesn't have. Regenerate it with `python tools/forever_api.py <forever-addon-kit> <forever-addon-dev>`.

The realm needs LuaJIT on the PATH (or in `LUAJIT`); without it those tests are skipped. The fakes are only as right as our guesses about Discord and the game: the harness proves the parts agree with each other, not that Forever behaves as the fake client does.

## Not done yet

- Nothing has run in the real game yet: WoW: Forever hasn't launched. The bot runs on the guild's Discord, and the companion app talks to it; the addon has run only against the fake game client, in the tests and the harness.
- No way to remove an item from the list or revoke a token other than issuing a new one (`/loot token` replaces the old one; deleting a row from the `tokens` table revokes it).
- Only the winner's bid tags (BIS, Sidegrade...) reach the bot, with the award; the other bidders' tags stay in game. "NEW IN OUR RAID" posts show how many wanted an item, not what they tagged.
- The CSV export for oxm.gg from the bot isn't built; the addon's `/nlc export` makes it for now.
- Milestones are levels only. The roster also shows rank changes and the guild's event log shows who joined, so promotions (a trial passed) and welcomes could follow; they're held back while the guild fills up.
- The addon isn't on CurseForge yet: the project is being set up, and the first file goes up as a beta.
