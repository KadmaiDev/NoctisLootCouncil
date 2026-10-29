import dataclasses

from bot import render
from bot.model import AwardInfo, ItemState, LogGroup
from bot.rules import COUNCIL, ROLL, Vote, tally

from .conftest import RAID, TZ


def state(**kw) -> ItemState:
    base = dict(id=18000, name="Sash of the Unseen", quality=4, slot="Waist · Cloth",
                source_text="Molten Core, Gehennas", raid="Molten Core", created_at=RAID + 4 * 3600)
    base.update(kw)
    return ItemState(**base)


def dropped(**kw) -> ItemState:
    """An item that has dropped for us (one that hasn't is behind a spoiler on the public posts)."""
    return state(drops=1, **kw)


def votes(*pairs) -> list[Vote]:
    return [Vote(i, name, choice, i) for i, (name, choice) in enumerate(pairs)]


MOCKUP_VOTES = votes(("Seren", COUNCIL), ("Doran", COUNCIL), ("Lyra", ROLL), ("Kadmai", COUNCIL))


def test_officer_card_matches_mockup():
    s = state(tally=tally(MOCKUP_VOTES, 3), decision=COUNCIL, priority="Warlock priority", priority_by="Seren",
              suggestions=6)
    card = render.officer_card(s, TZ)
    assert card.title == "Sash of the Unseen"
    assert card.subtitle == "Epic · Waist · Cloth · Molten Core, Gehennas"
    assert card.colour == 0xA335EE
    assert card.kicker == ""
    assert card.body.splitlines() == [
        "✅ **Council item**, decided 3 of 4. In game after the next /reload.",
        "**Votes:** Council 3 · Roll 1",
        "-# Council: Seren, Doran, Kadmai · Roll: Lyra",
        "**Priority:** Warlock priority",
        "-# Set by Seren",
    ]
    assert card.footer == "No drops yet\n6 raiders suggest council in #loot-items"  # from before names were kept
    assert [b.label for b in card.buttons] == ["Council", "Roll", "Set priority"]


def test_officer_card_names_the_raiders_who_suggested_council():
    card = render.officer_card(state(suggestions=3, suggested_by=("Ilsa", "Vespera_x")), TZ)
    assert card.footer.splitlines()[1] == "Suggested for council by Ilsa, Vespera\\_x and 1 more"
    names = tuple(f"Raider{i}" for i in range(20))
    card = render.officer_card(state(suggestions=20, suggested_by=names), TZ)
    assert card.footer.splitlines()[1].endswith("Raider14 and 5 more")
    assert "Ilsa" not in render.items_card(state(suggestions=3, suggested_by=("Ilsa",)), TZ).text()


def test_officer_card_new_in_raid():
    award = AwardInfo(item_id=16805, item_name="Felheart Gloves", who="Corvin Dusk", how="ms", at=RAID + 1000,
                      roll=77, nms=4, nos=1)
    s = state(id=16805, name="Felheart Gloves", slot="Hands · Cloth", source_text="Molten Core, Lucifron",
              new_in_raid=True, drops=1, first_drop_at=RAID + 900, last_drop_at=RAID + 900, first_award=award,
              suggestions=2, suggested_by=("Ilsa", "Vespera"))
    card = render.officer_card(s, TZ)
    assert card.kicker == "NEW IN OUR RAID LAST NIGHT"
    assert card.body.splitlines() == [
        "Rolled, won by Corvin Dusk (main spec, 77)",
        "-# Wanted it: 4 main spec, 1 off spec",
        "**Votes:** none yet",
    ]
    assert card.footer == "Dropped once, last Mon 26 Oct\nSuggested for council by Ilsa, Vespera"


def test_new_in_raid_posted_days_later_names_the_day():
    s = state(new_in_raid=True, drops=1, first_drop_at=RAID, last_drop_at=RAID, created_at=RAID + 3 * 86400)
    assert render.officer_card(s, TZ).kicker == "NEW IN OUR RAID ON MONDAY 26 OCT"


def test_officer_card_in_game_decision():
    s = state(game_handling=ROLL, game_note="tanks first", game_by="Kadmai Moonwhisper")
    body = render.officer_card(s, TZ).body.splitlines()
    assert body[0] == "Set in game by Kadmai Moonwhisper: **roll item**. A vote here replaces it."
    assert body[-2:] == ["**Priority:** tanks first", "-# Set in game by Kadmai Moonwhisper"]


