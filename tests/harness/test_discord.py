"""The real bot (discord.py, slash commands, buttons, the form) against the fake Discord."""
from __future__ import annotations

from .conftest import start_bot, stop_bot

SASH = dict(item_id=18000, name="Sash of the Unseen", slot="Waist · Cloth", source="Molten Core, Lucifron")


async def add_sash(guild):
    await guild.slash(guild.officers[0], "loot add", **SASH)
    officer = await guild.wait_until(lambda: guild.channel("loot-officers").find("Sash of the Unseen"))
    items = await guild.wait_until(lambda: guild.channel("loot-items").find("Sash of the Unseen"))
    return officer, items


async def test_loot_add_posts_to_both_channels_with_a_thread(guild, running):
    r = await guild.slash(guild.officers[0], "loot add", **SASH)
    assert r.ephemeral
    officer, items = await add_sash(guild)
    assert officer.thread is not None and officer.thread.name == "Sash of the Unseen"
    assert officer.button_labels == ["Council", "Roll", "Set priority"]
    assert "### Sash of the Unseen\n-# Epic · Waist · Cloth · Molten Core, Lucifron" in officer.text
    assert officer.components[0]["accent_color"] == 0xA335EE  # /loot add assumes epic
    assert items.thread is None
    assert items.button_labels == ["Suggest for council · 0"]
    # Using it again updates the posts instead of adding new ones.
    await guild.slash(guild.officers[0], "loot add", **dict(SASH, name="Sash of the Unseen Eye"))
    await guild.wait_until(lambda: "Unseen Eye" in officer.text, what="the officer post to be edited")
    await guild.quiet()
    assert len(guild.channel("loot-officers").posts) == 1 and len(guild.channel("loot-items").posts) == 1


async def test_raiders_cant_use_officer_commands_or_buttons(guild, running):
    officer, _ = await add_sash(guild)
    ilsa = guild.raiders[0]
    r = await guild.slash(ilsa, "loot add", item_id=1, name="Nope")
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
    _, items = await add_sash(guild)
    ilsa, vespera = guild.raiders
    await guild.click(ilsa, items, "Suggest for council · 0")
    await guild.wait_until(lambda: items.button_labels == ["Suggest for council · 1"])
    await guild.click(vespera, items, "Suggest for council · 1")
    await guild.wait_until(lambda: items.button_labels == ["Suggest for council · 2"])
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
