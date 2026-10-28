import copy

import pytest

from bot.rules import COUNCIL, ROLL
from bot.upload import BadUpload, parse_upload

from .conftest import RAID, link, sample_body


def upload(store, body, owner=("discord:1", "Kadmai")):
    return store.apply_upload(parse_upload(body), *owner)


# ---- parsing ------------------------------------------------------------------

def test_parse_takes_name_from_link():
    up = parse_upload(sample_body())
    names = {it.id: it.name for it in up.items}
    assert names == {18000: "Sash of the Unseen", 16805: "Felheart Gloves", 17069: None}


def test_parse_rejects_wrong_containers():
    with pytest.raises(BadUpload):
        parse_upload([])
    with pytest.raises(BadUpload):
        parse_upload({"items": []})
    with pytest.raises(BadUpload):
        parse_upload({"awards": {"1": {}}})


def test_parse_accepts_empty_table_for_list():
    # An empty Lua table is the same for a list and a map; the companion may send it as {}.
    up = parse_upload({"drops": {}, "awards": {}})
    assert up.drops == [] and up.awards == []


def test_parse_skips_malformed_entries():
    body = sample_body()
    body["items"]["abc"] = {"seen": 1}
    body["awards"].append({"id": 1, "who": "Nobody"})  # no `at` or `how`
    body["drops"].append("not a drop")
    up = parse_upload(body)
    assert up.skipped == 3
    assert len(up.items) == 3 and len(up.awards) == 2 and len(up.drops) == 2


def test_parse_ignores_unknown_handling():
    body = sample_body()
    body["items"]["16805"]["handling"] = "disenchant"
    up = parse_upload(body)
    assert next(it for it in up.items if it.id == 16805).handling is None


# ---- merging and de-duplication ---------------------------------------------------

def test_first_upload_creates_items_and_awards(store):
    result = upload(store, sample_body())
    assert (result.new_items, result.new_awards) == (3, 2)
    sash = store.item_state(18000)
    assert sash.name == "Sash of the Unseen"
    assert sash.source_text == "Molten Core, Lucifron"
    assert sash.raid == "Molten Core"
    assert sash.new_in_raid
    assert sash.drops == 1
    # An item added in game before it dropped (seen 0) is listed but isn't new in our raids.
    unseen = store.item_state(17069)
    assert unseen.name == "Item 17069" and not unseen.new_in_raid and unseen.drops == 0


def test_same_upload_twice_changes_nothing(store):
    upload(store, sample_body())
    result = upload(store, sample_body())
    assert (result.new_items, result.new_awards) == (0, 0)
    assert store.item_state(16805).drops == 1
    assert len(store.log_group("Molten Core", "2026-10-26").awards) == 2


def test_award_dedupe_ignores_winner_case(store):
    upload(store, sample_body())
    body = sample_body("Seren Ashvale")
    for aw in body["awards"]:
        aw["who"] = aw["who"].upper()
    assert upload(store, body, ("discord:2", "Seren")).new_awards == 0


def test_two_officers_same_drop_counted_once_keeping_largest_n(store):
    upload(store, sample_body())
    other = sample_body("Seren Ashvale")
    # The other officer's client saw the same drop a few seconds later, and two copies of it.
    other["drops"] = [{"id": 16805, "at": RAID + 905, "src": "e663", "inst": 409, "n": 2}]
    upload(store, other, ("discord:2", "Seren"))
    assert store.item_state(16805).drops == 2
    # Either side of a half-hour boundary is still the same drop.
    across = sample_body("Doran Pike")
    across["drops"] = [{"id": 16805, "at": RAID + 900 - 600, "src": "e663", "inst": 409, "n": 1}]
    upload(store, across, ("discord:3", "Doran"))
    assert store.item_state(16805).drops == 2
    # Hours later it's a separate sighting.
    later = sample_body()
    later["drops"] = [{"id": 16805, "at": RAID + 3 * 3600, "src": "e663", "inst": 409, "n": 1}]
    upload(store, later)
    assert store.item_state(16805).drops == 3


def test_item_merge_rules(store):
    upload(store, sample_body())
    body = sample_body()
    sash = body["items"]["18000"]
    sash["first"] = RAID - 86400 * 10
    sash["last"] = RAID + 7200
    sash["from"] = {"e664": 1}
    body["encounters"]["664"] = {"name": "Gehennas", "inst": 409}
    body["items"]["17069"]["link"] = link(17069, "Strikers Mark", "a335ee")
    upload(store, body)
    row = store.conn.execute("SELECT * FROM items WHERE id = 18000").fetchone()
    assert row["first_at"] == RAID - 86400 * 10 and row["last_at"] == RAID + 7200
    srcs = {r["src"] for r in store.conn.execute("SELECT src FROM item_sources WHERE item_id = 18000")}
    assert srcs == {"e663", "e664"}
    assert store.item_state(18000).source_text == "Molten Core, Lucifron, Gehennas"
    # The name arrives once the game has loaded the item.
    assert store.item_state(17069).name == "Strikers Mark"
    # A bare link never replaces a full one.
    body["items"]["17069"]["link"] = "item:17069"
    upload(store, body)
    assert "|Hitem:" in store.conn.execute("SELECT link FROM items WHERE id = 17069").fetchone()["link"]