def test_officer_card_without_details_stays_short():
    card = render.officer_card(state(quality=None, slot=None, source_text=None), TZ)
    assert (card.subtitle, card.body, card.footer) == ("", "**Votes:** none yet", "No drops yet")
    assert card.colour == render.DEFAULT_COLOUR


def test_items_card_council():
    s = state(tally=tally(MOCKUP_VOTES, 3), decision=COUNCIL, priority="Warlock priority")
    card = render.items_card(s, TZ)
    assert card.subtitle == "Epic · Waist · Cloth · Molten Core, Gehennas"
    assert card.body == "**Council item**\n**Priority:** Warlock priority"  # labelled as on the officer post
    assert card.footer == "Decided by the officers, 3 of 4."
    assert card.buttons == []  # council items show no button


def test_items_card_undecided_new_item():
    s = state(id=16805, name="Felheart Gloves", slot="Hands · Cloth", source_text="Molten Core, Lucifron",
              new_in_raid=True, drops=1, first_drop_at=RAID + 900, suggestions=2)
    card = render.items_card(s, TZ)
    assert card.body == "**Undecided**"
    assert card.footer == "First seen last night.\nRolled until the officers decide."
    assert [b.label for b in card.buttons] == ["Suggest for council · 2"]


def test_items_card_roll_item():
    s = state(name="Robe of Volatile Power", quality=3, tally=tally(votes(("A", ROLL), ("B", ROLL), ("C", ROLL)), 3),
              decision=ROLL)
    card = render.items_card(s, TZ)
    assert card.body == "**Roll item**"
    assert card.footer == "Main spec, then second main spec, then off spec.\nDecided by the officers, 3 of 3."
    assert card.subtitle.startswith("Rare · ")
    assert card.colour == 0x0070DD
    assert [b.label for b in card.buttons] == ["Suggest for council · 0"]


def test_card_text_puts_small_lines_around_the_heading():
    card = render.Card(title="Felheart Gloves", colour=0, kicker="NEW IN OUR RAID LAST NIGHT", subtitle="Epic",
                       body="**Votes:** none yet", footer="one\ntwo")
    assert card.text().splitlines() == ["-# NEW IN OUR RAID LAST NIGHT", "### Felheart Gloves", "-# Epic",
                                        "**Votes:** none yet", "-# one", "-# two"]


def test_layout_spaces_the_footer_from_the_body():
    import discord

    from bot.views import card_layout
    card = render.officer_card(state(priority="Warlock priority", priority_by="Seren", suggestions=1), TZ)
    box = card_layout(card, 18000).children[0]
    kinds = [(type(c).__name__, getattr(c, "visible", None)) for c in box.children]
    assert kinds == [("MediaGallery", None), ("TextDisplay", None), ("Separator", True), ("TextDisplay", None),
                     ("Separator", False), ("TextDisplay", None)]
    assert box.children[0].items[0].media.url == "attachment://title.png"
    assert box.children[0].items[0].description == "Sash of the Unseen"
    # Without a known quality there's no colour to draw in: the plain heading.
    plain = card_layout(render.officer_card(state(quality=None), TZ), 18000).children[0]
    assert plain.children[0].content.startswith("### Sash of the Unseen")
    assert box.children[-1].content.startswith("-# No drops yet")
    assert isinstance(box, discord.ui.Container)
    assert not box.children[0].items[0].spoiler


def test_public_post_hides_an_item_that_hasnt_dropped_for_us():
    from bot.views import card_layout
    s = state(origin="wowhead", wowhead=("forever", "Sash of the Unseen"), emoji="<:e:1>")
    card = render.items_card(s, TZ)
    assert card.spoiler and card.kicker == "NOT DROPPED FOR US YET · SPOTTED ON WOWHEAD"
    assert card.head() == (
        "-# NOT DROPPED FOR US YET · SPOTTED ON WOWHEAD\n### ||<:e:1> Sash of the Unseen||\n"
        "-# ||Epic · Waist · Cloth · Molten Core, Gehennas · "
        "[Wowhead](https://www.wowhead.com/forever/item=18000/sash-of-the-unseen)||")
    box = card_layout(card, 18000).children[0]
    assert [type(c).__name__ for c in box.children[:3]] == ["TextDisplay", "MediaGallery", "TextDisplay"]
    assert box.children[1].items[0].spoiler  # the drawn name, blurred until tapped
    # The officers see it plainly, with where it was found.
    officer = render.officer_card(s, TZ)
    assert not officer.spoiler and officer.footer == "Not dropped for us yet · spotted on Wowhead"
    assert render.officer_card(state(origin="other_raid"), TZ).footer == \
        "Not dropped for us yet · seen in another guild's raid"
    # Once it drops for us, nothing is hidden.
    shown = render.items_card(dataclasses.replace(s, drops=1), TZ)
    assert not shown.spoiler and shown.kicker == ""


