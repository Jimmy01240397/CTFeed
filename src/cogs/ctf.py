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
    def __init__(self, bot:commands.Bot, known_events:List[Event], custom_events):
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(JoinSelect(bot, known_events, custom_events))
        self.add_item(RemoveSelect(bot, known_events, custom_events))
        self.add_item(CreateSelect(bot, known_events))

class JoinSelect(discord.ui.Select):
    def __init__(self, bot:commands.Bot, known_events:List[Event], custom_events):
        self.bot = bot
        options = []
        for e in known_events[:15]:
            options.append(discord.SelectOption(label=e.title, value=f"event:{e.event_id}", description=f"event id={e.event_id}"))
        for ce in custom_events[:8]:
            options.append(discord.SelectOption(label=ce.title, value=f"custom:{ce.category_id}", description=f"category id={ce.category_id}"))
        placeholder = "選擇要加入的項目"
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options, custom_id="ctf_select_join")

    async def callback(self, interaction:discord.Interaction):
        value = self.values[0]
        if value.startswith("event:"):
            event_id = int(value.split(":")[1])
            await join_channel(self.bot, interaction, event_id)
            return
        if value.startswith("custom:"):
            category_id = int(value.split(":")[1])
            await join_custom_channel(self.bot, interaction, category_id)
            return

class RemoveSelect(discord.ui.Select):
    def __init__(self, bot:commands.Bot, known_events:List[Event], custom_events):
        self.bot = bot
        options = []
        for e in known_events[:15]:
            options.append(discord.SelectOption(label=e.title, value=f"event:{e.event_id}", description=f"event id={e.event_id}"))
        for ce in custom_events[:8]:
            options.append(discord.SelectOption(label=ce.title, value=f"custom:{ce.category_id}", description=f"category id={ce.category_id}"))
        placeholder = "選擇要移除的資料"
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options, custom_id="ctf_select_remove")

    async def callback(self, interaction:discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        value = self.values[0]
        deleted_events = 0
        deleted_custom = 0
        try:
            async with get_db() as session:
                if value.startswith("event:"):
                    eid = int(value.split(":")[1])
                    res = await crud.delete_event(session, event_id=[eid])
                    if res == 1:
                        deleted_events = 1
                elif value.startswith("custom:"):
                    cid = int(value.split(":")[1])
                    res2 = await crud.delete_custom_event(session, category_id=[cid])
                    if res2 == 1:
                        deleted_custom = 1
        except Exception as e:
            await interaction.followup.send(content=f"Failed: {e}", ephemeral=True)
            return
        if deleted_events == 0 and deleted_custom == 0:
            await interaction.followup.send(content="No matching record deleted", ephemeral=True)
            return
        await interaction.followup.send(content=f"Deleted: events={deleted_events}, custom_categories={deleted_custom}", ephemeral=True)

class CreateSelect(discord.ui.Select):
    def __init__(self, bot:commands.Bot, known_events:List[Event]):
        self.bot = bot
        options = []
        for e in known_events[:20]:
            options.append(discord.SelectOption(label=e.title, value=f"name:{e.title}", description="使用活動名稱建立自訂分類"))
        presets = ["Practice", "Training", "Workshop", "CTF Study", "Internal CTF"]
        for p in presets:
            options.append(discord.SelectOption(label=p, value=f"name:{p}", description="使用預設名稱建立自訂分類"))
        placeholder = "選擇要建立的自訂 CTF 名稱"
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options[:25], custom_id="ctf_select_create")

    async def callback(self, interaction:discord.Interaction):
        value = self.values[0]
        if value.startswith("name:"):
            name = value.split(":", 1)[1]
            await create_custom_channel(self.bot, interaction, name)
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

        
        await ctx.response.send_message(embed=embed, view=CTFMenuView(self.bot, known_events, custom_events), ephemeral=True)



def setup(bot:commands.Bot):
    bot.add_cog(CTF(bot))
