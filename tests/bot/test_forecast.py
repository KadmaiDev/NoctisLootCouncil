"""The road to max level (forecast.py): the sums, the posts' wording, what the store keeps of the
level-ups, and the poster that keeps the forecast channel in step."""
from __future__ import annotations

from zoneinfo import ZoneInfo

from bot import forecast, roster
from bot.forecast import DAY, Reached
from bot.milestones import parse_milestone_upload

from .conftest import RAID, Clock
from .test_poster import FakeChannel, make_bot, text

TZ = ZoneInfo("Australia/Perth")
NOW = 1_800_000_000
AT_50 = 45 + 5 * 50  # a level 50 monster's experience
ROAD_CHANNEL, ROSTER_CHANNEL = 40, 30


def steady(start: int, end: int, per_day_xp: float, now: int = NOW, read_gap: int = 60) -> list[Reached]:
    """Level-ups of someone playing steadily (as much each day as earns `per_day_xp` at level 50),
    reaching `end` exactly at `now`, each seen within `read_gap` seconds."""
    out, t = [], float(now)
    for level in range(end, start, -1):
        out.append(Reached(level, int(t) - read_gap, int(t)))
        t -= forecast.work_to_next(level - 1) / (per_day_xp / AT_50) * DAY
    return out[::-1]


# ---- the sums ------------------------------------------------------------------------------------

def test_the_experience_table_is_classics():
    assert len(forecast.XP_TO_NEXT) == 59
    assert forecast.xp_at(1) == 0 and forecast.xp_at(2) == 400 and forecast.xp_at(60) == 4_084_700
    assert forecast.xp_to_next(59) == 209_800 and forecast.xp_to_next(75) == 209_800


def test_levels_are_weighed_by_how_long_they_take_not_by_experience():
    # A level 50 monster gives 295 experience, a level 25 one 170: the same play earns more later on.
    assert forecast.work_to_next(50) == 147_500 / 295 and forecast.work_to_next(25) == 34_000 / 170
    share = [round(100 * forecast.work_at(lv) / forecast.work_at(60)) for lv in (30, 40, 50)]
    assert share == [21, 40, 66]  # by experience alone: 12, 28, 56
    # Someone steady through the thirties is forecast sooner than their experience a day would say.
    f = forecast.forecast(40, steady(30, 40, 60_000), NOW, 60)
    history = steady(30, 40, 60_000)
    xp_a_day = (forecast.xp_at(40) - forecast.xp_at(31)) / ((history[-1].hi - history[0].hi) / DAY)
    assert (f.eta - NOW) / DAY < 0.8 * (forecast.xp_at(60) - forecast.xp_at(40)) / xp_a_day


def test_a_steady_pace_is_carried_forward():
    # At level 50 this minute, after ten levels at a steady pace: the same pace for the ten to go.
    f = forecast.forecast(50, steady(40, 50, 100_000), NOW, 60)
    days = (f.eta - NOW) / DAY
    assert abs(days - (forecast.work_at(60) - forecast.work_at(50)) / (100_000 / AT_50)) < 0.05
    # The range is never tighter than a quarter earlier to half as long again.
    assert (f.early - NOW) / DAY <= 0.75 * days + 0.01 and (f.late - NOW) / DAY >= 1.5 * days - 0.01


def test_only_the_last_two_weeks_set_the_pace():
    # Slow a month ago, fast for the last ten days: the fast pace counts.
    old = steady(20, 30, 10_000, now=NOW - 10 * DAY)
    fast = steady(30, 40, 90_000)[1:]
    f = forecast.forecast(40, old + fast, NOW, 60)
    days = (f.eta - NOW) / DAY
    assert abs(days - (forecast.work_at(60) - forecast.work_at(40)) / (90_000 / AT_50)) / days < 0.2


