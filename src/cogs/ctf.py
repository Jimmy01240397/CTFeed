from typing import List
from datetime import datetime
from zoneinfo import ZoneInfo
import logging

import discord
from discord.ext import commands

from src.config import settings
from src.database.database import get_db
from src.database.model import BaseEvent, Event
from src import crud
import crud.event as crud_event
import crud.custom_event as crud_custom_event
from src.utils.join_channel import join_request
from src.utils.join_channel import create_custom_channel

# logging
logger = logging.getLogger(__name__)

async def event_join_autocomplete(ctx: discord.AutocompleteContext) -> List[str]:
    events:List[BaseEvent] = await crud.read_all_event()
    result = []
    for e in events:
        if ctx.value.lower() in e.title.lower():
            result.append(e.title)
    return result[:25]

# ui - ctf menu
class CTFMenuView(discord.ui.View):
    def __init__(self, bot:commands.Bot):
        super().__init__(timeout=None)
        
        self.bot = bot

    @discord.ui.button(label="Join a channel", custom_id="ctf_select_channel", style=discord.ButtonStyle.blurple, emoji=settings.EMOJI)
    async def ctf_select_channel_callback(self, button:discord.ui.Button, interaction:discord.Interaction):
        known_events:List[BaseEvent] = await crud.read_all_event()
        if len(known_events) == 0:
            await interaction.response.send_message(content="目前沒有可加入的活動或自訂類別", ephemeral=True)
            return
        view = JoinSelectPrompt(self.bot, known_events)
        await interaction.response.send_message(content="請選擇要加入的項目", view=view, ephemeral=True)

    @discord.ui.button(label="Remove from database", custom_id="ctf_remove_db", style=discord.ButtonStyle.red, emoji="🗑️")
    async def ctf_remove_db_callback(self, button:discord.ui.Button, interaction:discord.Interaction):
        # 僅允許具備 Administrator 權限的使用者操作
        try:
            if not getattr(interaction.user, "guild_permissions", None) or not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message(content="你沒有權限使用此功能（需要 Administrator）", ephemeral=True)
                return
        except Exception:
            await interaction.response.send_message(content="權限檢查失敗，請於伺服器中使用此功能", ephemeral=True)
            return

        known_events:List[BaseEvent] = await crud.read_all_event(filter=True)

        if len(known_events) == 0:
            await interaction.response.send_message(content="目前沒有可移除的活動或自訂類別", ephemeral=True)
            return
        view = RemoveSelectPrompt(self.bot, known_events)
        await interaction.response.send_message(content="請選擇要移除的資料", view=view, ephemeral=True)


    @discord.ui.button(label="Create CTF", custom_id="ctf_create_custom", style=discord.ButtonStyle.green, emoji="🆕")
    async def ctf_create_custom_callback(self, button:discord.ui.Button, interaction:discord.Interaction):
        await interaction.response.send_modal(CreateCTFModal(bot=self.bot, title="Create a custom CTF category"))

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

# ---- Select-based prompts (dropdowns) ----
class JoinSelectPrompt(discord.ui.View):
    def __init__(self, bot:commands.Bot, known_events:List[BaseEvent]):
        super().__init__(timeout=180)
        self.add_item(JoinSelect(bot, known_events))

class JoinSelect(discord.ui.Select):
    def __init__(self, bot:commands.Bot, known_events:List[BaseEvent]):
        self.bot = bot
        options:List[discord.SelectOption] = [discord.SelectOption(label=e.title[:100], value=f"{e.event_type}:{e.event_id}", description=f"event id={e.event_id}") for e in known_events]
        options = options[:25]
        super().__init__(placeholder="選擇要加入的項目", min_values=1, max_values=1, options=options, custom_id="ctf_select_join")

    async def callback(self, interaction:discord.Interaction):
        choice = self.values[0]
        await join_request(self.bot, interaction, choice)

class RemoveSelectPrompt(discord.ui.View):
    def __init__(self, bot:commands.Bot, known_events:List[BaseEvent]):
        super().__init__(timeout=180)
        self.add_item(RemoveSelect(bot, known_events))

class RemoveSelect(discord.ui.Select):
    def __init__(self, bot:commands.Bot, known_events:List[BaseEvent]):
        self.bot = bot
        options:List[discord.SelectOption] = [discord.SelectOption(label=e.title[:100], value=f"{e.event_type}:{e.event_id}", description=f"event id={e.event_id}") for e in known_events]
        options = options[:25]
        super().__init__(placeholder="選擇要移除的資料", min_values=1, max_values=1, options=options, custom_id="ctf_select_remove")

    async def callback(self, interaction:discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        choice = self.values[0]
        usemodule = None
        if choice.startswith("event:"):
            usemodule = crud_event
        elif choice.startswith("custom:"):
            usemodule = crud_custom_event
        else:
            await interaction.followup.send(content="Invalid choice", ephemeral=True)
            return
        try:
            eid = int(choice.split(":")[1])
            async with get_db() as session:
                if await usemodule.delete_event(session, event_id=[eid]):
                    await interaction.followup.send(content=f"Deleted success", ephemeral=True)
                else:
                    await interaction.followup.send(content=f"No matching record deleted", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(content=f"Failed: {e}", ephemeral=True)
            return        

# cog
class CTF(commands.Cog):
    def __init__(self, bot:commands.Bot):
        self.bot:commands.Bot = bot
    
    
    @discord.slash_command(name="ctf_menu", description="list CTF events")
    async def ctf_menu(self, ctx:discord.ApplicationContext):
        known_events:List[BaseEvent] = await crud.read_all_event()
        
        # embed
        embed = discord.Embed(
            title=f"{settings.EMOJI} CTF events tracked",
            color=discord.Color.green()
        )
        for event in known_events:
            embed.add_field(
                name=f"[event id={event.event_id}] {event.title}",
                value=f"start at {datetime.fromtimestamp(event.start).astimezone(ZoneInfo(settings.TIMEZONE))}\n\
                finish at {datetime.fromtimestamp(event.finish).astimezone(ZoneInfo(settings.TIMEZONE))}" if isinstance(event, Event) else "",
                inline=False
            )
                
        await ctx.response.send_message(embed=embed, view=CTFMenuView(self.bot), ephemeral=True)

    @discord.slash_command(name="join_ctf", description="Join a CTF event channel")
    async def join_event(self, ctx:discord.ApplicationContext,
        event_title: str = discord.Option(
            description="請選擇要加入的項目",
            autocomplete=event_join_autocomplete
        )
    ):
        event = await crud.read_event(title=[event_title])
        if len(event) == 0:
            await ctx.response.send_message(content="找不到指定的活動", ephemeral=True)
            return
        await join_request(self.bot, ctx.interaction, f"{event[0].event_type}:{event[0].event_id}")

def setup(bot:commands.Bot):
    bot.add_cog(CTF(bot))
