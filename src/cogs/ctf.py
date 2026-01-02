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
from src.utils.join_channel import join_request
from src.utils.join_channel import create_custom_channel

# logging
logger = logging.getLogger(__name__)

# ui - ctf menu
class CTFMenuView(discord.ui.View):
    def __init__(self, bot:commands.Bot):
        super().__init__(timeout=None)
        
        self.bot = bot

    
    @discord.ui.button(label="Join a channel", custom_id="ctf_select_channel", style=discord.ButtonStyle.blurple, emoji=settings.EMOJI)
    async def ctf_select_channel_callback(self, button:discord.ui.Button, interaction:discord.Interaction):
        # 改為顯示下拉式表單的視窗（ephemeral），使用名稱選擇
        async with get_db() as session:
            known_events:List[Event] = await crud.read_event(session)
            custom_events = await crud.read_custom_event(session)
        if len(known_events) == 0 and len(custom_events) == 0:
            await interaction.response.send_message(content="目前沒有可加入的活動或自訂類別", ephemeral=True)
            return
        view = JoinSelectPrompt(self.bot, known_events, custom_events)
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

        # 改為顯示下拉式表單的視窗（ephemeral），使用名稱選擇
        async with get_db() as session:
            known_events:List[Event] = await crud.read_event(session, finish_after=None)
            custom_events = await crud.read_custom_event(session)
        # 僅顯示已建立的分類（存在於 Discord 的分類頻道）
        filtered_events:List[Event] = []
        for e in known_events:
            if getattr(e, "category_id", None) and e.category_id is not None:
                filtered_events.append(e)

        if len(filtered_events) == 0 and len(custom_events) == 0:
            await interaction.response.send_message(content="目前沒有可移除的活動或自訂類別", ephemeral=True)
            return
        view = RemoveSelectPrompt(self.bot, filtered_events, custom_events)
        await interaction.response.send_message(content="請選擇要移除的資料", view=view, ephemeral=True)


    @discord.ui.button(label="Create CTF", custom_id="ctf_create_custom", style=discord.ButtonStyle.green, emoji="🆕")
    async def ctf_create_custom_callback(self, button:discord.ui.Button, interaction:discord.Interaction):
        await interaction.response.send_modal(CreateCTFModal(bot=self.bot, title="Create a custom CTF category"))


    async def callback(self, interaction:discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        choice = self.values[0]
        deleted_events = 0
        deleted_custom = 0
        try:
            async with get_db() as session:
                if choice.startswith("event:"):
                    eid = int(choice.split(":")[1])
                    res = await crud.delete_event(session, event_id=[eid])
                    if res == 1:
                        deleted_events = 1
                elif choice.startswith("custom:"):
                    cid = int(choice.split(":")[1])
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
    def __init__(self, bot:commands.Bot, known_events:List[Event], custom_events):
        super().__init__(timeout=180)
        self.add_item(JoinSelect(bot, known_events, custom_events))

class JoinSelect(discord.ui.Select):
    def __init__(self, bot:commands.Bot, known_events:List[Event], custom_events):
        self.bot = bot
        options:List[discord.SelectOption] = []
        # then custom categories
        for ce in custom_events:
            options.append(discord.SelectOption(label=ce.title[:100], value=f"custom:{ce.category_id}", description=f"category id={ce.category_id}"))
        # events first
        for e in known_events:
            options.append(discord.SelectOption(label=e.title[:100], value=f"event:{e.event_id}", description=f"event id={e.event_id}"))
        # limit to 25 (Discord limit)
        options = options[:25]
        super().__init__(placeholder="選擇要加入的項目", min_values=1, max_values=1, options=options, custom_id="ctf_select_join")

    async def callback(self, interaction:discord.Interaction):
        choice = self.values[0]

        await join_request(self.bot, interaction, choice)

class RemoveSelectPrompt(discord.ui.View):
    def __init__(self, bot:commands.Bot, known_events:List[Event], custom_events):
        super().__init__(timeout=180)
        self.add_item(RemoveSelect(bot, known_events, custom_events))

class RemoveSelect(discord.ui.Select):
    def __init__(self, bot:commands.Bot, known_events:List[Event], custom_events):
        self.bot = bot
        options:List[discord.SelectOption] = []
        # 僅包含存在中的分類頻道
        for ce in custom_events:
            options.append(discord.SelectOption(label=ce.title[:100], value=f"custom:{ce.category_id}", description=f"category id={ce.category_id}"))
        for e in known_events:
            if getattr(e, "category_id", None) and e.category_id is not None:
                options.append(discord.SelectOption(label=e.title[:100], value=f"event:{e.event_id}", description=f"event id={e.event_id}"))
        options = options[:25]
        super().__init__(placeholder="選擇要移除的資料", min_values=1, max_values=1, options=options, custom_id="ctf_select_remove")

    async def callback(self, interaction:discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        choice = self.values[0]
        deleted_events = 0
        deleted_custom = 0
        try:
            async with get_db() as session:
                if choice.startswith("event:"):
                    eid = int(choice.split(":")[1])
                    res = await crud.delete_event(session, event_id=[eid])
                    if res == 1:
                        deleted_events = 1
                elif choice.startswith("custom:"):
                    cid = int(choice.split(":")[1])
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