def test_a_forecast_slips_as_a_character_goes_quiet():
    history = steady(40, 50, 100_000)
    just = forecast.forecast(50, history, NOW, 60)
    # Three hours on they could still be within the level: the same date.
    soon = forecast.forecast(50, history, NOW + 3 * 3600, 60)
    assert abs(soon.eta - just.eta) < 600
    # A week of nothing: later, and later still after ten days.
    week = forecast.forecast(50, history, NOW + 7 * DAY, 60)
    ten = forecast.forecast(50, history, NOW + 10 * DAY, 60)
    assert just.eta < week.eta < ten.eta
    # No level-up in two weeks: no estimate.
    assert forecast.forecast(50, history, NOW + 15 * DAY, 60) is None


def test_too_little_to_go_on_is_no_forecast():
    assert forecast.forecast(60, steady(40, 60, 100_000), NOW, 60) is None  # there already
    assert forecast.forecast(30, [], NOW, 60) is None
    assert forecast.forecast(30, [Reached(30, NOW - 120, NOW - 60)], NOW, 60) is None  # one level-up seen
    # Two levels noticed in one read after time away: nothing between them to measure.
    assert forecast.forecast(31, [Reached(30, NOW - DAY, NOW - 60), Reached(31, NOW - DAY, NOW - 60)], NOW, 60) is None
    # A level-up from the future (not yet "now") is left out.
    assert forecast.forecast(31, [Reached(30, None, NOW - 3 * DAY), Reached(31, None, NOW + 60)], NOW, 60) is not None
    # Over a year away at this pace.
    assert forecast.forecast(12, [Reached(11, None, NOW - 13 * DAY), Reached(12, None, NOW - DAY)], NOW, 60) is None


def test_a_first_session_is_no_forecast_until_two_days_have_been_watched():
    # A character made this afternoon: four levels in two and a half hours. Carried forward as if
    # they never stopped, that reaches 60 within the week.
    first, hour = NOW - 9000, 3600
    session = [Reached(6, first - 60, first), Reached(7, first + 2100, first + 2160),
               Reached(8, first + 2 * hour, first + 2 * hour + 60), Reached(10, NOW - 600, NOW - 60)]
    assert forecast.forecast(10, session, NOW, 60) is None
    assert forecast.why_not(10, session, NOW) == forecast.UNSEEN
    assert forecast.forecast(10, session, NOW + DAY, 60) is None
    # Two days on, the days without a level-up are part of the pace: months, not days.
    f = forecast.forecast(10, session, first + 2 * DAY + 60, 60)
    assert f is not None and f.eta - NOW > 60 * DAY and f.quality == forecast.THIN
    # Someone back after three weeks away who levels twice in an evening is measured from before the break.
    back = [Reached(40, None, NOW - 21 * DAY), Reached(41, NOW - 7300, NOW - 7200), Reached(42, NOW - 120, NOW - 60)]
    assert forecast.forecast(42, back, NOW, 60) is None and forecast.why_not(42, back, NOW) == forecast.UNSEEN


def test_one_recent_level_up_is_measured_from_the_one_before():
    before, last = Reached(57, None, NOW - 20 * DAY), Reached(58, None, NOW - DAY)
    assert forecast.forecast(58, [before, last], NOW, 60) is not None
    assert forecast.forecast(58, [Reached(57, None, NOW - 40 * DAY), last], NOW, 60) is None


def test_a_level_nobody_saw_reached_counts_from_the_last_one_seen():
    # The roster shows 33; the level-ups on record end at 31.
    history = steady(25, 31, 30_000, now=NOW - 2 * DAY)
    f = forecast.forecast(33, history, NOW, 60)
    assert f is not None and f.eta > NOW


def test_wide_gaps_between_roster_reads_widen_the_range():
    tight = forecast.forecast(50, steady(45, 50, 100_000), NOW, 60)
    assert tight.late - NOW <= 1.51 * (tight.eta - NOW)
    # Two level-ups a day and a half apart, each somewhere in thirty hours without an officer online.
    wide = forecast.forecast(50, steady(48, 50, 100_000, read_gap=30 * 3600), NOW, 60)
    assert wide.late - NOW > 1.6 * (wide.eta - NOW)
    # Without `since` (older companions) the level-up counts as when it was noticed.
    unknown = [Reached(p.level, None, p.hi) for p in steady(45, 50, 100_000)]
    assert abs(forecast.forecast(50, unknown, NOW, 60).eta - tight.eta) < 3600


