from typing import Optional, List
import logging

from discord.ext import commands
import discord

from src.database.model import Event
from src.database.database import get_db
from src import crud
from src.utils.ctf_api import fetch_ctf_events
from src.utils.embed_creator import create_event_embed, create_custom_event_embed
from src.utils.get_channel import get_announcement_channel, get_admin_channel
from src.config import settings


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
        # py-cord supports create_forum_channel
        await guild.create_forum_channel("題目", category=category)
    except Exception as e:
        logger.warning(f"Failed to create forum channel, falling back to text channel: {e}")
        await guild.create_text_channel("題目", category=category)

    return category

async def join_request(
    bot: commands.Bot,
    interaction: discord.Interaction,
    event_data: str,
):
    await interaction.response.defer(ephemeral=True)

    event_type = str(event_data.split(":")[0])
    event_id = int(event_data.split(":")[1])

    events = []
    async with get_db() as session:
        if event_type == "event":
            events = await crud.read_event(session, event_id=[event_id])
        elif event_type == "custom":
            events = await crud.read_custom_event(session, category_id=[event_id])
        if len(events) != 1:
            await interaction.followup.send(content="Invalid event", ephemeral=True)
            return
        event = events[0]
        guild_id = interaction.guild.id
        user_id = interaction.user.id

        # If event marked private, request admin approval first
        if (not getattr(interaction.user, "guild_permissions", None) or not interaction.user.guild_permissions.administrator) and event.is_private:
            try:
                admin_channel = await get_admin_channel(bot)
                view = discord.ui.View(timeout=None)
                view.add_item(
                    discord.ui.Button(
                        label='Approve',
                        style=discord.ButtonStyle.green,
                        custom_id=f"ctf_admin_approve:join:{event_type}:{event_id}:{guild_id}:{user_id}",
                    )
                )
                view.add_item(
                    discord.ui.Button(
                        label='Reject',
                        style=discord.ButtonStyle.red,
                        custom_id=f"ctf_admin_reject:join:{event_type}:{event_id}:{guild_id}:{user_id}",
                    )
                )
                embed = discord.Embed(
                    title="審核請求：加入私密活動",
                    description=(
                        f"使用者 <@{user_id}> 請求加入：{event.title} "
                        + (f"(event_id={event.event_id})" if event_type == "event" else f"(category_id={event.category_id})")
                    ),
                    color=discord.Color.orange(),
                )
                await admin_channel.send(embed=embed, view=view)
                await interaction.followup.send(content="已送交管理員審核，請稍候。", ephemeral=True)
                return
            except Exception as e:
                logger.error(f"Failed to send admin approval request: {e}")
                await interaction.followup.send(content=f"審核請求失敗：{e}", ephemeral=True)
                return

        if await join_channel(bot, interaction, event_data, guild_id, user_id):
            await interaction.followup.send(content="Done", ephemeral=True)

