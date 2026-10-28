"""/loot import's reading of pasted links and RCLootCouncil CSVs, and the store's side of it."""
from bot import importer
from bot.importer import OTHER_RAID, WOWHEAD, Found

from .conftest import link


def test_item_id_from_any_kind_of_reference():
    assert importer.item_id("https://www.wowhead.com/forever/item=873/staff-of-jordan") == 873
    assert importer.item_id("wowhead.com/classic/item=16805/felheart-gloves#comments") == 16805
    assert importer.item_id("https://www.wowhead.com/item=19019") == 19019
    assert importer.item_id(link(18000, "Sash of the Unseen")) == 18000
    assert importer.item_id(" 17076 ") == 17076
    for bad in ("", "0", "Staff of Jordan", "https://www.wowhead.com/forever/npc=12118/lucifron", "12.5"):
        assert importer.item_id(bad) is None, bad


def test_pasted_links_and_ids():
    text = (f"https://www.wowhead.com/forever/item=873/staff-of-jordan, 16805\n{link(18000, 'Sash of the Unseen')} "
            "and https://www.wowhead.com/forever/item=873/staff-of-jordan again")
    parsed = importer.parse(text)
    assert parsed.origin == WOWHEAD
    assert parsed.items == [Found(18000, "Sash of the Unseen"), Found(873), Found(16805)]
    assert parsed.unread == 2  # "and", "again"


# RCLootCouncil's export header (as our addon's /nlc export writes it) and two guilds' worth of rows.
HEADER = ("player,date,time,id,item,itemID,itemString,response,votes,class,instance,boss,difficultyID,mapID,"
          "groupSize,gear1,gear2,responseID,isAwardReason,subType,equipLoc,note,owner")


def row(item, item_id, instance="Molten Core", boss="Lucifron", player="Somebody"):
    return (f"{player},2026/10/26,21:05:00,1-1,{item},{item_id},item:{item_id},Main spec,,MAGE,{instance},{boss},"
            ",,,,,1,false,Cloth,INVTYPE_FEET,,Them")


def test_rclootcouncil_csv():
    text = "﻿" + "\n".join([
        HEADER,
        row(link(16800, "Arcanist Boots"), 16800),
        row("[Felheart Gloves]", 16805, boss=""),
        row("[Felheart Gloves]", 16805, boss="Lucifron"),  # a later row knows the boss
        row('"[Sulfuras, Hand of Ragnaros]"', 17182, boss="Ragnaros"),
        row("", "", boss="nobody"),
    ]) + "\n"
    parsed = importer.parse(text)
    assert parsed.origin == OTHER_RAID and parsed.unread == 1
    assert parsed.items == [Found(16800, "Arcanist Boots", "Molten Core, Lucifron"),
                            Found(16805, "Felheart Gloves", "Molten Core, Lucifron"),
                            Found(17182, "Sulfuras, Hand of Ragnaros", "Molten Core, Ragnaros")]


def test_import_adds_new_items_and_only_fills_missing_sources(store):
    store.add_item(16805, "Felheart Gloves")
    store.add_item(16800, "Arcanist Boots", source="Molten Core, typed by an officer")
    added, filled = store.import_items([(873, "Staff of Jordan", None, 4), (16805, "Felheart Gloves", "MC, Lucifron", None),
                                        (16800, "Arcanist Boots", "MC, Lucifron", None)], OTHER_RAID, by="Seren")
    assert (added, filled) == (1, 1)
    staff = store.item_state(873)
    assert (staff.origin, staff.quality, staff.dropped) == (OTHER_RAID, 4, False)
    assert store.item_state(16805).source_text == "MC, Lucifron"
    assert store.item_state(16800).source_text == "Molten Core, typed by an officer"
    assert store.item_state(16805).origin is None  # was on the list before: not "found elsewhere"