# ---- the posts -----------------------------------------------------------------------------------

def test_dates_are_a_range_in_the_bots_time_zone():
    f = forecast.Forecast(NOW + 5 * DAY, NOW + 4 * DAY, NOW + 8 * DAY)
    assert forecast.when_text(f, NOW, TZ) == "19 Jan – 23 Jan"
    assert forecast.when_text(forecast.Forecast(NOW + 60, NOW + 30, NOW + 90), NOW, TZ) == "15 Jan"
    assert forecast.when_text(forecast.Forecast(NOW, NOW, NOW + 360 * DAY), NOW, TZ) == "15 Jan – 10 Jan 2028"


def chars_and_history():
    chars = [roster.Character("Thorn Gale", 60, "WARRIOR", "Officer"),
             roster.Character("Ilsa Marrow", 58, "WARLOCK", "Raider"),
             roster.Character("Bran Holloway", 31, "MAGE", "Raider"),
             roster.Character("Vespera Ashward", 20, "DRUID", "Raider"),
             roster.Character("Kadmai Bank", 44, "HUNTER", "Alt"),
             roster.Character("Pip Newly", 25, "PRIEST", "Trial"),
             roster.Character("Tiny Alt", 5, "ROGUE", "Alt")]
    history = {"ilsa marrow": steady(50, 58, 150_000), "bran holloway": steady(25, 31, 45_000),
               "kadmai bank": steady(40, 44, 20_000), "pip newly": steady(20, 25, 50_000)}
    return chars, history


def test_the_board_lists_the_soonest_first():
    chars, history = chars_and_history()
    s = roster.Settings(on=True, channel_id=1, hidden_ranks=("Trial",))
    [(key, board)] = forecast.boards(chars, s, "Noctis", NOW, history, 60, TZ)
    assert key == "road" and board.title == "Noctis · Road to 60"
    assert "**1** at level 60" in board.description and "**3** on the way" in board.description
    assert "**0** quiet" in board.description and "**1** no history yet" in board.description
    assert f"<t:{NOW}:R>" in board.description
    names = [n for n, _, _ in board.fields]
    assert names == ["Within a week (1)", "Later (2)", "\N{SQUARED NEW} No history yet (1)"]
    assert all(not inline for _, _, inline in board.fields)
    assert board.fields[0][1].startswith("\N{LARGE GREEN CIRCLE} `58` **Ilsa Marrow** · ")  # eight level-ups, a minute each
    assert board.fields[1][1].index("Bran Holloway") < board.fields[1][1].index("Kadmai Bank")
    assert board.fields[2][1] == "Vespera Ashward 20"
    assert "Pip Newly" not in board.text() and "Tiny Alt" not in board.text()  # a hidden rank; below level 10
    # The same input in another order: the same post.
    again = forecast.boards(chars[::-1], s, "Noctis", NOW, history, 60, TZ)
    assert again[0][1].digest() == board.digest()
    # Two weeks and a day on, nobody has levelled: they're quiet, and Vespera still has no history.
    [(_, later)] = forecast.boards(chars, s, "Noctis", NOW + 15 * DAY, history, 60, TZ)
    assert [n for n, _, _ in later.fields] == ["\N{SLEEPING SYMBOL} Quiet (3)", "\N{SQUARED NEW} No history yet (1)"]
    assert later.fields[0][1] == "Ilsa Marrow 58, Kadmai Bank 44, Bran Holloway 31"


