"""python -m bot            run the bot (Discord + the HTTP API)
python -m bot --api-only run only the HTTP API, e.g. to try the companion app before Discord is set up
python -m bot --new-token "Name"   print an API token without Discord (for --api-only testing)
"""
from __future__ import annotations

import argparse
import logging
from zoneinfo import ZoneInfo

from . import config


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m bot", description="Noctis loot bot")
    parser.add_argument("--api-only", action="store_true", help="run only the HTTP API (no Discord)")
    parser.add_argument("--new-token", metavar="NAME", help="issue an API token for NAME and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config.load(require_discord=not (args.api_only or args.new_token))

    from .db import connect
    from .store import Store

    if args.new_token or args.api_only:
        store = Store(connect(cfg.db_path), ZoneInfo(cfg.timezone), cfg.votes_to_decide)
        if args.new_token:
            print(store.issue_token(f"cli:{args.new_token}", args.new_token))
            return
        from aiohttp import web
        from .api import create_app
        web.run_app(create_app(store), host=cfg.api_host, port=cfg.api_port, access_log=None)
        return

    from .client import LootBot
    LootBot(cfg).run(cfg.token, log_handler=None)


if __name__ == "__main__":
    main()
