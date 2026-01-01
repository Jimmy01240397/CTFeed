import discord
from discord.ext import commands
import logging

from src.config import settings

logger = logging.getLogger(__name__)

# utils
async def get_announcement_channel(bot:commands.Bot) -> discord.TextChannel:
    channel_name = settings.ANNOUNCEMENT_CHANNEL_NAME
    
    channel = None
    for guild in bot.guilds:
        for text_channel in guild.text_channels:
            if text_channel.name.lower() == channel_name.lower():
                channel = text_channel
                break
        if channel:
            break

    if not channel:
        logger.error(f"Can't find channel named '{channel_name}'")
        logger.error(f"Please check:")
        logger.error(f"1. Channel name is correct: {channel_name}")
        logger.error(f"2. Bot has permission to view the channel")
        logger.error(f"3. The channel exists in the server where the Bot is located")
        await bot.close()
        return
    
    return channel