def test_each_name_follows_its_class_icon():
    chars, history = chars_and_history()
    s = roster.Settings(on=True, channel_id=1, hidden_ranks=("Trial",))
    icons = {"WARLOCK": "<:class_warlock:11>", "DRUID": "<:class_druid:12>"}
    [(_, board)] = forecast.boards(chars, s, "Noctis", NOW, history, 60, TZ, icons)
    assert board.fields[0][1].startswith("🟢 `58` <:class_warlock:11> **Ilsa Marrow** · ")
    assert "`31` **Bran Holloway** · " in board.fields[1][1]  # no emoji for mages yet: the name alone
    assert board.fields[2][1] == "<:class_druid:12> Vespera Ashward 20"
    [(_, plain)] = forecast.boards(chars, s, "Noctis", NOW, history, 60, TZ)
    assert plain.digest() != board.digest()  # an emoji made later edits the post


def test_how_much_there_was_to_go_on():
    def quality(history, level=50):
        return forecast.forecast(level, history, NOW, 60).quality
    assert quality(steady(44, 50, 100_000)) == forecast.GOOD
    # The same level-ups from an older companion: how closely they were timed isn't known.
    assert quality([Reached(p.level, None, p.hi) for p in steady(44, 50, 100_000)]) == forecast.FAIR
    assert quality(steady(47, 50, 100_000)) == forecast.FAIR                        # two level-ups measured
    assert quality(steady(44, 50, 100_000, read_gap=20 * 3600)) == forecast.FAIR    # noticed most of a day late
    assert quality(steady(48, 50, 60_000)) == forecast.THIN                         # one level-up measured
    assert quality(steady(46, 50, 100_000, read_gap=40 * 3600)) == forecast.THIN    # noticed days late
    # Why there's no forecast: nothing seen, one sighting, or level-ups all noticed in one read are "new".
    assert forecast.why_not(30, [], NOW) == forecast.UNSEEN
    assert forecast.why_not(30, [Reached(30, None, NOW - DAY)], NOW) == forecast.UNSEEN
    assert forecast.why_not(31, [Reached(30, None, NOW - DAY), Reached(31, None, NOW - DAY)], NOW) == forecast.UNSEEN
    assert forecast.why_not(50, steady(44, 50, 100_000, now=NOW - 20 * DAY), NOW) == forecast.QUIET


def test_the_rosters_alt_ranks_are_left_out():
    chars, history = chars_and_history()
    s = roster.Settings(on=True, channel_id=1, alt_ranks=("Alt",))
    [(key, board)] = forecast.boards(chars, s, "Noctis", NOW, history, 60, TZ)
    assert key == "road" and board.title == "Noctis · Road to 60"
    assert "Kadmai Bank" not in board.text() and "**3** on the way" in board.description  # Ilsa, Bran, Pip


def test_before_any_roster_read_nobody_has_an_estimate():
    chars, history = chars_and_history()
    [(_, board)] = forecast.boards(chars, roster.Settings(), "Noctis", None, history, 60, TZ)
    assert "waiting for an officer's roster" in board.description and "**0** on the way" in board.description


def test_a_long_forecast_stays_within_discords_limits():
    chars = [roster.Character(f"Warrior{i:03d} Withaverylongsurname", 50, "WARRIOR", "Raider") for i in range(300)]
    history = {c.name.casefold(): steady(45, 50, 50_000 + i * 500) for i, c in enumerate(chars)}
    result = forecast.boards(chars + [roster.Character(f"Quiet{i:03d} Withaverylongsurname", 30) for i in range(200)],
                             roster.Settings(), "Noctis", NOW, history, 60, TZ)
    assert [k for k, _ in result][:2] == ["road", "road#2"]
    for _, b in result:
        assert b.size() <= roster.EMBED_LIMIT and len(b.fields) <= roster.FIELDS_LIMIT
        assert all(roster.text_length(v) <= roster.FIELD_VALUE_LIMIT for _, v, _ in b.fields)
    assert "more" in result[-1][1].fields[-1][1]  # the quiet ones are cut short, with how many are left out
    assert sum(b.text().count("**Warrior") for _, b in result) == 300


# ---- the store -----------------------------------------------------------------------------------

