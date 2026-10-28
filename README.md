# Noctis Loot

The Noctis guild's loot system for WoW: Forever: loot rolls and a loot council in game, decisions and the loot log in Discord. Three programs, one repo, each packaged for the people who use it:

| | Folder | Who gets it | How |
|---|---|---|---|
| **Noctis Loot Council**, the addon (`/nlc`) | [`addon/`](addon/README.md) | everyone in the raid | CurseForge zip: `python tools/package.py addon` |
| **The companion app** | `companion/` | officers, on their Windows PCs | `NoctisLootCompanion.exe`: `python tools/package.py companion` |
| **The loot bot** | `bot/` | the server | `docker compose up -d --build` (below) |

- The **addon** runs the rolls and the council in game and keeps the list of raid drops; its README is the player's guide.
- The **loot bot**, always on, keeps the official item list, runs the officers' votes in Discord and posts the loot log. It also serves a small HTTP API.
- The **companion app** uploads what the addon saw in the raid and writes the latest decisions where the game can load them.

The game can't reach the internet, so data moves through files:

```
addon ──saved file──▶ companion app ──POST /api/upload──▶ bot ──▶ Discord
addon ◀─NoctisLootDecisions addon── companion app ◀──GET /api/decisions── bot
```

The exact formats are in [`docs/sync-format.md`](docs/sync-format.md). A change to them changes the addon and the bot together, in one commit.

### The weekly flow

1. **Between raids, in Discord.** An officer posts a known item with `/loot add`. In the private **#loot-officers** channel officers vote **Council** or **Roll** and set a priority ("Warlock priority"); an option wins once it has 3 votes (and more than the other). To discuss an item, an officer starts a thread on its post (Discord's own Create Thread). In the public **#loot-items** channel raiders see every item's status and can press **Suggest for council**; officers see who suggested it, and it never changes anything by itself. Each post shows the item's icon and links to its Wowhead page (Forever's when Wowhead has it).
2. **Before the raid.** An officer runs `/loot priorities`: the council items and their priorities go to **#loot-priorities**. The companion app has already written the latest decisions into the game's AddOns folder; the loot master types `/reload` and the addon says "Decisions from 27 Oct, 18:40: 34 council, 112 roll."
3. **In the raid.** The addon applies the decisions. Items nobody has decided are rolled.
4. **After the raid.** The loot master logs out or types `/reload`. The companion app uploads the night. The bot posts the awards to **#loot-log** (one post per raid and night) and every item that dropped for the first time to **#loot-officers** ("NEW IN OUR RAID LAST NIGHT", who won it, how many wanted it) and **#loot-items**, for a vote.

Decisions made in Discord always win. A decision set in game (`/nlc council ...`) is used only for items Discord hasn't decided, and is shown as "Set in game by <character>".

---

## Setting up the bot

### 1. Create the Discord application

