"""The real bot (discord.py, slash commands, buttons, the form) against the fake Discord."""
from __future__ import annotations

import dataclasses

from bot.iteminfo import ItemInfo
from bot.upload import parse_upload
from bot.warcraftlogs import Fight, Report
from harness.fake_discord import FileUpload

from ..bot.conftest import RAID, sample_body
from .conftest import start_bot, stop_bot

SASH = dict(item="18000", name="Sash of the Unseen", slot="Waist · Cloth", source="Molten Core, Lucifron")


async def add_sash(guild):
    await guild.slash(guild.officers[0], "loot add", **SASH)
    officer = await guild.wait_until(lambda: guild.channel("loot-officers").find("Sash of the Unseen"))
    items = await guild.wait_until(lambda: guild.channel("loot-items").find("Sash of the Unseen"))
    return officer, items


async def test_loot_add_posts_to_both_channels(guild, running):
    r = await guild.slash(guild.officers[0], "loot add", **SASH)
    assert r.ephemeral
    officer, items = await add_sash(guild)
    assert officer.thread is None  # officers start one themselves if an item needs discussing
    assert officer.button_labels == ["Council", "Roll", "Set priority"]
    # The name is drawn in the quality colour and uploaded with the post.
    assert "[image: Sash of the Unseen]\n-# Epic · Waist · Cloth · Molten Core, Lucifron" in officer.text
    assert officer.attachments == ["title.png"] and items.attachments == ["title.png"]
    assert officer.components[0]["accent_color"] == 0xA335EE  # /loot add assumes epic
    assert items.thread is None
    assert items.button_labels == ["Suggest for council · 0"]
    # It hasn't dropped for us: on the public post it's behind a spoiler.
    assert ("-# NOT DROPPED FOR US YET\n[spoiler image: Sash of the Unseen]\n"
            "-# ||Epic · Waist · Cloth · Molten Core, Lucifron||") in items.text
    # Using it again updates the posts instead of adding new ones.
    await guild.slash(guild.officers[0], "loot add", **dict(SASH, name="Sash of the Unseen Eye"))
    await guild.wait_until(lambda: "Unseen Eye" in officer.text, what="the officer post to be edited")
    await guild.quiet()
    assert len(guild.channel("loot-officers").posts) == 1 and len(guild.channel("loot-items").posts) == 1


async def test_raiders_cant_use_officer_commands_or_buttons(guild, running):
    officer, _ = await add_sash(guild)
    ilsa = guild.raiders[0]
    r = await guild.slash(ilsa, "loot add", item="1", name="Nope")
    assert r.ephemeral and "officers" in r.text
    r = await guild.click(ilsa, officer, "Council")
    assert r.ephemeral and "Only officers" in r.text
    r = await guild.slash(ilsa, "loot token")
    assert "officers" in r.text


async def test_three_council_votes_decide_and_the_posts_follow(guild, running):
    officer, items = await add_sash(guild)
    seren, doran, kadmai = guild.officers
    r = await guild.click(seren, officer, "Council")
    assert r.ephemeral and "Council 1 · Roll 0" in r.text
    await guild.click(doran, officer, "Council")
    r = await guild.click(kadmai, officer, "Council")
    assert "Decided: council item" in r.text
    await guild.wait_until(lambda: "Suggest for council" not in " ".join(items.button_labels),
                           what="the public post to drop its Suggest button")
    # Changing a vote undoes it.
    r = await guild.click(kadmai, officer, "Roll")
    assert "Council 2 · Roll 1" in r.text and "Decided" not in r.text
    assert running.bot.store.decisions()["items"]["18000"]["handling"] == "none"


async def test_priority_form(guild, running):
    officer, items = await add_sash(guild)
    seren = guild.officers[0]
    opened = await guild.click(seren, officer, "Set priority")
    assert opened.modal is not None
    r = await guild.submit(seren, opened, "Warlock priority")
    assert "Warlock priority" in r.text
    await guild.wait_until(lambda: "Warlock priority" in items.text, what="the public post to show the priority")
    assert "Warlock priority" in officer.text