def test_award_for_unlisted_item_creates_it(store):
    body = sample_body()
    body["awards"].append({"id": 19019, "link": link(19019, "Thunderfury", "ff8000"), "who": "Doran Pike",
                           "at": RAID + 2000, "how": "ms", "roll": 99, "inst": "Molten Core"})
    upload(store, body)
    state = store.item_state(19019)
    assert state.name == "Thunderfury" and state.new_in_raid


def test_known_item_dropping_is_not_new(store):
    store.add_item(16805, "Felheart Gloves", slot="Hands · Cloth", by="Kadmai")
    result = upload(store, sample_body())
    assert result.new_items == 2
    gloves = store.item_state(16805)
    assert not gloves.new_in_raid and gloves.drops == 1 and gloves.slot == "Hands · Cloth"


# ---- decisions --------------------------------------------------------------

def test_votes_decide_and_can_be_undone(store, clock):
    store.add_item(18000, "Sash of the Unseen")
    store.cast_vote(18000, 1, "Seren", COUNCIL)
    store.cast_vote(18000, 2, "Doran", COUNCIL)
    assert store.decisions()["items"] == {}
    t = store.cast_vote(18000, 3, "Kadmai", COUNCIL)
    assert t.decided == COUNCIL
    at1 = store.decisions()["at"]
    assert store.decisions()["items"] == {"18000": {"handling": "council", "name": "Sash of the Unseen"}}
    # Same second, another change: `at` still moves on so the companion notices.
    store.cast_vote(18000, 3, "Kadmai", ROLL)
    assert store.item_state(18000).decision is None
    # Listed as "none" so the game forgets it too.
    assert store.decisions()["items"] == {"18000": {"handling": "none", "name": "Sash of the Unseen"}}
    assert store.decisions()["at"] > at1
    store.cast_vote(18000, 2, "Doran", ROLL)
    store.cast_vote(18000, 1, "Seren", ROLL)
    assert store.decisions()["items"] == {"18000": {"handling": "roll", "name": "Sash of the Unseen"}}


def test_priority_is_the_note_and_moves_at(store, clock):
    store.add_item(18000, "Sash of the Unseen")
    for uid in (1, 2, 3):
        store.cast_vote(18000, uid, f"O{uid}", COUNCIL)
    at1 = store.decisions()["at"]
    clock.t += 60
    store.set_priority(18000, " Warlock priority ", "Seren")
    d = store.decisions()
    assert d["items"]["18000"]["note"] == "Warlock priority"
    assert d["at"] == int(clock.t) > at1
    store.set_priority(18000, "", "Seren")
    assert "note" not in store.decisions()["items"]["18000"]


def test_unchanged_list_keeps_at(store, clock):
    store.add_item(18000, "Sash")
    for uid in (1, 2, 3):
        store.cast_vote(18000, uid, f"O{uid}", ROLL)
    at1 = store.decisions()["at"]
    clock.t += 100
    store.cast_vote(18000, 1, "O1", ROLL)  # pressing the same button again
    store.toggle_suggestion(18000, 99)
    assert store.decisions()["at"] == at1


def test_in_game_decision_used_without_a_discord_one(store):
    upload(store, sample_body())
    d = store.decisions()["items"]
    assert d["18000"] == {"handling": "council", "note": "Warlock priority", "name": "Sash of the Unseen"}
    state = store.item_state(18000)
    assert state.decided_in_game and state.game_by == "Kadmai Moonwhisper"


def test_discord_decision_wins_over_game(store):
    store.add_item(18000, "Sash of the Unseen")
    for uid in (1, 2, 3):
        store.cast_vote(18000, uid, f"O{uid}", ROLL)
    upload(store, sample_body())  # the saved file still says council
    assert store.decisions()["items"]["18000"] == {"handling": "roll", "name": "Sash of the Unseen"}
    state = store.item_state(18000)
    assert state.handling == ROLL and state.game_handling is None


def test_echo_of_discord_decision_is_not_recorded_as_in_game(store):
    store.add_item(18000, "Sash of the Unseen")
    for uid in (1, 2, 3):
        store.cast_vote(18000, uid, f"O{uid}", COUNCIL)
    upload(store, sample_body())  # the addon applied our decision and uploads it back
    store.cast_vote(18000, 3, "O3", ROLL)  # the officers undo it
    assert store.item_state(18000).handling is None


def test_taken_back_decision_isnt_relearnt_from_the_game_until_it_has_heard(store, clock):
    store.add_item(18000, "Sash of the Unseen")
    for uid in (1, 2, 3):
        store.cast_vote(18000, uid, f"O{uid}", COUNCIL)
    clock.t += 3600
    store.cast_vote(18000, 3, "O3", ROLL)  # taken back
    cleared = store.decisions()["at"]
    body = sample_body()  # the game still has "council" from before
    body["decisions_at"] = cleared - 3600
    upload(store, body)
    assert store.decisions()["items"]["18000"]["handling"] == "none"
    # Once its decisions include the "none", what it reports is a real in-game decision.
    clock.t += 600
    body["decisions_at"] = cleared
    upload(store, body)
    assert store.decisions()["items"]["18000"]["handling"] == "council"
    assert store.item_state(18000).decided_in_game


