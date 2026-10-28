"""python -m companion [--tray] [--console] [--once] [--setup] [--config PATH]

With no options it opens the window (and the tray icon). --console runs the older console version, which
needs nothing outside Python's standard library; --once and --setup imply it.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import config
from .app import Companion, setup_logging
from .client import TokenRefused

log = logging.getLogger("companion")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="companion", description="Noctis Loot companion app")
    parser.add_argument("--tray", action="store_true", help="start in the tray, without the window (Start with Windows)")
    parser.add_argument("--console", action="store_true", help="run in the console instead of a window")
    parser.add_argument("--once", action="store_true", help="do one pass (upload, fetch decisions) and exit")
    parser.add_argument("--setup", action="store_true", help="ask for the settings again, in the console")
    parser.add_argument("--config", type=Path, help=f"path to {config.CONFIG_NAME}")
    args = parser.parse_args(argv)

    path = config.config_path(args.config)
    settings = config.load(path)
    if args.console or args.once or args.setup:
        return console(args, path, settings)
    try:
        from . import ui
    except ImportError as exc:  # run from the code without pywebview and pystray installed
        print(f"No window ({exc}): running in the console. "
              "pip install -r requirements-companion.txt for the window.", file=sys.stderr)
        return console(args, path, settings)
    setup_logging(path.with_name("companion.log"))
    return ui.run(path, settings, start_hidden=args.tray)


def console(args: argparse.Namespace, path: Path, settings: config.Settings | None) -> int:
    if args.setup or settings is None or not settings.complete:
        if sys.stdin is None or not sys.stdin.isatty():
            print(f"Settings missing in {path}. Run the app in a console to set it up.", file=sys.stderr)
            return 2
        settings = config.prompt(settings, detected=config.detect_wow_dir())
        config.save(path, settings)
        print(f"Saved to {path}")

    setup_logging(path.with_name("companion.log"))
    if not settings.wow_dir.is_dir():
        log.error("Can't find the WoW folder %s. Fix wow_folder in %s or run with --setup.", settings.wow_dir, path)
        return 2
    if settings.bot_url.startswith("http://") and "127.0.0.1" not in settings.bot_url and "localhost" not in settings.bot_url:
        log.warning("The bot address isn't https: the token is sent unencrypted.")

    app = Companion(settings)
    try:
        if args.once:
            app.run_once()
        else:
            app.run_forever()
    except TokenRefused:
        log.error("The bot didn't accept the token. Get a new one with /loot token in Discord, "
                  "then run with --setup.")
        return 3
    except KeyboardInterrupt:
        log.info("Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
