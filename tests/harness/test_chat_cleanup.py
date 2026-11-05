"""#in-game-chat: the bot deletes the game's "not linked" lines and nothing else."""
from __future__ import annotations

import asyncio

import pytest

from bot.cogs.chatcleanup import FROM_THE_GAME, PLACEHOLDER

from .conftest import start_bot, stop_bot

MESSAGE_CONTENT = 1 << 15


@pytest.fixture
def chat(guild):
    return guild.fake.add_channel("in-game-chat")


@pytest.fixture
async def cleaning(guild, chat, tmp_path):
    running = await start_bot(guild.fake, tmp_path / "bot.db", ch_in_game_chat=chat.id)
    yield running
    await stop_bot(running)
    assert guild.unknown_routes == [], guild.unknown_routes


def lines(channel):
    return [m.content for m in channel.posts]


async def test_lines_that_came_in_while_the_bot_was_away_are_cleared_at_start(guild, chat, tmp_path):
    raider, fake = guild.raiders[0], guild.fake
    fake.post_as(raider, chat, PLACEHOLDER, flags=FROM_THE_GAME)
    fake.post_as(raider, chat, "anyone for Deadmines?", flags=FROM_THE_GAME)
    fake.post_as(raider, chat, PLACEHOLDER)  # typed on Discord: not the game's
    fake.post_as(raider, chat, PLACEHOLDER, flags=FROM_THE_GAME)
    elsewhere = fake.post_as(raider, guild.channel("general"), PLACEHOLDER, flags=FROM_THE_GAME)
    running = await start_bot(fake, tmp_path / "bot.db", ch_in_game_chat=chat.id)
    await guild.wait_until(lambda: len(chat.posts) == 2, what="the two lines to go")
    assert lines(chat) == ["anyone for Deadmines?", PLACEHOLDER]
    assert not elsewhere.deleted
    await stop_bot(running)


async def test_a_new_line_is_deleted_and_real_chat_stays(guild, chat, cleaning):
    raider, fake = guild.raiders[0], guild.fake
    assert fake.identified_intents & MESSAGE_CONTENT
    await fake.say(raider, chat, "hello from Stormwind", flags=FROM_THE_GAME)
    await fake.say(raider, guild.channel("general"), PLACEHOLDER, flags=FROM_THE_GAME)
    line = await fake.say(raider, chat, PLACEHOLDER, flags=FROM_THE_GAME)
    await guild.wait_until(lambda: line.deleted, what="the line to go")
    assert lines(chat) == ["hello from Stormwind"]
    assert guild.channel("general").find(PLACEHOLDER)


async def test_without_permission_the_bot_carries_on(guild, chat, cleaning):
    raider, fake = guild.raiders[0], guild.fake
    fake.forbid_deletes = True
    line = await fake.say(raider, chat, PLACEHOLDER, flags=FROM_THE_GAME)
    await guild.wait_until(lambda: fake.refused_deletes, what="the bot to try")
    assert not line.deleted
    fake.forbid_deletes = False
    line = await fake.say(raider, chat, PLACEHOLDER, flags=FROM_THE_GAME)
    await guild.wait_until(lambda: line.deleted, what="the next line to go")


async def test_without_the_setting_it_asks_for_nothing_and_touches_nothing(guild, chat, running):
    raider, fake = guild.raiders[0], guild.fake
    assert not fake.identified_intents & MESSAGE_CONTENT  # Discord refuses to connect a bot without it switched on
    assert "ChatCleanupCog" not in running.bot.cogs
    line = await fake.say(raider, chat, PLACEHOLDER, flags=FROM_THE_GAME)
    await asyncio.sleep(0.05)
    assert not line.deleted
