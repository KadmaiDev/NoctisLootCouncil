"""All reads and writes of the bot's database. No Discord here: the API and the cogs both call this."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import secrets
import sqlite3
import time
from typing import Callable
from zoneinfo import ZoneInfo

from . import iteminfo, rules, warcraftlogs
from .model import AwardInfo, ItemState, LogGroup, Post, UploadResult
from .rules import COUNCIL, HANDLINGS, Vote
from .upload import Upload, UploadItem, name_from_link

TOKEN_PREFIX = "nlc_"
# Loot counts as in a Warcraft Logs report from an hour before it starts (logging switched on late)
# to two hours after it ends (logging stopped before the last loot went out).
REPORT_SLACK_BEFORE, REPORT_SLACK_AFTER = 3600, 7200
# The game's clock and the log's can disagree a little: a kill this soon after the loot still counts as before it.
FIGHT_SLACK = 120


def _boss_key(name: str) -> str:
    """Boss names compared as the game and Warcraft Logs may spell them ('Majordomo Executus')."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


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
                 quality: int | None = None, by: str | None = None, origin: str | None = None) -> bool:
        """/loot add. Returns True if the item is new; an existing item gets the given details updated.
        The quality is the officer's choice until an upload from the game sets the real one. `origin`
        says where an item that hasn't dropped for us was found (wowhead, other_raid)."""
        name = name.strip()
        with self.conn:
            if self.item_exists(item_id):
                self.conn.execute(
                    "UPDATE items SET name = ?, slot = COALESCE(?, slot), source = COALESCE(?, source), "
                    "quality = CASE WHEN link IS NULL THEN COALESCE(?, quality) ELSE quality END, "
                    "origin = COALESCE(origin, ?) WHERE id = ?",
                    (name, slot or None, source or None, quality, origin, item_id))
                self._mark_dirty(item_id)
                self._refresh_decisions_at()
                return False
            self.conn.execute(
                "INSERT INTO items(id, name, slot, source, quality, added_by, created_at, origin) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (item_id, name, slot or None, source or None, quality, by, self.now(), origin))
            return True

    def import_items(self, found: list[tuple[int, str, str | None, int | None]], origin: str,
                     by: str | None = None) -> tuple[int, int]:
        """/loot import: (item ID, name, source, quality) found outside our raids. New items are added;
        one already on the list only gets a source if it had none. Returns (added, sources filled)."""
        added = filled = 0
        for item_id, name, source, quality in found:
            if not self.item_exists(item_id):
                self.add_item(item_id, name, source=source, quality=quality, by=by, origin=origin)
                added += 1
            elif source:
                with self.conn:
                    cur = self.conn.execute("UPDATE items SET source = ? WHERE id = ? AND source IS NULL "
                                            "AND inst IS NULL", (source, item_id))
                    if cur.rowcount:
                        self._mark_dirty(item_id)
                        filled += 1
        return added, filled

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
                         nos=r["nos"], tags=r["tags"], new_item=new_item)

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
        suggesters = [r["user_name"] for r in self.conn.execute(
            "SELECT user_name FROM suggestions WHERE item_id = ? ORDER BY at, user_id", (item_id,))]
        info = self.conn.execute("SELECT ii.*, e.emoji, im.icon IS NOT NULL AS has_image FROM item_info ii "
                                 "LEFT JOIN icon_emojis e ON e.icon = ii.icon "
                                 "LEFT JOIN icon_images im ON im.icon = ii.icon WHERE ii.item_id = ?",
                                 (item_id,)).fetchone()
        # Quality: the game's once an upload has it, else Wowhead's Forever data, else /loot add's.
        quality = row["quality"]
        if row["link"] is None and info and info["quality"] is not None:
            quality = info["quality"]
        return ItemState(
            id=row["id"], name=row["name"], quality=quality, slot=row["slot"] or (info and info["slot"]),
            icon=info and info["icon"], emoji=info and info["emoji"], icon_image=bool(info and info["has_image"]),
            wowhead=(info["env"], info["name"] or row["name"]) if info and info["found"] and info["env"] else None,
            source_text=self._source_text(row), raid=self._raid_name(row),
            tally=rules.tally(self._votes(item_id), self.votes_to_decide),
            decision=row["decision"], game_handling=row["game_handling"], game_note=row["game_note"],
            game_by=row["game_by"], priority=row["priority"], priority_by=row["priority_by"],
            suggestions=len(suggesters), suggested_by=tuple(n for n in suggesters if n),
            drops=max(drops["n"], row["seen"]),
            first_drop_at=min(firsts) if firsts else None, last_drop_at=max(lasts) if lasts else None,
            new_in_raid=bool(row["new_in_raid"]), created_at=row["created_at"], origin=row["origin"],
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
            taken_back = result.decided is None and current is not None
            if taken_back:
                # Taken back: the game is told "none", and an older in-game decision doesn't
                # come back in its place.
                self.conn.execute("UPDATE items SET decision = NULL, decided_at = NULL, cleared_at = ?, "
                                  "game_handling = NULL, game_note = NULL, game_by = NULL WHERE id = ?",
                                  (self.now(), item_id))
            elif result.decided != current:
                self.conn.execute("UPDATE items SET decision = ?, decided_at = ?, cleared_at = NULL WHERE id = ?",
                                  (result.decided, self.now(), item_id))
            self._mark_dirty(item_id)
            self._refresh_decisions_at()
            if taken_back:
                # cleared_at is the decisions version that carries the "none": a game that has
                # applied it (its decisions_at is at least this) has heard. A time would do too,
                # except when the decision and its taking back fall in the same second.
                self.conn.execute("UPDATE items SET cleared_at = ? WHERE id = ?",
                                  (int(self._meta("decisions_at", "0") or 0), item_id))
        return result

    def toggle_suggestion(self, item_id: int, user_id: int, user_name: str | None = None) -> tuple[bool, int]:
        """Suggest for council, or take the suggestion back. Returns (suggesting now, total)."""
        with self.conn:
            cur = self.conn.execute("DELETE FROM suggestions WHERE item_id = ? AND user_id = ?", (item_id, user_id))
            on = cur.rowcount == 0
            if on:
                self.conn.execute("INSERT INTO suggestions(item_id, user_id, at, user_name) VALUES(?, ?, ?, ?)",
                                  (item_id, user_id, self.now(), user_name))
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
                                     "WHERE decision IS NOT NULL OR game_handling IS NOT NULL OR cleared_at IS NOT NULL "
                                     "ORDER BY id"):
            handling = row["decision"] or row["game_handling"] or "none"
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

    def _merge_item(self, it: UploadItem, uploader: str, decisions_at: int | None = None) -> bool:
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
        # /loot add's free text wins; otherwise the slot and type the game reported.
        slot = rules.slot_text(it.slot, it.sub)
        if slot and not row["slot"]:
            self.conn.execute("UPDATE items SET slot = ? WHERE id = ?", (slot, it.id))
        old = {r["src"]: r["count"] for r in
               self.conn.execute("SELECT src, count FROM item_sources WHERE item_id = ?", (it.id,))}
        for src, n in rules.merge_sources(old, it.sources).items():
            self.conn.execute("INSERT INTO item_sources(item_id, src, count) VALUES(?, ?, ?) "
                              "ON CONFLICT(item_id, src) DO UPDATE SET count = excluded.count", (it.id, src, n))
        # An in-game decision counts only while Discord has none. Recording it only then also keeps
        # the addon's echo of a Discord decision (written back by the companion) from being taken
        # for a decision made in game. After a decision is taken back, the game still has it until
        # its decisions are newer than that, so until then what it reports is the old echo.
        stale = row["cleared_at"] is not None and (decisions_at or 0) < row["cleared_at"]
        if row["decision"] is None and not stale and it.handling is not None and (
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
                new_items += self._merge_item(it, uploader, up.decisions_at)
            # An award for an item missing from the list still means it dropped for us.
            for aw in up.awards:
                if aw.id not in listed and not self.item_exists(aw.id):
                    new_items += self._merge_item(UploadItem(id=aw.id, name=name_from_link(aw.link), link=aw.link,
                                                             seen=1, first=aw.at, last=aw.at), uploader)
                    listed.add(aw.id)
            # A drop matches another officer's report of it; two drops in one upload are two
            # drops (the addon already counts each once), so a row matches at most once per upload.
            matched: set[int] = set()
            for d in up.drops:
                src = d.src or ""
                window = rules.DROP_WINDOW_SECONDS
                rows = self.conn.execute(
                    "SELECT id, at, n FROM drops WHERE item_id = ? AND src = ? AND at BETWEEN ? AND ? "
                    "ORDER BY ABS(at - ?)", (d.id, src, d.at - window, d.at + window, d.at)).fetchall()
                row = next((r for r in rows if r["id"] not in matched and rules.same_drop(d.at, r["at"])), None)
                if row is None:
                    cur = self.conn.execute("INSERT INTO drops(item_id, src, at, inst, n) VALUES(?, ?, ?, ?, ?)",
                                            (d.id, src, d.at, d.inst, d.n))
                    matched.add(cur.lastrowid)
                    changed = True
                else:
                    matched.add(row["id"])
                    changed = d.n > row["n"]
                    if changed:
                        self.conn.execute("UPDATE drops SET n = ? WHERE id = ?", (d.n, row["id"]))
                if changed and self.item_exists(d.id):
                    self._mark_dirty(d.id)
            for aw in up.awards:
                who_key, item_id, at = rules.award_key(aw.who, aw.id, aw.at)
                night = rules.night_of(at, self.tz).isoformat()
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO awards(who_key, item_id, at, who, class, how, roll, note, inst, boss, "
                    "nms, nos, tags, link, night, uploader, received_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (who_key, item_id, at, aw.who, aw.cls, aw.how, aw.roll, aw.note, aw.inst, aw.boss, aw.nms,
                     aw.nos, aw.tags, aw.link, night, uploader, self.now()))
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
        rows = self.conn.execute("SELECT a.*, i.name AS item_name, e.emoji, ii.found AS wh_found, "
                                 "ii.env AS wh_env, ii.name AS wh_name FROM awards a "
                                 "LEFT JOIN items i ON i.id = a.item_id "
                                 "LEFT JOIN item_info ii ON ii.item_id = a.item_id "
                                 "LEFT JOIN icon_emojis e ON e.icon = ii.icon "
                                 "WHERE COALESCE(a.inst, '') = ? AND a.night = ? ORDER BY a.at, a.who_key",
                                 (inst, night)).fetchall()
        awards = []
        for r in rows:
            name = r["item_name"] or name_from_link(r["link"]) or f"Item {r['item_id']}"
            # "new item": rolled on its first night in our raids (council items were decided, so not new).
            new_item = r["how"] != COUNCIL and self._first_night(r["item_id"]) == night
            url = (iteminfo.page_url(r["item_id"], r["wh_name"] or name, r["wh_env"])
                   if r["wh_found"] and r["wh_env"] else None)
            awards.append(dataclasses.replace(self._award_info(r, name, new_item), emoji=r["emoji"], url=url))
        report = self._report_for(night, [a.at for a in awards])
        if report is None:
            return LogGroup(inst=inst, night=night, awards=awards)
        return LogGroup(inst=inst, night=night, awards=awards,
                        report_url=warcraftlogs.report_url(report["host"], report["code"]),
                        fight_urls=self._fight_urls(report, awards))

    # ---- Warcraft Logs (warcraftlogs.py) -------------------------------------

    def save_report(self, report: warcraftlogs.Report, by: str | None = None) -> list[tuple[str, str]]:
        """Keep a report and its boss kills. Returns the #loot-log posts (raid, night) that now link to it."""
        first, last = (rules.night_of(t, self.tz).isoformat() for t in (report.start_at, report.end_at))
        with self.conn:
            self.conn.execute(
                "INSERT INTO wcl_reports(code, host, title, start_at, end_at, first_night, last_night, added_at, "
                "added_by) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(code) DO UPDATE SET host = excluded.host, "
                "title = excluded.title, start_at = excluded.start_at, end_at = excluded.end_at, "
                "first_night = excluded.first_night, last_night = excluded.last_night, "
                "added_at = excluded.added_at, added_by = excluded.added_by",
                (report.code, report.host, report.title, report.start_at, report.end_at, first, last, self.now(), by))
            self.conn.execute("DELETE FROM wcl_fights WHERE code = ?", (report.code,))
            self.conn.executemany("INSERT INTO wcl_fights(code, id, name, end_at) VALUES(?, ?, ?, ?)",
                                  [(report.code, f.id, f.name, f.end_at) for f in report.fights])
            self.conn.execute("UPDATE log_groups SET dirty = dirty + 1 WHERE night BETWEEN ? AND ?", (first, last))
        groups = self.conn.execute("SELECT inst, night FROM log_groups WHERE night BETWEEN ? AND ? "
                                   "ORDER BY night, inst", (first, last)).fetchall()
        linked = []
        for g in groups:
            times = [r["at"] for r in self.conn.execute(
                "SELECT at FROM awards WHERE COALESCE(inst, '') = ? AND night = ?", (g["inst"], g["night"]))]
            chosen = self._report_for(g["night"], times)
            if chosen is not None and chosen["code"] == report.code:
                linked.append((g["inst"], g["night"]))
        return linked

    def _report_for(self, night: str, times: list[int]) -> sqlite3.Row | None:
        """Of the reports on this night, the one whose span holds the most of the loot (the latest
        linked on a tie: an officer correcting a link). One holding none of it is another raid's."""
        rows = self.conn.execute("SELECT * FROM wcl_reports WHERE ? BETWEEN first_night AND last_night",
                                 (night,)).fetchall()

        def covered(r: sqlite3.Row) -> int:
            return sum(r["start_at"] - REPORT_SLACK_BEFORE <= t <= r["end_at"] + REPORT_SLACK_AFTER for t in times)
        scored = [(covered(r), r["added_at"], r["code"], r) for r in rows]
        return max((s for s in scored if s[0]), key=lambda s: s[:3], default=(None,) * 4)[3]

    def _fight_urls(self, report: sqlite3.Row, awards: list[AwardInfo]) -> dict[str, str]:
        """Each boss's kill: the last one before its loot was handed out (or the nearest, if the
        clocks disagree)."""
        fights = self.conn.execute("SELECT id, name, end_at FROM wcl_fights WHERE code = ?",
                                   (report["code"],)).fetchall()
        first_loot: dict[str, int] = {}
        for a in awards:
            if a.boss:
                first_loot.setdefault(a.boss, a.at)
        urls = {}
        for boss, at in first_loot.items():
            kills = [f for f in fights if _boss_key(f["name"]) == _boss_key(boss)]
            if not kills:
                continue
            before = [f for f in kills if f["end_at"] <= at + FIGHT_SLACK]
            kill = max(before, key=lambda f: f["end_at"]) if before else min(kills, key=lambda f: abs(f["end_at"] - at))
            urls[boss] = warcraftlogs.fight_url(report["host"], report["code"], kill["id"])
        return urls

    # ---- item info (iteminfo.py) ---------------------------------------------

    def items_to_look_up(self, limit: int = 25) -> list[int]:
        """Items due a Wowhead lookup: first those about to be posted (dirty, or in a dirty log post),
        then any other, a few at a time so a long list doesn't flood Wowhead."""
        soon = {r["id"] for r in self.conn.execute("SELECT id FROM items WHERE dirty > 0")}
        soon |= {r["item_id"] for r in self.conn.execute(
            "SELECT DISTINCT a.item_id FROM awards a JOIN log_groups g "
            "ON COALESCE(a.inst, '') = g.inst AND a.night = g.night WHERE g.dirty > 0")}
        rest = {r["id"] for r in self.conn.execute("SELECT id FROM items")} - soon
        due = [i for i in (*sorted(soon), *sorted(rest)) if self.item_info_due(i)]
        return due[:limit]

    def item_info_due(self, item_id: int) -> bool:
        """Never looked up, or not in Wowhead's Forever database a day or more ago."""
        r = self.conn.execute("SELECT env, fetched_at FROM item_info WHERE item_id = ?", (item_id,)).fetchone()
        return r is None or (r["env"] != iteminfo.FOREVER and self.now() - r["fetched_at"] >= iteminfo.RETRY_SECONDS)

    def save_item_info(self, item_id: int, info: iteminfo.ItemInfo) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO item_info(item_id, found, icon, slot, fetched_at, env, name, quality) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(item_id) DO UPDATE SET found = excluded.found, icon = excluded.icon, "
                "slot = excluded.slot, fetched_at = excluded.fetched_at, env = excluded.env, "
                "name = excluded.name, quality = excluded.quality",
                (item_id, int(info.found), info.icon, info.slot, self.now(), info.env, info.name, info.quality))
            self._mark_dirty(item_id)
            self.conn.execute(
                "UPDATE log_groups SET dirty = dirty + 1 WHERE EXISTS (SELECT 1 FROM awards a WHERE a.item_id = ? "
                "AND COALESCE(a.inst, '') = log_groups.inst AND a.night = log_groups.night)", (item_id,))

    def icons_without_image(self) -> list[str]:
        return [r["icon"] for r in self.conn.execute(
            "SELECT DISTINCT icon FROM item_info WHERE found = 1 AND icon IS NOT NULL "
            "AND icon NOT IN (SELECT icon FROM icon_images) ORDER BY icon")]

    def icon_image(self, icon: str) -> bytes | None:
        r = self.conn.execute("SELECT image FROM icon_images WHERE icon = ?", (icon,)).fetchone()
        return bytes(r["image"]) if r else None

    def save_icon_image(self, icon: str, image: bytes) -> None:
        """A new picture: the posts of items with that icon are marked for editing (their title has it)."""
        with self.conn:
            self.conn.execute("INSERT INTO icon_images(icon, image) VALUES(?, ?) "
                              "ON CONFLICT(icon) DO UPDATE SET image = excluded.image", (icon, image))
            self.conn.execute("UPDATE items SET dirty = dirty + 1 WHERE id IN "
                              "(SELECT item_id FROM item_info WHERE icon = ?)", (icon,))

    def icons_without_emoji(self) -> list[str]:
        return [r["icon"] for r in self.conn.execute(
            "SELECT DISTINCT icon FROM item_info WHERE found = 1 AND icon IS NOT NULL "
            "AND icon NOT IN (SELECT icon FROM icon_emojis) ORDER BY icon")]

    def save_icon_emoji(self, icon: str, emoji: str) -> None:
        """A new emoji: every list line with that icon changes, so their posts are marked for editing."""
        with self.conn:
            self.conn.execute("INSERT INTO icon_emojis(icon, emoji) VALUES(?, ?) "
                              "ON CONFLICT(icon) DO UPDATE SET emoji = excluded.emoji", (icon, emoji))
            self.conn.execute(
                "UPDATE log_groups SET dirty = dirty + 1 WHERE EXISTS (SELECT 1 FROM awards a "
                "JOIN item_info ii ON ii.item_id = a.item_id WHERE ii.icon = ? "
                "AND COALESCE(a.inst, '') = log_groups.inst AND a.night = log_groups.night)", (icon,))

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