async def test_suggestions_count_on_the_public_post(guild, running):
    officer, items = await add_sash(guild)
    ilsa, vespera = guild.raiders
    await guild.click(ilsa, items, "Suggest for council · 0")
    await guild.wait_until(lambda: items.button_labels == ["Suggest for council · 1"])
    await guild.click(vespera, items, "Suggest for council · 1")
    await guild.wait_until(lambda: items.button_labels == ["Suggest for council · 2"])
    # The officers see who; the public post only the count.
    await guild.wait_until(lambda: f"Suggested for council by {ilsa.name}, {vespera.name}" in officer.text,
                           what="the officer post to name the raiders")
    assert ilsa.name not in items.text
    r = await guild.click(ilsa, items, "Suggest for council · 2")  # takes it back
    assert r.ephemeral
    await guild.wait_until(lambda: items.button_labels == ["Suggest for council · 1"])


async def test_status_autocomplete_token_and_priorities(guild, running):
    officer, _ = await add_sash(guild)
    for o in guild.officers:
        await guild.click(o, officer, "Council")
    choices = await guild.autocomplete(guild.raiders[0], "loot status", "item", item="sash")
    assert [c["name"] for c in choices] and "Sash" in choices[0]["name"]
    r = await guild.slash(guild.raiders[0], "loot status", item="18000")
    assert r.ephemeral and "council item (decided by the officers, 3 of 3)" in r.text
    r = await guild.slash(guild.officers[0], "loot token")
    assert r.ephemeral and "nlc_" in r.text
    r = await guild.slash(guild.officers[0], "loot priorities", day="Thursday 30 Oct")
    assert "Posted" in r.text
    post = await guild.wait_until(lambda: guild.channel("loot-priorities").find("Thursday 30 Oct"))
    assert "Sash of the Unseen" in post.text


STAFF = ItemInfo(found=True, env="forever", name="Staff of Jordan", quality=4, slot="Two-Hand · Staff")


def fake_wowhead(bot, known):
    """Wowhead knowing these items (without icons, so no emojis to make)."""
    bot.config = dataclasses.replace(bot.config, wowhead=True)

    async def lookup(session, item_id):
        return known.get(item_id, ItemInfo(found=False))
    bot.lookup = lookup


async def test_loot_add_with_just_a_wowhead_link(guild, running):
    fake_wowhead(running.bot, {873: STAFF})
    r = await guild.slash(guild.officers[0], "loot add", item="https://www.wowhead.com/forever/item=873/staff-of-jordan",
                          found="wowhead")
    assert "Added **Staff of Jordan** (873)" in r.text
    officer = await guild.wait_until(lambda: guild.channel("loot-officers").find("Staff of Jordan"))
    assert "-# Not dropped for us yet · spotted on Wowhead" in officer.text
    assert "Epic · Two-Hand · Staff · [Wowhead](https://www.wowhead.com/forever/item=873/staff-of-jordan)" in officer.text
    items = await guild.wait_until(lambda: guild.channel("loot-items").find("Staff of Jordan"))
    assert "NOT DROPPED FOR US YET · SPOTTED ON WOWHEAD\n[spoiler image: Staff of Jordan]" in items.text
    r = await guild.slash(guild.officers[0], "loot add", item="99999")
    assert "I need item 99999's name: Wowhead doesn't know it" in r.text
    r = await guild.slash(guild.officers[0], "loot add", item="Staff of Jordan")
    assert "That isn't an item" in r.text


