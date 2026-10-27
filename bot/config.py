import os
import pathlib
from dataclasses import dataclass

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    token: str
    guild_id: int
    officer_role_id: int
    ch_officers: int
    ch_items: int
    ch_priorities: int
    ch_log: int
    api_host: str
    api_port: int
    votes_to_decide: int
    db_path: pathlib.Path
    timezone: str


def _int(name: str, default: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    if not raw.isdigit():
        raise SystemExit(f"{name} in .env must be a number (got {raw!r}).")
    return int(raw)


def load(require_discord: bool = True) -> Config:
    """Read .env. With require_discord=False (API-only mode, token commands) the Discord settings may be blank."""
    load_dotenv(ROOT / ".env")
    cfg = Config(
        token=os.getenv("DISCORD_TOKEN", "").strip(),
        guild_id=_int("GUILD_ID"),
        officer_role_id=_int("OFFICER_ROLE_ID"),
        ch_officers=_int("CHANNEL_LOOT_OFFICERS"),
        ch_items=_int("CHANNEL_LOOT_ITEMS"),
        ch_priorities=_int("CHANNEL_LOOT_PRIORITIES"),
        ch_log=_int("CHANNEL_LOOT_LOG"),
        api_host=os.getenv("API_HOST", "127.0.0.1").strip() or "127.0.0.1",
        api_port=_int("API_PORT", 8080),
        votes_to_decide=max(1, _int("VOTES_TO_DECIDE", 3)),
        db_path=ROOT / os.getenv("DB_PATH", "data/noctis-loot.db").strip(),
        timezone=os.getenv("TIMEZONE", "Europe/London").strip() or "Europe/London",
    )
    if require_discord:
        missing = [name for name, value in (
            ("DISCORD_TOKEN", cfg.token), ("GUILD_ID", cfg.guild_id), ("OFFICER_ROLE_ID", cfg.officer_role_id),
            ("CHANNEL_LOOT_OFFICERS", cfg.ch_officers), ("CHANNEL_LOOT_ITEMS", cfg.ch_items),
            ("CHANNEL_LOOT_PRIORITIES", cfg.ch_priorities), ("CHANNEL_LOOT_LOG", cfg.ch_log)) if not value]
        if missing:
            raise SystemExit(f"Set {', '.join(missing)} in .env (copy .env.example to .env).")
    return cfg