async def join_channel(
    bot: commands.Bot,
    interaction: discord.Interaction,
    event_data: str,
    guild_id: int,
    user_id: int,
    fromadmin: bool=False,
):
    messager = interaction.followup.send if not fromadmin else interaction.response.send_message

    event_type = str(event_data.split(":")[0])
    event_id = int(event_data.split(":")[1])

    async with get_db() as session:
        # get event from database
        events = []
        if event_type == "event":
            events = await crud.read_event(session, event_id=[event_id])
        elif event_type == "custom":
            events = await crud.read_custom_event(session, category_id=[event_id])
        if len(events) != 1:
            await messager(content="Invalid event", ephemeral=True)
            return False
        event = events[0]

        guild = bot.get_guild(guild_id)
        if guild is None:
            await messager(content="Guild not found", ephemeral=True)
            return False
        member = guild.get_member(user_id)
        user = bot.get_user(user_id)
        if member is None:
            await messager(content="Member not found", ephemeral=True)
            return False

        # If we already have a stored id, treat it as a category id
        existing = bot.get_channel(event.category_id) if event.category_id else None
        if isinstance(existing, discord.CategoryChannel):
            try:
                # Grant access on category
                perms = existing.permissions_for(member)
                if perms.view_channel:
                    await messager(content="You have joined the category", ephemeral=True)
                    return False

                await existing.set_permissions(member, view_channel=True)

                info_ch = _get_info_channel(existing)
                if info_ch:
                    await info_ch.send(embed=discord.Embed(
                        color=discord.Color.green(),
                        title=f"{user.display_name} joined the category"
                    ))

                logger.info(
                    f"User {user.display_name}(id={user.id}) joined category {existing.name}(id={existing.id})"
                )
                return True
            except Exception as e:
                logger.error(f"Failed to join category: {e}")
                await messager(content=f"Failed to join category: {e}", ephemeral=True)
                return False

        if event_type == "event":
            # Otherwise create a new category with child channels
            events_api = await fetch_ctf_events(event.event_id)
            if len(events_api) != 1:
                await messager(content="Invalid event", ephemeral=True)
                return False
            event_api = events_api[0]

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                user: discord.PermissionOverwrite(view_channel=True),
                guild.me: discord.PermissionOverwrite(view_channel=True),
            }

            category = await _create_event_category_with_channels(guild, event.title, overwrites)
            # store category id
            updated = await crud.update_event(session, event_id=event.event_id, category_id=category.id)
            if updated is None:
                await messager(
                    content=f"Failed to create: database update failed for event_id={event.event_id}",
                    ephemeral=True,
                )
                # Optionally clean up created category
                try:
                    await category.delete(reason="DB update failed for event creation")
                except Exception:
                    pass
                return False

            info_ch = _get_info_channel(category)
            if info_ch:
                embed = await create_event_embed(event_api, f"{user.display_name} 發起了 {event.title}")
                view = discord.ui.View(timeout=None)
                view.add_item(
                    discord.ui.Button(
                        label='Set Private',
                        style=discord.ButtonStyle.gray,
                        custom_id=f"ctf_info:private:event:{category.id}",
                        )
                )
                await info_ch.send(embed=embed, view=view)

            logger.info(
                f"User {user.display_name}(id={user.id}) created and joined category {category.name}(id={category.id})"
            )
            return True

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
            embed = await create_custom_event_embed(name, f"{interaction.user.display_name} 發起了 {name}")
            view = discord.ui.View(timeout=None)
            view.add_item(
                discord.ui.Button(
                    label='Set Private',
                    style=discord.ButtonStyle.gray,
                    custom_id=f"ctf_info:private:custom:{category.id}",
                    )
            )
            await info_ch.send(embed=embed, view=view)

        channel:discord.TextChannel = await get_announcement_channel(bot)
        embed = await create_custom_event_embed(name, f"{interaction.user.display_name} 發起了 {name}")
        view = discord.ui.View(timeout=None)
        view.add_item(
            discord.ui.Button(
                label='Join',
                style=discord.ButtonStyle.blurple,
                custom_id=f"ctf_join_channel:event:custom:{category.id}",
                emoji=settings.EMOJI,
            )
        )
        view.add_item(
            discord.ui.Button(
                label='Set Private',
                style=discord.ButtonStyle.gray,
                custom_id=f"ctf_join_channel:private:custom:{category.id}",
                )
        )
        await channel.send(embed=embed, view=view)

        await interaction.followup.send(content="Done", ephemeral=True)
        logger.info(
            f"User {interaction.user.display_name}(id={interaction.user.id}) created custom category {category.name}(id={category.id})"
        )
        return
    except Exception as e:
        logger.error(f"Failed to create custom category: {e}")
        await interaction.followup.send(content=f"Failed to create custom category: {e}", ephemeral=True)
        return

async def set_private(
    bot: commands.Bot,
    interaction: discord.Interaction,
    event_data: str,
):
    try:
        if not getattr(interaction.user, "guild_permissions", None) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(content="你沒有權限使用此功能（需要 Administrator）", ephemeral=True)
            return False
    except Exception:
        await interaction.response.send_message(content="權限檢查失敗，請於伺服器中使用此功能", ephemeral=True)
        return False

    async with get_db() as session:
        event_type = str(event_data.split(":")[0])
        event_id = int(event_data.split(":")[1])
        # get event from database
        events = []
        if event_type == "event":
            events = await crud.read_event(session, event_id=[event_id])
        elif event_type == "custom":
            events = await crud.read_custom_event(session, category_id=[event_id])
        
        if len(events) != 1:
            await interaction.response.send_message(content="Invalid event", ephemeral=True)
            return False

        event = events[0]

        updated = None
        if event_type == "event":
            updated = await crud.update_event(session, event_id=event.event_id, private=not event.is_private)
        elif event_type == "custom":
            updated = await crud.update_custom_event(session, category_id=event.category_id, private=not event.is_private)

        if updated is None:
            await interaction.response.send_message(
                content=(
                    f"Failed to update privacy: database update failed for "
                    + (f"event_id={event.event_id}" if event_type == "event" else f"category_id={event.category_id}")
                ),
                ephemeral=True,
            )
            return False

        logger.info(
            f"User {interaction.user.display_name}(id={interaction.user.id}) set event {event.title}(id={event_id}) private={event.is_private}"
        )
        return True