def body(members, scanned, levels=()) -> dict:
    return {"uploader": "Kadmai Moonwhisper", "guild": "Noctis", "realm": "Forever", "scanned": scanned,
            "members": [{"name": n, "level": lv, "class": c, "rank": r, "seen": scanned} for n, lv, c, r in members],
            "levels": [{"name": n, "from": f, "to": t, "at": at, **({"since": since} if since is not None else {})}
                       for n, f, t, at, since in levels]}


def apply(store, members, scanned, levels=()):
    return store.apply_milestones(parse_milestone_upload(body(members, scanned, levels)), "Kadmai")


def test_level_ups_are_kept_and_narrowed_by_every_upload(store, clock):
    store.set_milestone_settings(on=True, guild="Noctis", channel_id=20)
    t = int(clock()) - DAY
    bran = [("Bran Holloway", 33, "MAGE", "Raider")]
    # Kadmai was away for hours: 30 to 33 in one read. An old companion: no `since`.
    apply(store, bran, t, [("Bran Holloway", 30, 33, t, None)])
    assert store.level_history() == {"bran holloway": [Reached(31, None, t), Reached(32, None, t), Reached(33, None, t)]}
    # Seren was online: she saw 31 hours earlier, and 32 and 33 within a minute each.
    apply(store, bran, t, [("Bran Holloway", 30, 31, t - 7200, t - 7260), ("Bran Holloway", 31, 32, t - 3600, t - 3660),
                           ("Bran Holloway", 32, 33, t - 600, t - 660)])
    assert store.level_history()["bran holloway"] == [
        Reached(31, t - 7260, t - 7200), Reached(32, t - 3660, t - 3600), Reached(33, t - 660, t - 600)]
    # Kadmai's file again, now with `since` from the day before: nothing gets wider.
    gen = store.roster_dirty()
    apply(store, bran, t, [("Bran Holloway", 30, 33, t, t - DAY)])
    assert store.level_history()["bran holloway"][0] == Reached(31, t - 7260, t - 7200)
    assert store.roster_dirty() == gen  # and nothing to post again
    # A `since` after the level-up was noticed (clocks) isn't believed past it; times from the future are now.
    now = int(clock())
    apply(store, bran, t, [("Bran Holloway", 33, 34, now + 500, now + 400)])
    assert store.level_history()["bran holloway"][-1] == Reached(34, now, now)


def test_a_new_level_up_marks_the_posts_dirty(store, clock):
    store.set_milestone_settings(on=True, guild="Noctis", channel_id=20)
    t = int(clock()) - 3600
    apply(store, [("Bran Holloway", 31, "MAGE", "Raider")], t)
    store.clear_roster_dirty(store.roster_dirty())
    apply(store, [("Bran Holloway", 31, "MAGE", "Raider")], t, [("Bran Holloway", 30, 31, t - 60, t - 120)])
    assert store.roster_dirty() > 0


def test_forecast_settings_keep_what_isnt_changed(store):
    s = store.forecast_settings()
    assert (s.on, s.channel_id, s.ready) == (False, None, False)
    s = store.set_forecast_settings(channel_id=ROAD_CHANNEL)
    assert (s.on, s.channel_id) == (False, ROAD_CHANNEL)
    assert store.set_forecast_settings(on=True).ready
    assert store.set_forecast_settings(on=False).channel_id == ROAD_CHANNEL
    assert "Road to max level: **Off**" in forecast.settings_text(s, None, 0, True)
    on = forecast.Settings(on=True)
    assert "not posting until the channel is set and level milestones are on" in forecast.settings_text(on, None, 0, False)
    assert "Road to max level: **On**." in forecast.settings_text(forecast.Settings(True, 1), "<#1>", 3, True)


# ---- the poster ----------------------------------------------------------------------------------

MEMBERS = [("Thorn Gale", 60, "WARRIOR", "Officer"), ("Ilsa Marrow", 58, "WARLOCK", "Raider"),
           ("Vespera Ashward", 20, "DRUID", "Raider")]


