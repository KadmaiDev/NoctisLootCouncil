import discord
from discord import app_commands


class NotOfficer(app_commands.CheckFailure):
    pass


def is_officer(user: discord.abc.User, role_id: int) -> bool:
    # Only the officer role counts, not Administrator: votes decide items, so who can vote
    # should be exactly the officers.
    return isinstance(user, discord.Member) and role_id != 0 and any(r.id == role_id for r in user.roles)


def officer_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not is_officer(interaction.user, interaction.client.config.officer_role_id):
            raise NotOfficer()
        return True
    return app_commands.check(predicate)