def test_card_digest_changes_with_content():
    a = render.items_card(state(), TZ)
    assert a.digest() == render.items_card(state(), TZ).digest()
    assert a.digest() != render.items_card(state(suggestions=1), TZ).digest()


def test_suggestion_replies():
    assert render.suggestion_reply(True, 3) == ("Thanks, that's 3 suggestions. The officers see who suggested it "
                                                "when they decide.")
    assert render.suggestion_reply(False, 1) == "Taken back. That leaves 1 suggestion."


def aw(name, who, how, roll=None, note=None, nms=None, nos=None, new=False) -> AwardInfo:
    return AwardInfo(item_id=1, item_name=name, who=who, how=how, at=RAID, roll=roll, note=note, nms=nms, nos=nos,
                     new_item=new)


def test_log_post_matches_mockup():
    group = LogGroup("Molten Core", "2026-10-26", [
        aw("Choker of Enlightenment", "Vespera Ashward", "ms", 91, nms=3, nos=0),
        aw("Sash of the Unseen", "Ilsa Marrow", "council",
           note='council vote, 3 of 4: biggest upgrade, less loot so far; bid: BIS "first upgrade in weeks"'),
        aw("Felheart Gloves", "Corvin Dusk", "ms", 77, nms=4, nos=1, new=True),
        aw("Helm of Might", "Tarnia Moonwhisper", "ms", 90),
        aw("Robe of Volatile Power", "Bran Holloway", "os", 64),
        aw("Onslaught Girdle", "Doran Pike", "ms2", 58, nms=1, nos=0),
    ])
    [card] = render.log_cards(group)
    assert (card.title, card.subtitle, card.footer) == ("Molten Core · Monday 26 Oct", "6 items", render.LOG_FOOTER)
    assert card.body.splitlines() == [
        "Choker of Enlightenment → **Vespera Ashward** · main-spec roll, 91",
        "Sash of the Unseen → **Ilsa Marrow** · council, 3 of 4 votes · biggest upgrade, less loot so far",
        '-# bid: BIS "first upgrade in weeks"',
        "Felheart Gloves → **Corvin Dusk** · main-spec roll, 77 · new item",
        "Helm of Might → **Tarnia Moonwhisper** · main-spec roll, 90",
        "Robe of Volatile Power → **Bran Holloway** · off-spec roll, 64",
        "Onslaught Girdle → **Doran Pike** · second main-spec roll, 58 (nobody else wanted it)",
    ]


def test_long_log_is_split_without_breaking_lines():
    group = LogGroup("Molten Core", "2026-10-26", [aw(f"Item number {i:03}", "Somebody Longname", "ms", 50)
                                                   for i in range(200)])
    parts = render.log_cards(group)
    assert len(parts) > 1
    assert all(len(p.text()) <= 4000 for p in parts)
    assert (parts[0].title, parts[0].subtitle) == ("Molten Core · Monday 26 Oct", "200 items")
    assert parts[1].title == "Molten Core · Monday 26 Oct (continued)" and parts[1].subtitle == ""
    assert [bool(p.footer) for p in parts] == [False] * (len(parts) - 1) + [True]
    assert sum(p.body.count(" → ") for p in parts) == 200


def test_log_post_by_boss_with_links_and_council_decisions():
    def at(a, boss, minutes, url=None):
        return dataclasses.replace(a, boss=boss, at=RAID + 60 * minutes, url=url)
    group = LogGroup("Molten Core", "2026-10-26", [
        at(aw("Band of Accuria", "Doran Pike", "council", note="the only main-spec bid"), "Ragnaros", 200),
        at(aw("Arcanist Boots", "Ilsa Marrow", "ms", 88), "Lucifron", 10,
           "https://www.wowhead.com/forever/item=16800/arcanist-boots"),
        at(aw("Lava Core", "Bran Holloway", "os", 12), None, 5),
        at(aw("Striker's Mark", "Brannoc Vale", "council", note="roll-off after a split vote, 87; bid: Big upgrade"),
           "Magmadar", 40),
        at(aw("Felheart Gloves", "Corvin Dusk", "ms", 77), "Lucifron", 11),
    ])
    [card] = render.log_cards(group)
    assert card.body.splitlines() == [
        "__Lucifron__",
        "[Arcanist Boots](https://www.wowhead.com/forever/item=16800/arcanist-boots) → **Ilsa Marrow** · "
        "main-spec roll, 88",
        "Felheart Gloves → **Corvin Dusk** · main-spec roll, 77",
        "",
        "__Magmadar__",
        "Striker's Mark → **Brannoc Vale** · council · roll-off after a split vote, 87",
        "-# bid: Big upgrade",
        "",
        "__Ragnaros__",
        "Band of Accuria → **Doran Pike** · council · the only main-spec bid",
        "",
        "__Other loot__",
        "Lava Core → **Bran Holloway** · off-spec roll, 12",
    ]


