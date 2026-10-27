"""All reads and writes of the bot's database. No Discord here: the API and the cogs both call this."""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from typing import Callable
from zoneinfo import ZoneInfo

from . import rules
from .model import AwardInfo, ItemState, LogGroup, Post, UploadResult
from .rules import COUNCIL, HANDLINGS, Vote
from .upload import Upload, UploadItem, name_from_link

TOKEN_PREFIX = "nlc_"


def _hash_token(token: str) -> str:
    # Tokens are long and random, so a plain SHA-256 is enough: there's nothing to brute-force.
    return hashlib.sha256(token.strip().encode()).hexdigest()


class Store:
    def __init__(self, conn: sqlite3.Connection, tz: ZoneInfo, votes_to_decide: int = 3,
                 clock: Callable[[], float] = time.time):
        self.conn = conn
        self.tz = tz
        self.votes_to_decide = votes_to_decide
        self._clock = clock

    def now(self) -> int:
        return int(self._clock())

    # ---- meta ------------------------------------------------------------

    def _meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def _set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    # ---- items -------------------------------------------------------------

    def _mark_dirty(self, item_id: int) -> None:
        self.conn.execute("UPDATE items SET dirty = dirty + 1 WHERE id = ?", (item_id,))

    def item_exists(self, item_id: int) -> bool:
        return self.conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone() is not None

    def add_item(self, item_id: int, name: str, *, slot: str | None = None, source: str | None = None,
                 by: str | None = None) -> bool:
        """/loot add. Returns True if the item is new; an existing item gets the given details updated."""
        name = name.strip()
        with self.conn:
            if self.item_exists(item_id):
                self.conn.execute(
                    "UPDATE items SET name = ?, slot = COALESCE(?, slot), source = COALESCE(?, source) WHERE id = ?",
                    (name, slot or None, source or None, item_id))
                self._mark_dirty(item_id)
                self._refresh_decisions_at()
                return False
            self.conn.execute(
                "INSERT INTO items(id, name, slot, source, added_by, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (item_id, name, slot or None, source or None, by, self.now()))
            return True

    def find_items(self, text: str, limit: int = 25) -> list[tuple[int, str]]:
        text = text.strip()
        if text.isdigit():
            rows = self.conn.execute("SELECT id, name FROM items WHERE CAST(id AS TEXT) LIKE ? ORDER BY id LIMIT ?",
                                     (text + "%", limit))
        else:
            rows = self.conn.execute("SELECT id, name FROM items WHERE name LIKE ? ORDER BY name LIMIT ?",
                                     (f"%{text}%", limit))
        return [(r["id"], r["name"]) for r in rows]

    def _votes(self, item_id: int) -> list[Vote]:
        rows = self.conn.execute("SELECT user_id, user_name, choice, at FROM votes WHERE item_id = ?", (item_id,))
        return [Vote(r["user_id"], r["user_name"], r["choice"], r["at"]) for r in rows]

    def _instance_name(self, inst: int | None) -> str | None:
        if inst is None:
            return None
        row = self.conn.execute("SELECT name FROM instances WHERE id = ?", (inst,)).fetchone()
        return row["name"] if row else None

    def _source_text(self, row: sqlite3.Row) -> str | None:
        """'Molten Core, Lucifron': typed in with /loot add, or built from where it dropped."""
        if row["source"]:
            return row["source"]
        parts: list[str] = []
        inst = self._instance_name(row["inst"])
        if inst:
            parts.append(inst)
        srcs = self.conn.execute("SELECT src, count FROM item_sources WHERE item_id = ? ORDER BY count DESC, src",
                                 (row["id"],)).fetchall()
        for s in srcs:
            src = s["src"]
            label = None
            if src.startswith("e") and src[1:].isdigit():
                enc = self.conn.execute("SELECT name FROM encounters WHERE id = ?", (int(src[1:]),)).fetchone()
                label = enc["name"] if enc else None
            elif src.startswith("n"):
                label = "trash"
            elif src.startswith("o"):
                label = "a chest"
            if label and label not in parts:
                parts.append(label)
        return ", ".join(parts) or None

    def _raid_name(self, row: sqlite3.Row) -> str | None:
        """The raid an item belongs to, for grouping #loot-priorities."""
        inst = self._instance_name(row["inst"])
        if inst:
            return inst
        if row["source"]:
            return row["source"].split(",")[0].strip() or None
        return None

    def _award_info(self, r: sqlite3.Row, item_name: str, new_item: bool = False) -> AwardInfo:
        return AwardInfo(item_id=r["item_id"], item_name=item_name, who=r["who"], how=r["how"], at=r["at"],
                         roll=r["roll"], note=r["note"], inst=r["inst"], boss=r["boss"], nms=r["nms"],
                         nos=r["nos"], new_item=new_item)

    def item_state(self, item_id: int) -> ItemState | None:
        row = self.conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            return None
        drops = self.conn.execute("SELECT COALESCE(SUM(n), 0) AS n, MIN(at) AS first, MAX(at) AS last "
                                  "FROM drops WHERE item_id = ?", (item_id,)).fetchone()
        aw = self.conn.execute("SELECT MIN(at) AS first, MAX(at) AS last FROM awards WHERE item_id = ?",
                               (item_id,)).fetchone()
        first_award = self.conn.execute("SELECT * FROM awards WHERE item_id = ? ORDER BY at LIMIT 1",
                                        (item_id,)).fetchone()
        firsts = [t for t in (drops["first"], aw["first"]) if t is not None]
        lasts = [t for t in (drops["last"], aw["last"]) if t is not None]
        suggestions = self.conn.execute("SELECT COUNT(*) AS n FROM suggestions WHERE item_id = ?",
                                        (item_id,)).fetchone()["n"]
        return ItemState(
            id=row["id"], name=row["name"], quality=row["quality"], slot=row["slot"],
            source_text=self._source_text(row), raid=self._raid_name(row),
            tally=rules.tally(self._votes(item_id), self.votes_to_decide),
            decision=row["decision"], game_handling=row["game_handling"], game_note=row["game_note"],
            game_by=row["game_by"], priority=row["priority"], priority_by=row["priority_by"],
            suggestions=suggestions, drops=max(drops["n"], row["seen"]),
            first_drop_at=min(firsts) if firsts else None, last_drop_at=max(lasts) if lasts else None,
            new_in_raid=bool(row["new_in_raid"]), created_at=row["created_at"],
            first_award=self._award_info(first_award, row["name"]) if first_award else None,
        )

    def all_item_ids(self) -> list[int]:
        return [r["id"] for r in self.conn.execute("SELECT id FROM items ORDER BY id")]

    # ---- votes, suggestions, priority -------------------------------------

    def cast_vote(self, item_id: int, user_id: int, user_name: str, choice: str) -> rules.Tally:
        """One vote per officer, changeable. Re-tallies and records the decision if it changed."""
        if choice not in HANDLINGS:
            raise ValueError(choice)
        with self.conn:
            self.conn.execute(
                "INSERT INTO votes(item_id, user_id, user_name, choice, at) VALUES(?, ?, ?, ?, ?) "
                "ON CONFLICT(item_id, user_id) DO UPDATE SET user_name = excluded.user_name, "
                "choice = excluded.choice, at = CASE WHEN votes.choice = excluded.choice THEN votes.at ELSE excluded.at END",
                (item_id, user_id, user_name, choice, self.now()))
            result = rules.tally(self._votes(item_id), self.votes_to_decide)
            current = self.conn.execute("SELECT decision FROM items WHERE id = ?", (item_id,)).fetchone()["decision"]
            if result.decided != current:
                self.conn.execute("UPDATE items SET decision = ?, decided_at = ? WHERE id = ?",
                                  (result.decided, self.now() if result.decided else None, item_id))
            self._mark_dirty(item_id)
            self._refresh_decisions_at()
        return result

    def toggle_suggestion(self, item_id: int, user_id: int) -> tuple[bool, int]:
        """Suggest for council, or take the suggestion back. Returns (suggesting now, total)."""
        with self.conn:
            cur = self.conn.execute("DELETE FROM suggestions WHERE item_id = ? AND user_id = ?", (item_id, user_id))
            on = cur.rowcount == 0
            if on:
                self.conn.execute("INSERT INTO suggestions(item_id, user_id, at) VALUES(?, ?, ?)",
                                  (item_id, user_id, self.now()))
            self._mark_dirty(item_id)
        n = self.conn.execute("SELECT COUNT(*) AS n FROM suggestions WHERE item_id = ?", (item_id,)).fetchone()["n"]
        return on, n

    def set_priority(self, item_id: int, text: str | None, by: str) -> None:
        text = (text or "").strip() or None
        with self.conn:
            self.conn.execute("UPDATE items SET priority = ?, priority_by = ? WHERE id = ?",
                              (text, by if text else None, item_id))
            self._mark_dirty(item_id)
            self._refresh_decisions_at()

    # ---- decisions (GET /api/decisions) -----------------------------------

    def _decision_items(self) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for row in self.conn.execute("SELECT id, name, decision, priority, game_handling, game_note FROM items "
                                     "WHERE decision IS NOT NULL OR game_handling IS NOT NULL ORDER BY id"):
            handling = row["decision"] or row["game_handling"]
            note = row["priority"] or (row["game_note"] if row["decision"] is None else None)
            entry = {"handling": handling, "name": row["name"]}
            if note:
                entry["note"] = note
            out[str(row["id"])] = entry
        return out

    def _refresh_decisions_at(self) -> None:
        """Move `at` forward whenever the decisions list changes (and only then).

        Comparing a digest of the whole list catches every way it can change (a vote, a priority,
        a rename, an in-game decision) without each caller having to know. `at` always moves
        forward by at least a second, so two changes in one second still look like a change.
        """
        digest = hashlib.sha256(json.dumps(self._decision_items(), sort_keys=True).encode()).hexdigest()
        if digest == self._meta("decisions_digest"):
            return
        prev = int(self._meta("decisions_at", "0") or 0)
        self._set_meta("decisions_digest", digest)
        self._set_meta("decisions_at", str(max(self.now(), prev + 1)))

    def decisions(self) -> dict:
        return {"at": int(self._meta("decisions_at", "0") or 0), "items": self._decision_items()}

    # ---- uploads -----------------------------------------------------------

    def _merge_item(self, it: UploadItem, uploader: str) -> bool:
        """Merge one uploaded item; returns True if the bot had never seen it."""
        row = self.conn.execute("SELECT * FROM items WHERE id = ?", (it.id,)).fetchone()
        created = row is None
        if created:
            self.conn.execute(
                "INSERT INTO items(id, name, link, quality, inst, first_at, last_at, seen, created_at, new_in_raid) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (it.id, it.name or f"Item {it.id}", it.link, it.quality, it.inst, it.first, it.last, it.seen,
                 self.now(), 1 if it.seen > 0 else 0))
            row = self.conn.execute("SELECT * FROM items WHERE id = ?", (it.id,)).fetchone()
        else:
            firsts = [t for t in (row["first_at"], it.first) if t is not None]
            lasts = [t for t in (row["last_at"], it.last) if t is not None]
            self.conn.execute(
                "UPDATE items SET name = ?, link = ?, quality = COALESCE(?, quality), inst = COALESCE(inst, ?), "
                "first_at = ?, last_at = ?, seen = MAX(seen, ?) WHERE id = ?",
                (it.name or row["name"], rules.better_link(row["link"], it.link), it.quality, it.inst,
                 min(firsts) if firsts else None, max(lasts) if lasts else None, it.seen, it.id))
        old = {r["src"]: r["count"] for r in
               self.conn.execute("SELECT src, count FROM item_sources WHERE item_id = ?", (it.id,))}
        for src, n in rules.merge_sources(old, it.sources).items():
            self.conn.execute("INSERT INTO item_sources(item_id, src, count) VALUES(?, ?, ?) "
                              "ON CONFLICT(item_id, src) DO UPDATE SET count = excluded.count", (it.id, src, n))
        # An in-game decision counts only while Discord has none. Recording it only then also keeps
        # the addon's echo of a Discord decision (written back by the companion) from being taken
        # for a decision made in game.
        if row["decision"] is None and it.handling is not None and (
                it.handling != row["game_handling"] or it.note != row["game_note"]):
            self.conn.execute("UPDATE items SET game_handling = ?, game_note = ?, game_by = ? WHERE id = ?",
                              (it.handling, it.note, uploader, it.id))
        self._mark_dirty(it.id)
        return created

    def apply_upload(self, up: Upload, owner: str, owner_name: str) -> UploadResult:
        uploader = up.uploader or owner_name
        new_items = new_awards = 0
        with self.conn:
            for iid, name in up.instances.items():
                self.conn.execute("INSERT INTO instances(id, name) VALUES(?, ?) "
                                  "ON CONFLICT(id) DO UPDATE SET name = excluded.name", (iid, name))
            for eid, (name, inst) in up.encounters.items():
                self.conn.execute("INSERT INTO encounters(id, name, inst) VALUES(?, ?, ?) "
                                  "ON CONFLICT(id) DO UPDATE SET name = excluded.name, inst = COALESCE(excluded.inst, inst)",
                                  (eid, name, inst))
            listed = {it.id for it in up.items}
            for it in up.items:
                new_items += self._merge_item(it, uploader)
            # An award for an item missing from the list still means it dropped for us.
            for aw in up.awards:
                if aw.id not in listed and not self.item_exists(aw.id):
                    new_items += self._merge_item(UploadItem(id=aw.id, name=name_from_link(aw.link), link=aw.link,
                                                             seen=1, first=aw.at, last=aw.at), uploader)
                    listed.add(aw.id)
            for d in up.drops:
                item_id, src, bucket = rules.drop_key(d.id, d.src, d.at)
                cur = self.conn.execute(
                    "INSERT INTO drops(item_id, src, bucket, at, inst, n) VALUES(?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(item_id, src, bucket) DO UPDATE SET n = MAX(n, excluded.n) WHERE excluded.n > n",
                    (item_id, src, bucket, d.at, d.inst, d.n))
                if cur.rowcount and self.item_exists(item_id):
                    self._mark_dirty(item_id)
            for aw in up.awards:
                who_key, item_id, at = rules.award_key(aw.who, aw.id, aw.at)
                night = rules.night_of(at, self.tz).isoformat()
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO awards(who_key, item_id, at, who, class, how, roll, note, inst, boss, "
                    "nms, nos, link, night, uploader, received_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (who_key, item_id, at, aw.who, aw.cls, aw.how, aw.roll, aw.note, aw.inst, aw.boss, aw.nms,
                     aw.nos, aw.link, night, uploader, self.now()))
                if cur.rowcount:
                    new_awards += 1
                    self.conn.execute("INSERT INTO log_groups(inst, night) VALUES(?, ?) "
                                      "ON CONFLICT(inst, night) DO UPDATE SET dirty = dirty + 1", (aw.inst or "", night))
                    self._mark_dirty(item_id)
            self.conn.execute("INSERT INTO uploads(at, owner, uploader, new_items, new_awards) VALUES(?, ?, ?, ?, ?)",
                              (self.now(), owner, uploader, new_items, new_awards))
            self._refresh_decisions_at()
        return UploadResult(new_items=new_items, new_awards=new_awards, skipped=up.skipped)

    # ---- #loot-log ---------------------------------------------------------

    def _first_night(self, item_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT MIN(at) AS t FROM (SELECT at FROM drops WHERE item_id = ? UNION ALL "
            "SELECT at FROM awards WHERE item_id = ?)", (item_id, item_id)).fetchone()
        return rules.night_of(row["t"], self.tz).isoformat() if row["t"] is not None else None

    def log_group(self, inst: str, night: str) -> LogGroup:
        rows = self.conn.execute("SELECT a.*, i.name AS item_name FROM awards a LEFT JOIN items i ON i.id = a.item_id "
                                 "WHERE COALESCE(a.inst, '') = ? AND a.night = ? ORDER BY a.at, a.who_key",
                                 (inst, night)).fetchall()
        awards = []
        for r in rows:
            name = r["item_name"] or name_from_link(r["link"]) or f"Item {r['item_id']}"
            # "new item": rolled on its first night in our raids (council items were decided, so not new).
            new_item = r["how"] != COUNCIL and self._first_night(r["item_id"]) == night
            awards.append(self._award_info(r, name, new_item))
        return LogGroup(inst=inst, night=night, awards=awards)

    # ---- dirty queues ------------------------------------------------------

    def dirty_items(self) -> list[tuple[int, int]]:
        return [(r["id"], r["dirty"]) for r in self.conn.execute("SELECT id, dirty FROM items WHERE dirty > 0 ORDER BY id")]

    def clear_item_dirty(self, item_id: int, generation: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE items SET dirty = 0 WHERE id = ? AND dirty = ?", (item_id, generation))

    def dirty_log_groups(self) -> list[tuple[str, str, int]]:
        return [(r["inst"], r["night"], r["dirty"]) for r in
                self.conn.execute("SELECT inst, night, dirty FROM log_groups WHERE dirty > 0 ORDER BY night, inst")]

    def clear_log_dirty(self, inst: str, night: str, generation: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE log_groups SET dirty = 0 WHERE inst = ? AND night = ? AND dirty = ?",
                              (inst, night, generation))

    def mark_all_dirty(self) -> None:
        with self.conn:
            self.conn.execute("UPDATE items SET dirty = dirty + 1")
            self.conn.execute("UPDATE log_groups SET dirty = dirty + 1")

    # ---- posts -------------------------------------------------------------

    def get_post(self, kind: str, key: str) -> Post | None:
        r = self.conn.execute("SELECT * FROM posts WHERE kind = ? AND key = ?", (kind, key)).fetchone()
        return Post(r["kind"], r["key"], r["channel_id"], r["message_id"], r["thread_id"], r["digest"]) if r else None

    def save_post(self, post: Post) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO posts(kind, key, channel_id, message_id, thread_id, digest) VALUES(?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(kind, key) DO UPDATE SET channel_id = excluded.channel_id, "
                "message_id = excluded.message_id, thread_id = excluded.thread_id, digest = excluded.digest",
                (post.kind, post.key, post.channel_id, post.message_id, post.thread_id, post.digest))

    def forget_post(self, kind: str, key: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM posts WHERE kind = ? AND key = ?", (kind, key))

    # ---- lists for #loot-priorities and /loot status ----------------------

    def item_states(self) -> list[ItemState]:
        return [s for s in (self.item_state(i) for i in self.all_item_ids()) if s is not None]

    def raid_names(self) -> list[str]:
        names = {s.raid for s in self.item_states() if s.raid}
        return sorted(names)

    # ---- tokens ------------------------------------------------------------

    def issue_token(self, owner: str, owner_name: str) -> str:
        """Create or replace an officer's API token. Only its hash is stored; the token is shown once."""
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        with self.conn:
            self.conn.execute(
                "INSERT INTO tokens(owner, owner_name, token_hash, created_at) VALUES(?, ?, ?, ?) "
                "ON CONFLICT(owner) DO UPDATE SET owner_name = excluded.owner_name, "
                "token_hash = excluded.token_hash, created_at = excluded.created_at, last_used_at = NULL",
                (owner, owner_name, _hash_token(token), self.now()))
        return token

    def token_owner(self, token: str) -> tuple[str, str] | None:
        if not token:
            return None
        row = self.conn.execute("SELECT owner, owner_name FROM tokens WHERE token_hash = ?",
                                (_hash_token(token),)).fetchone()
        if row is None:
            return None
        with self.conn:
            self.conn.execute("UPDATE tokens SET last_used_at = ? WHERE owner = ?", (self.now(), row["owner"]))
        return row["owner"], row["owner_name"]
