from typing import Optional, List
import logging

from discord.ext import commands
import discord

from src.database.model import Event
from src.database.database import get_db
from src import crud
from src.utils.ctf_api import fetch_ctf_events
from src.utils.embed_creator import create_event_embed

logger = logging.getLogger(__name__)


def _get_child_text_channel(category: discord.CategoryChannel, name: str) -> Optional[discord.TextChannel]:
    for ch in category.channels:
        if isinstance(ch, discord.TextChannel) and ch.name.lower() == name.lower():
            return ch
    return None


def _get_info_channel(category: discord.CategoryChannel) -> Optional[discord.TextChannel]:
    # Prefer an 'info' channel; otherwise first text channel
    ch = _get_child_text_channel(category, "資訊")
    if ch:
        return ch
    for ch in category.channels:
        if isinstance(ch, discord.TextChannel):
            return ch
    return None


async def get_info_channel_for_category(bot: commands.Bot, category_id: int) -> Optional[discord.TextChannel]:
    cat = bot.get_channel(category_id)
    if not isinstance(cat, discord.CategoryChannel):
        return None
    return _get_info_channel(cat)


async def _create_event_category_with_channels(
    guild: discord.Guild,
    name: str,
    overwrites: dict,
) -> discord.CategoryChannel:
    # Create category
    category = await guild.create_category(name, overwrites=overwrites)

    # Create child channels
    await guild.create_text_channel("資訊", category=category)
    await guild.create_text_channel("聊天", category=category)
    # Try to create a forum channel for problems; fallback to text
    try:
        # py-cord supports create_forum
        await guild.create_forum("題目", category=category)
    except Exception as e:
        logger.warning(f"Failed to create forum channel, falling back to text channel: {e}")
        await guild.create_text_channel("題目", category=category)

    return category


async def join_channel(
    bot: commands.Bot,
    interaction: discord.Interaction,
    event_id: int,
):
    await interaction.response.defer(ephemeral=True)

    async with get_db() as session:
        # get event from database
        events = await crud.read_event(session, event_id=[event_id])
        if len(events) != 1:
            await interaction.followup.send(content="Invalid event", ephemeral=True)
            return
        event: Event = events[0]

        guild = interaction.guild
        member = guild.get_member(interaction.user.id)

        # If we already have a stored id, treat it as a category id
        existing = bot.get_channel(event.category_id) if event.category_id else None
        if isinstance(existing, discord.CategoryChannel):
            try:
                # Grant access on category
                perms = existing.permissions_for(member)
                if perms.view_channel:
                    await interaction.followup.send(content="You have joined the category", ephemeral=True)
                    return

                await existing.set_permissions(member, view_channel=True)

                info_ch = _get_info_channel(existing)
                if info_ch:
                    await info_ch.send(embed=discord.Embed(
                        color=discord.Color.green(),
                        title=f"{interaction.user.display_name} joined the category"
                    ))

                await interaction.followup.send(content="Done", ephemeral=True)
                logger.info(
                    f"User {interaction.user.display_name}(id={interaction.user.id}) joined category {existing.name}(id={existing.id})"
                )
                return
            except Exception as e:
                logger.error(f"Failed to join category: {e}")
                await interaction.followup.send(content=f"Failed to join category: {e}", ephemeral=True)
                return

        # Otherwise create a new category with child channels
        events_api = await fetch_ctf_events(event.event_id)
        if len(events_api) != 1:
            await interaction.followup.send(content="Invalid event", ephemeral=True)
            return
        event_api = events_api[0]

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True),
            guild.me: discord.PermissionOverwrite(view_channel=True),
        }

        try:
            category = await _create_event_category_with_channels(guild, event.title, overwrites)
            # store category id
            updated = await crud.update_event(session, event_id=event.event_id, category_id=category.id)
            if updated is None:
                await interaction.followup.send(
                    content=f"Failed to create: database update failed for event_id={event.event_id}",
                    ephemeral=True,
                )
                # Optionally clean up created category
                try:
                    await category.delete(reason="DB update failed for event creation")
                except Exception:
                    pass
                return

            info_ch = _get_info_channel(category)
            if info_ch:
                embed = await create_event_embed(event_api, f"{interaction.user.display_name} 發起了 {event.title}")
                await info_ch.send(embed=embed)

            await interaction.followup.send(content="Done", ephemeral=True)
            logger.info(
                f"User {interaction.user.display_name}(id={interaction.user.id}) created and joined category {category.name}(id={category.id})"
            )
            return
        except Exception as e:
            logger.error(f"Failed to create category: {e}")
            await interaction.followup.send(content=f"Failed to create category: {e}", ephemeral=True)
            return

async def create_custom_channel(
    bot: commands.Bot,
    interaction: discord.Interaction,
    name: str,
):
    await interaction.response.defer(ephemeral=True)

    guild = interaction.guild
    member = guild.get_member(interaction.user.id)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True),
        guild.me: discord.PermissionOverwrite(view_channel=True),
    }

    try:
        category = await _create_event_category_with_channels(guild, name, overwrites)

        # record custom category
        async with get_db() as session:
            await crud.create_custom_event(session, title=name, category_id=category.id)

        info_ch = _get_info_channel(category)
        if info_ch:
            await info_ch.send(embed=discord.Embed(
                color=discord.Color.green(),
                title=f"{interaction.user.display_name} 建立了自訂 CTF：{name}"
            ))

        await interaction.followup.send(content="Done", ephemeral=True)
        logger.info(
            f"User {interaction.user.display_name}(id={interaction.user.id}) created custom category {category.name}(id={category.id})"
        )
        return
    except Exception as e:
        logger.error(f"Failed to create custom category: {e}")
        await interaction.followup.send(content=f"Failed to create custom category: {e}", ephemeral=True)
        return


async def join_custom_channel(
    bot: commands.Bot,
    interaction: discord.Interaction,
    category_id: int,
):
    await interaction.response.defer(ephemeral=True)

    guild = interaction.guild
    member = guild.get_member(interaction.user.id)

    # If we already have a stored id, treat it as a category id
    existing = bot.get_channel(category_id) if category_id else None
    try:
        # Grant access on category
        perms = existing.permissions_for(member)
        if perms.view_channel:
            await interaction.followup.send(content="You have joined the category", ephemeral=True)
            return

        await existing.set_permissions(member, view_channel=True)

        info_ch = _get_info_channel(existing)
        if info_ch:
            await info_ch.send(embed=discord.Embed(
                color=discord.Color.green(),
                title=f"{interaction.user.display_name} joined the category"
            ))

        await interaction.followup.send(content="Done", ephemeral=True)
        logger.info(
            f"User {interaction.user.display_name}(id={interaction.user.id}) joined category {existing.name}(id={existing.id})"
        )
        return
    except Exception as e:
        logger.error(f"Failed to join category: {e}")
        await interaction.followup.send(content=f"Failed to join category: {e}", ephemeral=True)
        return


