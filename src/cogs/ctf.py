from typing import List
from datetime import datetime
from zoneinfo import ZoneInfo
import logging

import discord
from discord.ext import commands

from src.config import settings
from src.database.database import get_db
from src.database.model import Event
from src import crud
from src.utils.join_channel import join_channel
from src.utils.join_channel import create_custom_channel
from src.utils.join_channel import join_custom_channel

# logging
logger = logging.getLogger(__name__)

# ui - ctf menu
class CTFMenuView(discord.ui.View):
    def __init__(self, bot:commands.Bot):
        super().__init__(timeout=None)
        
        self.bot = bot

    
    @discord.ui.button(label="Join a channel", custom_id="ctf_select_channel", style=discord.ButtonStyle.blurple, emoji=settings.EMOJI)
    async def ctf_select_channel_callback(self, button:discord.ui.Button, interaction:discord.Interaction):
        await interaction.response.send_modal(JoinChannelModal(bot=self.bot, title="Create / Join via CTFTime event id or category id"))

    @discord.ui.button(label="Remove from database", custom_id="ctf_remove_db", style=discord.ButtonStyle.red, emoji="🗑️")
    async def ctf_remove_db_callback(self, button:discord.ui.Button, interaction:discord.Interaction):
        await interaction.response.send_modal(RemoveCTFModal(bot=self.bot, title="Remove CTF via event id or category id"))

    @discord.ui.button(label="Create CTF", custom_id="ctf_create_custom", style=discord.ButtonStyle.green, emoji="🆕")
    async def ctf_create_custom_callback(self, button:discord.ui.Button, interaction:discord.Interaction):
        await interaction.response.send_modal(CreateCTFModal(bot=self.bot, title="Create a custom CTF category"))

class JoinChannelModal(discord.ui.Modal):
    def __init__(self, bot:commands.Bot, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        
        self.bot = bot
        
        self.add_item(discord.ui.InputText(label="Enter CTFTime event id or Discord category id", style=discord.InputTextStyle.short))


    async def callback(self, interaction: discord.Interaction):
        try:
            provided_id = int(self.children[0].value)
        except:
            await interaction.response.send_message(content="Invalid arguments", ephemeral=True)
            return
        
        # If the provided id corresponds to a Discord CategoryChannel, treat as custom category join
        ch = self.bot.get_channel(provided_id)
        if isinstance(ch, discord.CategoryChannel):
            await join_custom_channel(self.bot, interaction, provided_id)
            return

        # Otherwise treat it as a CTFTime event id
        await join_channel(self.bot, interaction, provided_id)
        return

class RemoveCTFModal(discord.ui.Modal):
    def __init__(self, bot:commands.Bot, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        
        self.bot = bot
        
        self.add_item(discord.ui.InputText(label="Enter CTFTime event id or Discord category id", style=discord.InputTextStyle.short))

    async def callback(self, interaction: discord.Interaction):
        try:
            provided_id = int(self.children[0].value)
        except:
            await interaction.response.send_message(content="Invalid arguments", ephemeral=True)
            return

        deleted_events = 0
        deleted_custom = 0
        targets_event_ids = set()
        try:
            async with get_db() as session:
                # match Event by event_id
                events_by_eid = await crud.read_event(session, event_id=[provided_id], finish_after=None)
                targets_event_ids.update([e.event_id for e in events_by_eid])

                # match Event by category_id
                events_by_cid = await crud.read_event(session, category_id=[provided_id], finish_after=None)
                targets_event_ids.update([e.event_id for e in events_by_cid])

                # delete Events
                if len(targets_event_ids) > 0:
                    res = await crud.delete_event(session, event_id=list(targets_event_ids))
                    if res == 1:
                        deleted_events = len(targets_event_ids)

                # delete CustomEvent by category_id
                customs = await crud.read_custom_event(session, category_id=[provided_id])
                if len(customs) > 0:
                    res2 = await crud.delete_custom_event(session, category_id=[provided_id])
                    if res2 == 1:
                        deleted_custom = len(customs)
        except Exception as e:
            await interaction.response.send_message(content=f"Failed: {e}", ephemeral=True)
            return

        if deleted_events == 0 and deleted_custom == 0:
            await interaction.response.send_message(content="No matching event or custom category in database", ephemeral=True)
            return

        await interaction.response.send_message(
            content=f"Deleted DB records: events={deleted_events}, custom_categories={deleted_custom}",
            ephemeral=True
        )

class CreateCTFModal(discord.ui.Modal):
    def __init__(self, bot:commands.Bot, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        
        self.bot = bot
        
        self.add_item(discord.ui.InputText(label="Enter custom CTF name", style=discord.InputTextStyle.short))

    async def callback(self, interaction: discord.Interaction):
        name = self.children[0].value.strip()
        if not name:
            await interaction.response.send_message(content="Name cannot be empty", ephemeral=True)
            return
        try:
            await create_custom_channel(self.bot, interaction, name)
        except Exception as e:
            # create_custom_channel handles response, but just in case
            await interaction.response.send_message(content=f"Failed to create: {e}", ephemeral=True)
        return

# cog
class CTF(commands.Cog):
    def __init__(self, bot:commands.Bot):
        self.bot:commands.Bot = bot
    
    
    @discord.slash_command(name="ctf_menu", description="list CTF events")
    async def ctf_menu(self, ctx:discord.ApplicationContext):
        async with get_db() as session:
            known_events:List[Event] = await crud.read_event(session)
            custom_events = await crud.read_custom_event(session)
        
        # embed
        embed = discord.Embed(
            title=f"{settings.EMOJI} CTF events tracked",
            color=discord.Color.green()
        )
        embed.add_field(
            name=f"{settings.EMOJI} CTFd CTF categories",
            value="",
            inline=False
        )
        for event in known_events:
            embed.add_field(
                name=f"[event id={event.event_id}] {event.title}",
                value=f"start at {datetime.fromtimestamp(event.start).astimezone(ZoneInfo(settings.TIMEZONE))}\n\
                finish at {datetime.fromtimestamp(event.finish).astimezone(ZoneInfo(settings.TIMEZONE))}",
                inline=False
            )
        
        
        # List custom CTF categories
        if len(custom_events) > 0:
            embed.add_field(
                name=f"{settings.EMOJI} Custom CTF categories",
                value="",
                inline=False
            )
            for ce in custom_events:
                embed.add_field(
                    name=f"[category id={ce.category_id}] {ce.title}",
                    value="",
                    inline=False
                )

        
        await ctx.response.send_message(embed=embed, view=CTFMenuView(self.bot), ephemeral=True)



def setup(bot:commands.Bot):
    bot.add_cog(CTF(bot))
