from typing import List, Dict, Any
from datetime import datetime, timedelta
import logging

import discord
from discord.ext import commands, tasks

from src.config import settings
from src.database.database import get_db
from src.database.model import Event
from src.utils.ctf_api import fetch_ctf_events
from src.utils.embed_creator import create_event_embed
from src.utils.join_channel import join_request, join_channel, set_private
from src.utils.join_channel import get_info_channel_for_category
from src.utils.get_channel import get_announcement_channel
import src.crud.event as crud_event
import src.crud.custom_event as crud_custom_event

# logging
logger = logging.getLogger(__name__)

# cog
class CTFBGTask(commands.Cog):
    def __init__(self, bot:commands.Bot):
        self.bot:commands.Bot = bot
        
    @commands.Cog.listener()
    async def on_ready(self):
        # start background task
        self.task_checks.start()
        
    # background task
    @tasks.loop(minutes=settings.CHECK_INTERVAL_MINUTES)
    async def task_checks(self):
        # get channel
        channel:discord.TextChannel = await get_announcement_channel(self.bot)
        
        # 1. get new events
        async with get_db() as session:
            all_events = await fetch_ctf_events()
            
            known_events = await crud_event.read_event(session)
            known_events_id = [ event.event_id for event in known_events ]
        
            new_events_db:List[Event] = [] # new events data for database
            new_events_ctftime:List[Dict[str, Any]] = [] # new events data from CTFTime
            for event in all_events:
                event_id = event["id"]
                if event_id not in known_events_id: # new event
                    new_events_db.append(Event(
                        event_id=event_id,
                        title=event["title"],
                        start=datetime.fromisoformat(event["start"]).timestamp(),
                        finish=datetime.fromisoformat(event["finish"]).timestamp(),
                    ))
                    
                    new_events_ctftime.append(event)
                    
            if len(new_events_db) > 0:
                await crud_event.create_events(session, new_events_db)
            
            for event in new_events_ctftime:
                embed = await create_event_embed(event, "有新的 CTF 競賽！")

                view = discord.ui.View(timeout=None)
                view.add_item(
                    discord.ui.Button(
                        label='Join',
                        style=discord.ButtonStyle.blurple,
                        custom_id=f"ctf_join_channel:event:event:{event['id']}",
                        emoji=settings.EMOJI,
                    )
                )
                view.add_item(
                    discord.ui.Button(
                        label='Set Private',
                        style=discord.ButtonStyle.gray,
                        custom_id=f"ctf_join_channel:private:event:{event['id']}",
                        )
                )
                try:
                    await channel.send(embed=embed, view=view)
                    logger.info(f"Sent new event notification: {event['title']}")
                except Exception as e:
                    logger.error(f"Failed to send notification: {e}")
            
        # 2. detect updates
        # - event updates
        # - event removed
        # - custom channel removed
        known_events.extend(new_events_db)
        async with get_db() as session:
            # check events
            for event in known_events:
                events_api = await fetch_ctf_events(event.event_id)
                if len(events_api) != 1:
                    # event removed
                    logger.info(f"Detected: {event.title} (event_id={event.event_id}) was removed")
                    
                    await crud_event.delete_event(session, event_id=[event.event_id])
                    
                    embed = discord.Embed(
                        color=discord.Color.red(),
                        title=f"{event.title} was removed",
                        footer=discord.EmbedFooter(text=f"Event ID: {event.event_id} | CTFtime.org")
                    )
                    # send notification to announcement channel
                    await channel.send(embed=embed)
                    # send notification to event info channel if category exists
                    if event.category_id:
                        info_ch = await get_info_channel_for_category(self.bot, event.category_id)
                        if info_ch:
                            await info_ch.send(embed=embed)
                else: 
                    # check update
                    event_api = events_api[0]
                    ntitle = event_api["title"]
                    nstart = datetime.fromisoformat(event_api["start"]).timestamp()
                    nfinish = datetime.fromisoformat(event_api["finish"]).timestamp()
                    
                    if event.title != ntitle or \
                        event.start != nstart or event.finish != nfinish:
                        # update detected
                        logger.info(f"Detected: {ntitle} (old: {event.title}) (event_id={event.event_id}) was updated")
                        
                        await crud_event.update_event(session, event_id=event.event_id,
                                          title=ntitle,
                                          start=nstart,
                                          finish=nfinish)
                        
                        embed = await create_event_embed(event_api, title="Update detected")
                        # send notification to announcement channel
                        await channel.send(embed=embed)
                        # send notification to event info channel if category exists
                        if event.category_id:
                            info_ch = await get_info_channel_for_category(self.bot, event.category_id)
                            if info_ch:
                                await info_ch.send(embed=embed)
                    
    @task_checks.before_loop
    async def before_task_checks(self):
        await self.bot.wait_until_ready()


    def cog_unload(self):
        self.task_checks.cancel()
    

    # interaction handler
    @commands.Cog.listener()
    async def on_interaction(self, interaction:discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        
        custom_id = interaction.data.get("custom_id")
        if custom_id is None:
            return
        
        if custom_id.startswith("ctf_join_channel:event:"):
            try:
                _ = custom_id.split(":")
                event_type = str(_[2])
                event_id:int = int(_[3])
            except:
                await interaction.response.send_message("Invalid arguments", ephemeral=True)
                return
            
            await join_request(self.bot, interaction, f"{event_type}:{event_id}")

        if custom_id.startswith("ctf_join_channel:private:"):
            try:
                _ = custom_id.split(":")
                event_type = str(_[2])
                event_id:int = int(_[3])
            except:
                await interaction.response.send_message("Invalid arguments", ephemeral=True)
                return
            
            if not await set_private(self.bot, interaction, f"{event_type}:{event_id}"):
                return

            async with get_db() as session:
                events = []
                if event_type == "event":
                    events = await crud_event.read_event(session, event_id=[event_id])
                elif event_type == "custom":
                    events = await crud_custom_event.read_event(session, event_id=[event_id])
                if len(events) != 1:
                    await interaction.followup.send(content="Invalid event", ephemeral=True)
                    return
                event = events[0]

                view = discord.ui.View(timeout=None)
                view.add_item(
                    discord.ui.Button(
                        label='Join',
                        style=discord.ButtonStyle.blurple,
                        custom_id=f"ctf_join_channel:event:{event_type}:{event_id}",
                        emoji=settings.EMOJI,
                    )
                )
                view.add_item(
                    discord.ui.Button(
                        label=f'Set {"Public" if event.is_private else "Private"}',
                        style=discord.ButtonStyle.gray,
                        custom_id=f"ctf_join_channel:private:{event_type}:{event_id}",
                        )
                )
                await interaction.response.edit_message(view=view)
    
        if custom_id.startswith("ctf_info:private:"):
            try:
                _ = custom_id.split(":")
                event_type = str(_[2])
                event_id:int = int(_[3])
            except:
                await interaction.response.send_message("Invalid arguments", ephemeral=True)
                return
            
            await set_private(self.bot, interaction, f"{event_type}:{event_id}")

            async with get_db() as session:
                events = []
                if event_type == "event":
                    events = await crud_event.read_event(session, event_id=[event_id])
                elif event_type == "custom":
                    events = await crud_custom_event.read_event(session, event_id=[event_id])
                if len(events) != 1:
                    await interaction.followup.send(content="Invalid event", ephemeral=True)
                    return
                event = events[0]

                view = discord.ui.View(timeout=None)
                view.add_item(
                    discord.ui.Button(
                        label=f'Set {"Public" if event.is_private else "Private"}',
                        style=discord.ButtonStyle.gray,
                        custom_id=f"ctf_info:private:{event_type}:{event_id}",
                        )
                )
                await interaction.response.edit_message(view=view)

        # Admin approval handlers
        if custom_id.startswith("ctf_admin_approve:join:"):
            try: # custom_id=f"ctf_admin_approve:join:{event_type}:{event_id}:{guild_id}:{user_id}",
                _ = custom_id.split(":")
                event_type = _[2]  # event/custom
                event_id = int(_[3])
                guild_id = int(_[4])
                user_id = int(_[5])
            except Exception:
                await interaction.response.send_message("Invalid arguments", ephemeral=True)
                return

            # Only admins can approve
            try:
                if not getattr(interaction.user, "guild_permissions", None) or not interaction.user.guild_permissions.administrator:
                    await interaction.response.send_message(content="你沒有權限使用此功能（需要 Administrator）", ephemeral=True)
                    return
            except Exception:
                await interaction.response.send_message(content="權限檢查失敗，請於伺服器中使用此功能", ephemeral=True)
                return

            await join_channel(self.bot, interaction, f"{event_type}:{event_id}", guild_id, user_id, True)

        if custom_id.startswith("ctf_admin_reject:join:"):
            # Only admins can reject
            try:
                if not getattr(interaction.user, "guild_permissions", None) or not interaction.user.guild_permissions.administrator:
                    await interaction.response.send_message(content="你沒有權限使用此功能（需要 Administrator）", ephemeral=True)
                    return
            except Exception:
                await interaction.response.send_message(content="權限檢查失敗，請於伺服器中使用此功能", ephemeral=True)
                return

            try:
                await interaction.response.edit_message(content="Rejected by admin", view=None)
            except Exception:
                await interaction.followup.send(content="Rejected by admin")
            return
    
        return
    

def setup(bot:commands.Bot):
    bot.add_cog(CTFBGTask(bot))