1. Go to https://discord.com/developers/applications, **New Application**, name it "Noctis Loot".
2. **Bot** tab: **Reset Token** and copy the token (it goes in `.env` as `DISCORD_TOKEN`). No privileged intents are needed.
3. **OAuth2 → URL Generator**: scopes **`bot`** and **`applications.commands`**; bot permissions **View Channels, Send Messages, Embed Links, Read Message History**. (Manage Messages isn't needed: the bot only edits its own posts.) Open the generated link and add the bot to the server. The same link by hand, with your application ID:
   `https://discord.com/oauth2/authorize?client_id=APPLICATION_ID&scope=bot+applications.commands&permissions=84992`

### 2. Channels and the officer role

- Create **#loot-officers** (private: officers only), **#loot-items**, **#loot-priorities** and **#loot-log**. Give the bot access to the private channel (channel settings → Permissions → add the bot's role with View Channel, Send Messages, Embed Links, Read Message History).
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
| `API_HOST`, `API_PORT` | where the API listens (default `127.0.0.1:8080`) |
| `VOTES_TO_DECIDE` | votes an option needs (default 3) |
| `DB_PATH` | the SQLite database (default `data/noctis-loot.db`) |
| `WCL_CLIENT_ID`, `WCL_CLIENT_SECRET` | optional, for `/loot wcl`: a client from warcraftlogs.com → API clients (any redirect URL, not a public client) |
| `TIMEZONE` | for raid nights and dates in posts (default `Europe/London`; a raid night runs until 06:00) |

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
| `/loot add <item_id> <name> [slot] [source]` | officers | Puts an item on the list and posts it to #loot-officers and #loot-items. Discord can't look items up, so the name is typed in; slot ("Waist · Cloth") and source ("Molten Core, Gehennas") are optional text. Using it again on the same ID updates the details. |
| **Council** / **Roll** buttons | officers | One vote each, press the other button to change it. Decided once an option has `VOTES_TO_DECIDE` votes and more than the other. |
| **Set priority** button | officers | A short text such as "Warlock priority", shown in #loot-items, #loot-priorities and in game. Empty clears it. |
| **Suggest for council** button | everyone | On roll and undecided items in #loot-items. Press again to take it back. |
| `/loot priorities [raid] [day]` | officers | Posts the council items and priorities to #loot-priorities, then the paragraph about everything else being rolled. `day` is the heading ("Thursday 30 Oct"; default today). |
| `/loot status [item]` | everyone | Just for you: what's decided, or one item. |
| `/loot token` | officers | Just for you: a token for the companion app. Running it again replaces the old one. |
| `/loot wcl <link>` | officers | Links a Warcraft Logs report to its night's #loot-log post: "Warcraft Logs" under the heading, and each boss heading to that boss's kill (the last one before its loot went out). The post that takes it is the one on the report's night whose loot falls in the report's time; a report linked before the upload is used once the loot comes. Linking another report that holds that night's loot replaces it. The report must be public or unlisted. Needs `WCL_CLIENT_ID` and `WCL_CLIENT_SECRET`. |

The posts are edited in place as votes, priorities, suggestions and uploads change things; restarting the bot never reposts. If a post is deleted, the bot posts it again on the next change.

---

## For officers: the companion app

It runs in a console window while you play (or all the time), checks the saved file every 30 seconds, uploads it when it changes, and keeps the decisions addon up to date.

**Install** (until there's an .exe): install Python 3.11 from python.org, download this project, and in its folder run

```
python -m companion
```

The first run asks for:

1. **The WoW: Forever folder.** It suggests one it found, usually `C:\Program Files (x86)\World of Warcraft\_forever_`.
2. **The bot address**, e.g. `https://loot.example.org` (ask whoever runs the bot). Your guild's .exe may already fill it in: press Enter to keep it.
3. **Your token**: type `/loot token` in Discord and paste it.

It saves them in `companion.ini` next to the app (or in `%APPDATA%\NoctisLoot\` if that folder isn't writable) and logs to `companion.log` beside it. `python -m companion --setup` asks again; `--once` does one pass and exits.

What it does each pass:

- For every `WTF\Account\*\SavedVariables\NoctisLootCouncil.lua` that changed since it last uploaded: reads it and sends it to the bot. (The game writes it at `/reload` and logout.)
- Fetches the decisions, and if they changed, writes `Interface\AddOns\NoctisLootDecisions\` (two `.toc` files and `Decisions.lua`). The game loads it at the next `/reload` or login. It shows in the AddOns list as "Noctis Loot Decisions"; leave it enabled.

**Single .exe:** `python -m pip install -r requirements-dev.txt`, then `python tools/package.py companion` builds `dist\NoctisLootCompanion.exe`. To fill in your bot's address for your officers (they can still change it), first create `companion\_guild.py` with one line, `BOT_URL = "https://loot.example.org"`; git ignores that file.

---

## Trying it without Discord

```
python -m bot --new-token "Test"     # prints a token
python -m bot --api-only             # just the API on 127.0.0.1:8080
python -m companion --setup          # bot address http://127.0.0.1:8080, the token above
```

## Development

```
python -m pip install -r requirements-dev.txt
python -m pytest                          # the bot, the companion and the harness (below)
cd addon && luajit tests/run.lua          # the addon, against a fake WoW: Forever client
python tools/package.py all               # dist/: the addon zip, NoctisLootCompanion.exe, NoctisLootBot.zip
python addon/tools/install_dev.py "<WoW>\_forever_"   # a dev copy of the addon in game
```

The rules (vote tally, upload merge and de-duplication, post wording) are plain modules with no Discord import (`bot/rules.py`, `bot/upload.py`, `bot/store.py`, `bot/render.py`) and are tested directly; the API is tested with aiohttp's test client against a temporary database; the poster against fake channels; the companion end to end against the real API.

### The test harness

`python -m pytest` also runs the three programs together, with Discord and the game faked (`harness/`, `tests/harness/`):

- **A fake Discord** (`harness/fake_discord.py`): a local server that speaks enough of Discord's REST API and gateway for the real bot to connect to it unchanged. Tests type slash commands, press buttons and fill in forms as officers and raiders, then read what the bot posted.
- **A raid realm** (`harness/realm/`): several players, each running the real addon in its own LuaJIT process on the fake WoW: Forever client from the addon's tests. The realm passes addon messages between them, rolls their `/roll`s and keeps their clocks together. Each player has their own PC folder, so the real companion app reads their saved files and writes their decisions just as it would on an officer's PC.
- **Scenarios**: a whole week (officers decide in Discord, the companion brings it into the game, a raid night with council votes and rolls, two officers upload, the bot posts the night and the new items, next week's game knows), plus checks of each part. With `dist/NoctisLootCompanion.exe` built, one scenario runs the built app.
- **Forever's API**: `harness/forever_api.json` lists the functions and events the Forever client has (from [forever-addon-kit](https://github.com/Thunderz96/forever-addon-kit) and [forever-addon-dev](https://github.com/imperial64/forever-addon-dev), MIT). A test fails if the fake client offers, or the addon uses, one the game doesn't have. Regenerate it with `python tools/forever_api.py <forever-addon-kit> <forever-addon-dev>`.

The realm needs LuaJIT on the PATH (or in `LUAJIT`); without it those tests are skipped. The fakes are only as right as our guesses about Discord and the game: the harness proves the parts agree with each other, not that Forever behaves as the fake client does.

## Not done yet

- Nothing has run against Discord or the real game: no bot token yet. The three programs run together in the test harness, against a fake Discord and the fake game client.
- No way to remove an item from the list or revoke a token other than issuing a new one (`/loot token` replaces the old one; deleting a row from the `tokens` table revokes it).
- Only the winner's bid tags (BIS, Sidegrade...) reach the bot, with the award; the other bidders' tags stay in game. "NEW IN OUR RAID" posts show how many wanted an item, not what they tagged.
- The CSV export for oxm.gg from the bot (the system map's "later") isn't built.
- No release yet: the addon zip and the companion .exe build (`python tools/package.py`) but haven't been published.