def level_ups(name: str, start: int, end: int, per_day: float, now: int) -> list[tuple]:
    return [(name, p.level - 1, p.level, p.hi, p.lo) for p in steady(start, end, per_day, now=now)]


async def test_the_forecast_has_its_own_channel_beside_the_roster(tmp_path):
    channels = {ROAD_CHANNEL: FakeChannel(ROAD_CHANNEL), ROSTER_CHANNEL: FakeChannel(ROSTER_CHANNEL)}
    bot = make_bot(tmp_path, channels)
    bot.store._clock = Clock(RAID)
    bot.store.set_milestone_settings(on=True, guild="Noctis", channel_id=20)
    bot.store.set_roster_settings(on=True, channel_id=ROSTER_CHANNEL)
    bot.store.set_forecast_settings(on=True, channel_id=ROAD_CHANNEL)
    now = bot.store.now()
    apply(bot.store, MEMBERS, now, level_ups("Ilsa Marrow", 52, 58, 150_000, now))
    await bot.sync_pending()
    road, ros = channels[ROAD_CHANNEL], channels[ROSTER_CHANNEL]
    assert road.sends == 1 and ros.sends == 1
    assert [p.key for p in bot.store.roster_posts("road")] == ["road"]
    assert [p.key for p in bot.store.roster_posts()] == ["roster"]
    [msg] = road.messages.values()
    assert msg["embed"].title == "Noctis · Road to 60"
    assert "`58` **Ilsa Marrow**" in text(msg) and "Vespera Ashward 20" in text(msg)
    assert "Road to 60" not in text(next(iter(ros.messages.values())))

    # Nothing changed: nothing sent or edited, even after a restart.
    bot2 = make_bot(tmp_path, channels)
    bot2.store._clock = bot.store._clock
    bot2.store.mark_all_dirty()
    await bot2.sync_pending()
    assert (road.sends, road.edits, ros.sends, ros.edits) == (1, 0, 1, 0)

    # Vespera levels twice: the forecast's post is edited, and she has an estimate.
    bot2.store._clock.t += 3 * DAY
    later = bot2.store.now()
    apply(bot2.store, [m if m[0] != "Vespera Ashward" else ("Vespera Ashward", 22, "DRUID", "Raider") for m in MEMBERS],
          later, [("Vespera Ashward", 20, 21, later - 2 * DAY - 600, later - 2 * DAY - 660), ("Vespera Ashward", 21, 22, later - 60, later - 120)])
    await bot2.sync_pending()
    assert road.sends == 1 and road.edits == 1
    assert "`22` **Vespera Ashward** · " in text(next(iter(road.messages.values())))

    # Off: the roster carries on, the forecast's post stays as it is.
    bot2.store.set_forecast_settings(on=False)
    bot2.store._clock.t += 600
    apply(bot2.store, MEMBERS[:2], bot2.store.now())
    await bot2.sync_pending()
    assert road.edits == 1 and len(road.messages) == 1 and ros.edits >= 1


async def test_the_forecast_runs_without_the_roster_channel(tmp_path):
    channels = {ROAD_CHANNEL: FakeChannel(ROAD_CHANNEL)}
    bot = make_bot(tmp_path, channels)
    bot.store._clock = Clock(RAID)
    bot.store.set_milestone_settings(on=True, guild="Noctis", channel_id=20)
    bot.store.set_forecast_settings(on=True, channel_id=ROAD_CHANNEL)
    apply(bot.store, MEMBERS, bot.store.now())
    await bot.sync_pending()
    assert channels[ROAD_CHANNEL].sends == 1 and bot.store.roster_dirty() == 0
    # A deleted post is put back.
    channels[ROAD_CHANNEL].messages.clear()
    bot.store.set_forecast_settings(on=False)
    bot.store.set_forecast_settings(on=True)
    await bot.sync_pending()
    assert channels[ROAD_CHANNEL].sends == 2 and len(channels[ROAD_CHANNEL].messages) == 1