def test_taken_back_in_the_same_second_it_was_decided(store, clock):
    # Found by the harness: with times, a game holding the decision from this very second looked
    # as if it had already heard it was taken back.
    store.add_item(18000, "Sash of the Unseen")
    for uid in (1, 2, 3):
        store.cast_vote(18000, uid, f"O{uid}", COUNCIL)
    decided = store.decisions()["at"]
    store.cast_vote(18000, 3, "O3", ROLL)  # same second
    body = sample_body()  # the game applied the council decision and reports it back
    body["decisions_at"] = decided
    upload(store, body)
    assert store.decisions()["items"]["18000"]["handling"] == "none"


def test_slot_and_type_from_the_game_and_award_tags(store):
    body = sample_body()
    body["items"]["18000"].update(slot="INVTYPE_WAIST", sub="Cloth")
    body["awards"][0]["tags"] = "BIS, Big upgrade"
    upload(store, body)
    assert store.item_state(18000).slot == "Waist · Cloth"
    award = store.item_state(body["awards"][0]["id"]).first_award
    assert award.tags == "BIS, Big upgrade"


def test_suggestions_toggle(store):
    store.add_item(18000, "Sash")
    assert store.toggle_suggestion(18000, 7) == (True, 1)
    assert store.toggle_suggestion(18000, 8) == (True, 2)
    assert store.toggle_suggestion(18000, 7) == (False, 1)
    assert store.item_state(18000).suggestions == 1
    store.toggle_suggestion(18000, 9, "Ilsa")
    store.toggle_suggestion(18000, 10, "Vespera")
    s = store.item_state(18000)
    assert (s.suggestions, s.suggested_by) == (3, ("Ilsa", "Vespera"))  # 8 suggested without a name


def test_old_database_gets_the_new_columns(tmp_path):
    import sqlite3

    from bot.db import connect
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE suggestions (item_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "
                "at INTEGER NOT NULL, PRIMARY KEY (item_id, user_id))")
    old.execute("INSERT INTO suggestions VALUES (18000, 7, 1)")
    old.commit()
    old.close()
    conn = connect(path)
    assert [tuple(r) for r in conn.execute("SELECT user_id, user_name FROM suggestions")] == [(7, None)]
    connect(path)  # and again: nothing to add


# ---- posting queues -----------------------------------------------------------

def test_dirty_generation_survives_change_during_post(store):
    store.add_item(18000, "Sash")
    [(item_id, gen)] = store.dirty_items()
    store.toggle_suggestion(18000, 1)  # changes while the poster is busy
    store.clear_item_dirty(item_id, gen)
    assert [i for i, _ in store.dirty_items()] == [18000]
    [(_, gen2)] = store.dirty_items()
    store.clear_item_dirty(18000, gen2)
    assert store.dirty_items() == []


def test_new_awards_mark_their_night(store):
    upload(store, sample_body())
    groups = store.dirty_log_groups()
    assert [(g[0], g[1]) for g in groups] == [("Molten Core", "2026-10-26")]
    store.clear_log_dirty("Molten Core", "2026-10-26", groups[0][2])
    upload(store, sample_body())
    assert store.dirty_log_groups() == []


def test_log_group_marks_new_items(store):
    body = sample_body()
    upload(store, body)
    group = store.log_group("Molten Core", "2026-10-26")
    flags = {a.item_name: a.new_item for a in group.awards}
    assert flags == {"Sash of the Unseen": False, "Felheart Gloves": True}
    # Next week the gloves drop again: not new any more.
    nxt = copy.deepcopy(body)
    week = 7 * 86400
    nxt["drops"] = [{"id": 16805, "at": RAID + week, "src": "e663", "inst": 409, "n": 1}]
    nxt["awards"] = [{"id": 16805, "who": "Bran Holloway", "at": RAID + week + 60, "how": "os", "roll": 40,
                      "inst": "Molten Core"}]
    upload(store, nxt)
    later = store.log_group("Molten Core", "2026-11-02")
    assert [a.new_item for a in later.awards] == [False]


# ---- tokens --------------------------------------------------------------------

def test_tokens_rotate_and_store_only_a_hash(store):
    t1 = store.issue_token("discord:1", "Kadmai")
    assert store.token_owner(t1) == ("discord:1", "Kadmai")
    t2 = store.issue_token("discord:1", "Kadmai")
    assert store.token_owner(t1) is None
    assert store.token_owner(t2) == ("discord:1", "Kadmai")
    stored = store.conn.execute("SELECT token_hash FROM tokens").fetchone()["token_hash"]
    assert t2 not in stored
    assert store.token_owner("") is None
