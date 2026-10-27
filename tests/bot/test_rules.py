import datetime as dt

from bot import rules
from bot.rules import COUNCIL, ROLL, Vote

from .conftest import RAID, TZ


def v(uid: int, choice: str, at: int = 0, name: str | None = None) -> Vote:
    return Vote(uid, name or f"Officer{uid}", choice, at)


def test_tally_needs_threshold():
    t = rules.tally([v(1, COUNCIL, 1), v(2, COUNCIL, 2), v(3, ROLL, 3)], needed=3)
    assert t.decided is None
    assert (len(t.council), len(t.roll), t.total) == (2, 1, 3)


def test_tally_decides_at_threshold_and_keeps_vote_order():
    t = rules.tally([v(1, COUNCIL, 1, "Seren"), v(2, COUNCIL, 2, "Doran"), v(4, ROLL, 3, "Lyra"),
                     v(3, COUNCIL, 4, "Kadmai")], needed=3)
    assert t.decided == COUNCIL
    assert t.council == ["Seren", "Doran", "Kadmai"]
    assert t.roll == ["Lyra"]
    assert (t.count(COUNCIL), t.total) == (3, 4)


def test_tally_one_vote_per_officer_latest_wins():
    t = rules.tally([v(1, COUNCIL, 1), v(1, ROLL, 5), v(2, ROLL, 2), v(3, ROLL, 3)], needed=3)
    assert t.decided == ROLL
    assert t.total == 3


def test_tally_tie_above_threshold_is_undecided():
    votes = [v(i, COUNCIL, i) for i in range(3)] + [v(10 + i, ROLL, 10 + i) for i in range(3)]
    t = rules.tally(votes, needed=3)
    assert t.decided is None
    assert t.tied_at_threshold


def test_drop_key_buckets_half_hours():
    base = 1793046600 - 1793046600 % 1800
    assert rules.drop_key(1, "e663", base) == rules.drop_key(1, "e663", base + 1799)
    assert rules.drop_key(1, "e663", base) != rules.drop_key(1, "e663", base + 1800)
    assert rules.drop_key(1, None, base) == (1, "", base // 1800)


def test_award_key_ignores_case():
    assert rules.award_key("Ilsa Marrow", 1, 5) == rules.award_key("ilsa marrow ", 1, 5)


def test_merge_sources_takes_largest_count():
    assert rules.merge_sources({"e1": 2, "e2": 1}, {"e1": 1, "e3": 4}) == {"e1": 2, "e2": 1, "e3": 4}


def test_better_link_prefers_full_link():
    full = "|cffa335ee|Hitem:18000::|h[Sash]|h|r"
    assert rules.better_link(full, "item:18000") == full
    assert rules.better_link("item:18000", full) == full
    assert rules.better_link(None, "item:1") == "item:1"
    assert rules.better_link(full, None) == full


def test_night_runs_past_midnight():
    assert rules.night_of(RAID, TZ) == dt.date(2026, 10, 26)
    assert rules.night_of(RAID + 5 * 3600, TZ) == dt.date(2026, 10, 26)  # 01:30
    assert rules.night_of(RAID + 10 * 3600, TZ) == dt.date(2026, 10, 27)  # 06:30


def test_day_labels():
    assert rules.day_label(dt.date(2026, 10, 26)) == "Monday 26 Oct"
    assert rules.short_day_label(dt.date(2026, 10, 26)) == "Mon 26 Oct"