async def test_loot_import_previews_then_posts(guild, running):
    fake_wowhead(running.bot, {873: STAFF})
    await add_sash(guild)
    csv = ("player,date,time,id,item,itemID,itemString,response,votes,class,instance,boss,difficultyID,mapID,"
           "groupSize,gear1,gear2,responseID,isAwardReason,subType,equipLoc,note,owner\n"
           "Them,2026/10/26,21:05:00,1-1,[Staff of Jordan],873,item:873,Main spec,,MAGE,Molten Core,Garr,,,,,,1,false,,,,X\n"
           "Them,2026/10/26,21:09:00,1-2,[Lava Shard],77777,item:77777,Off spec,,MAGE,Molten Core,Garr,,,,,,3,false,,,,X\n"
           "Them,2026/10/26,21:10:00,1-3,[Sash of the Unseen],18000,item:18000,Main spec,,MAGE,Molten Core,,,,,,,1,false,,,,X\n")
    r = await guild.slash(guild.officers[0], "loot import", file=FileUpload("rclc.csv", csv.encode()))
    preview = r.messages[-1]
    assert r.ephemeral and preview.button_labels == ["Import", "Cancel"]
    assert ("**2 new items**, seen in another guild's raid: Staff of Jordan, Lava Shard." in preview.text
            and "1 item already on the list" in preview.text)
    assert guild.channel("loot-officers").find("Lava Shard") is None  # nothing until Import
    # Only the officer who asked can press it.
    r = await guild.click(guild.officers[1], preview, "Import")
    assert r.ephemeral and "another officer's import" in r.text
    assert guild.channel("loot-officers").find("Lava Shard") is None
    done = await guild.click(guild.officers[0], preview, "Import")
    assert preview.button_labels == [] and "Imported 2 new items" in preview.text, done
    lava = await guild.wait_until(lambda: guild.channel("loot-officers").find("Lava Shard"))
    assert "Molten Core, Garr" in lava.text and "seen in another guild's raid" in lava.text
    # Pasted links, cancelled.
    r = await guild.slash(guild.officers[0], "loot import", text="16805 https://www.wowhead.com/forever/item=873/x")
    assert "Left out, no name (Wowhead doesn't know them): 16805" in r.messages[-1].text
    assert "1 item already on the list" in r.messages[-1].text
    r = await guild.slash(guild.officers[0], "loot import", text="nothing here")
    assert "couldn't find any items" in r.text


class FakeWcl:
    """Warcraft Logs, knowing one report: Lucifron killed just before the sample night's loot."""

    async def report(self, session, host, code):
        return Report(host=host, code=code, title="MC", start_at=RAID - 600, end_at=RAID + 3 * 3600,
                      fights=(Fight(5, "Lucifron", RAID + 650),))


async def test_wcl_links_the_report_on_the_loot_log(guild, running):
    running.bot.wcl = FakeWcl()
    running.bot.store.apply_upload(parse_upload(sample_body()), "discord:1", "Kadmai")
    running.bot.notify()
    log = await guild.wait_until(lambda: guild.channel("loot-log").find("Molten Core"))
    link = "https://classic.warcraftlogs.com/reports/8Td6NXf7AyhbpMWL"
    r = await guild.slash(guild.raiders[0], "loot wcl", link=link)
    assert "officers" in r.text
    r = await guild.slash(guild.officers[0], "loot wcl", link="https://example.com/reports/x")
    assert r.ephemeral and "isn't a Warcraft Logs report link" in r.text
    r = await guild.slash(guild.officers[0], "loot wcl", link=link)
    assert r.ephemeral and "Linked **MC** (1 boss kill) to [Molten Core · Monday 26 Oct](" in r.text
    await guild.wait_until(lambda: f"[Warcraft Logs]({link})" in log.text, what="the log post to link the report")
    assert f"__[Lucifron]({link}#fight=5)__" in log.text


async def test_a_restart_edits_instead_of_reposting_and_a_deleted_post_comes_back(guild, running, tmp_path):
    officer, items = await add_sash(guild)
    await stop_bot(running)
    again = await start_bot(guild.fake, tmp_path / "bot.db")
    try:
        r = await guild.click(guild.officers[0], officer, "Council")  # buttons from before the restart still work
        assert "Council 1 · Roll 0" in r.text
        await guild.quiet()
        assert len(guild.channel("loot-officers").posts) == 1
        # A deleted post comes back at the next change to what it shows (votes aren't on the public post).
        guild.delete_message(items)
        opened = await guild.click(guild.officers[1], officer, "Set priority")
        await guild.submit(guild.officers[1], opened, "Warlock priority")
        back = await guild.wait_until(lambda: guild.channel("loot-items").find("Warlock priority"),
                                      what="the public post to come back")
        assert back.id != items.id and len(guild.channel("loot-items").posts) == 1
    finally:
        await stop_bot(again)
