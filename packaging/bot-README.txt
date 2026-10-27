Noctis Loot bot
===============

The Discord bot and the API the officers' companion apps talk to, in one Docker container.
The full guide (Discord application, channels, reverse proxy) is the README in the repository.

First time, in this folder:
  1. Copy .env.example to .env and fill it in. .env holds the bot token: keep it private.
  2. docker compose up -d --build

Check it:
  docker logs -f noctis-loot-bot
  The API answers on http://127.0.0.1:8080/api/health on this machine only; forward /api/ to it
  from your reverse proxy or tunnel, with HTTPS.

Update after a new NoctisLootBot.zip: unpack it over this folder (your .env stays), then
  docker compose up -d --build

Stop:
  docker compose down
  The database is in the noctis-loot_loot-data volume and survives this. Never add -v unless
  you mean to delete it.

Back up the database while it runs:
  docker compose exec bot python -c "import sqlite3; sqlite3.connect('/data/noctis-loot.db').backup(sqlite3.connect('/data/backup.db'))"
  docker cp noctis-loot-bot:/data/backup.db .

Another host port, or anything else for this machine only: put it in docker-compose.override.yml
next to docker-compose.yml.

Windows with Docker Desktop: Docker Desktop only runs while a user is signed in. Turn on "Start
Docker Desktop when you sign in" in its settings and make sure that account signs in after a
reboot, or the bot won't come back until someone logs on.