def test_council_vote_lines():
    def line(note):
        return render.award_line(aw("Sash", "Ilsa", "council", note=note))
    assert line("council vote, 2 of 3: class fit") == "Sash → **Ilsa** · council, 2 of 3 votes · class fit"
    assert line("council vote, 2 of 3") == "Sash → **Ilsa** · council, 2 of 3 votes"  # from before reasons
    assert line("Ilsa won the last one; Warlock priority") == "Sash → **Ilsa** · council · Ilsa won the last one; Warlock priority"
    assert line(None) == "Sash → **Ilsa** · council"


def test_markdown_in_player_text_is_escaped():
    line = render.award_line(aw("Sash", "Ilsa", "council", note="*best* upgrade"))
    assert "council · \\*best\\* upgrade" in line


def test_priorities_post_for_one_raid():
    states = [
        dropped(name="Sash of the Unseen", decision=COUNCIL, priority="Warlock priority"),
        dropped(id=2, name="Onslaught Girdle", decision=COUNCIL, priority="tanks first"),
        dropped(id=3, name="Robe of Volatile Power", decision=ROLL),
        dropped(id=4, name="Head of Onyxia", decision=COUNCIL, raid="Onyxia's Lair"),
    ]
    [card] = render.priorities_cards(states, "Thursday 29 Oct", "Molten Core")
    assert (card.title, card.subtitle) == ("Molten Core · Thursday 29 Oct", "Council items")
    assert card.body.splitlines() == [
        "- **Onslaught Girdle** · tanks first",
        "- **Sash of the Unseen** · Warlock priority",
        "",
        render.EVERYTHING_ELSE,
    ]
    assert card.footer == "Think something should be a council item? Press Suggest for council on its post in #loot-items."


def test_priorities_post_all_raids_grouped():
    states = [dropped(name="Sash", decision=COUNCIL), dropped(id=4, name="Head of Onyxia", game_handling=COUNCIL,
                                                          raid="Onyxia's Lair"),
              dropped(id=5, name="Mystery", decision=COUNCIL, raid=None)]
    [card] = render.priorities_cards(states, "Thursday 29 Oct")
    assert card.title == "Thursday 29 Oct"
    assert card.body.splitlines()[:6] == ["__Molten Core__", "- **Sash**", "__Onyxia's Lair__", "- **Head of Onyxia**",
                                          "__Other__", "- **Mystery**"]


def test_priorities_link_to_wowhead():
    states = [dropped(id=873, name="Staff of Jordan", decision=COUNCIL, priority="Casters",
                    wowhead=("forever", "Staff of Jordan"), emoji="<:inv_staff_13:42>")]
    [card] = render.priorities_cards(states, "Thursday 29 Oct", "Molten Core")
    assert card.body.splitlines()[0] == \
        "- <:inv_staff_13:42> **[Staff of Jordan](https://www.wowhead.com/forever/item=873/staff-of-jordan)** · Casters"


def test_status_text():
    states = [state(decision=COUNCIL, priority="Warlock priority"), state(id=2, name="Robe", decision=ROLL),
              state(id=3, name="Gloves")]
    text = render.status_text(states)
    assert "• Sash of the Unseen (Molten Core) · Warlock priority" in text
    assert "**Roll items:** 1" in text
    assert "**Undecided:** 1" in text
    assert render.item_status(states[2]) == "**Gloves**: undecided, rolled until the officers decide."
    assert render.item_status(state(game_handling=ROLL, game_by="Kadmai", suggestions=2)) == (
        "**Sash of the Unseen**: roll item (set in game by Kadmai). 2 raiders suggest council.")
