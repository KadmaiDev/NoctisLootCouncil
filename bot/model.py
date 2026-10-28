"""Read-only snapshots of the bot's state, handed from the store to the renderers."""
from __future__ import annotations

from dataclasses import dataclass, field

from .rules import Tally


@dataclass(frozen=True)
class AwardInfo:
    item_id: int
    item_name: str
    who: str
    how: str
    at: int
    roll: int | None = None
    note: str | None = None
    inst: str | None = None
    boss: str | None = None
    nms: int | None = None
    nos: int | None = None
    tags: str | None = None
    new_item: bool = False  # the item's first night in our raids
    emoji: str | None = None  # the item's icon as the bot's emoji
    url: str | None = None  # the item's Wowhead page


@dataclass(frozen=True)
class ItemState:
    id: int
    name: str
    quality: int | None = None
    slot: str | None = None
    source_text: str | None = None
    raid: str | None = None
    tally: Tally = field(default_factory=Tally)
    decision: str | None = None        # from the officers' votes
    game_handling: str | None = None   # from an upload, only used without a Discord decision
    game_note: str | None = None
    game_by: str | None = None
    priority: str | None = None
    priority_by: str | None = None
    suggestions: int = 0
    suggested_by: tuple[str, ...] = ()  # raiders' names, oldest first (older suggestions have none)
    drops: int = 0
    first_drop_at: int | None = None
    last_drop_at: int | None = None
    new_in_raid: bool = False
    created_at: int = 0
    first_award: AwardInfo | None = None
    icon: str | None = None            # Wowhead's icon name, e.g. inv_staff_13
    emoji: str | None = None           # that icon as the bot's emoji
    icon_image: bool = False           # the icon's picture is stored, for the drawn title
    wowhead: tuple[str, str] | None = None  # (database, name) when Wowhead has the item: link to it

    @property
    def handling(self) -> str | None:
        """The decision in force: Discord's always wins over one set in game (sync-format.md, section 2)."""
        return self.decision or self.game_handling

    @property
    def decided_in_game(self) -> bool:
        return self.decision is None and self.game_handling is not None

    @property
    def note(self) -> str | None:
        """The priority text sent to the addon."""
        if self.priority:
            return self.priority
        return self.game_note if self.decided_in_game else None


@dataclass(frozen=True)
class LogGroup:
    inst: str  # raid name ('' when the addon didn't know it)
    night: str  # ISO date
    awards: list[AwardInfo]


@dataclass(frozen=True)
class Post:
    kind: str
    key: str
    channel_id: int
    message_id: int
    thread_id: int | None
    digest: str


@dataclass(frozen=True)
class UploadResult:
    new_items: int
    new_awards: int
    skipped: int = 0
