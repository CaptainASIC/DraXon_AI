import discord
from discord import app_commands
from discord.ext import commands, tasks
import logging
from datetime import datetime
from typing import Dict, Optional

from src.utils.constants import CHANNELS_CONFIG

logger = logging.getLogger('DraXon_OCULUS')

class MembersCog(commands.Cog):
    """Cog for handling member count tracking and statistics"""
    
    def __init__(self, bot):
        self.bot = bot
        self._task_started = False
        self.update_member_counts.start()
        logger.info("Members cog initialized")

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.update_member_counts.cancel()

    async def get_count_cache(self, guild_id: int, count_type: str) -> Optional[int]:
        """Get cached count from Redis"""
        try:
            cached = await self.bot.redis.get(f'count:{guild_id}:{count_type}')
            return int(cached) if cached else None
        except Exception as e:
            logger.error(f"Error getting count cache: {e}")
            return None

    async def set_count_cache(self, guild_id: int, count_type: str, count: int):
        """Set count cache in Redis"""
        try:
            await self.bot.redis.set(
                f'count:{guild_id}:{count_type}',
                str(count),
                ex=300  # 5 minutes
            )
        except Exception as e:
            logger.error(f"Error setting count cache: {e}")

    async def calculate_counts(self, guild: discord.Guild) -> Dict[str, int]:
        """Calculate member and bot counts"""
        counts = {}
        try:
            # Get cached counts
            members_cache = await self.get_count_cache(guild.id, 'members')
            bots_cache = await self.get_count_cache(guild.id, 'bots')

            if members_cache is None or bots_cache is None:
                # Calculate new counts
                counts['members'] = len([m for m in guild.members if not m.bot])
                
                bot_role = discord.utils.get(guild.roles, name="Bots")
                counts['bots'] = len(bot_role.members) if bot_role else 0

                # Cache new counts
                await self.set_count_cache(guild.id, 'members', counts['members'])
                await self.set_count_cache(guild.id, 'bots', counts['bots'])
            else:
                counts['members'] = members_cache
                counts['bots'] = bots_cache

        except Exception as e:
            logger.error(f"Error calculating counts: {e}")
            counts = {'members': 0, 'bots': 0}

        return counts

    @tasks.loop(minutes=5)
    async def update_member_counts(self):
        """Update member count channels periodically"""
        if not self.bot.is_ready():
            return
            
        logger.info("Starting member count update cycle")
        channels_cog = self.bot.get_cog('ChannelsCog')
        if not channels_cog:
            logger.error("ChannelsCog not found")
            return
        
        for guild in self.bot.guilds:
            try:
                category = await channels_cog.get_category(guild)
                if not category:
                    logger.warning(f"No DraXon OCULUS category found in {guild.name}")
                    continue

                logger.info(f"Updating counts for guild: {guild.name}")
                
                # Get current counts
                counts = await self.calculate_counts(guild)

                # Update each count channel
                for config in CHANNELS_CONFIG:
                    if config["count_type"] not in ["members", "bots"]:
                        continue

                    display_start = config["display"].split(':')[0]
                    logger.info(f"Looking for channel starting with: {display_start}")
                    
                    matching_channels = [
                        ch for ch in category.voice_channels 
                        if ch.name.startswith(display_start)
                    ]
                    
                    if not matching_channels:
                        continue
                        
                    channel = matching_channels[0]
                    count = counts[config["count_type"]]
                    
                    new_name = channels_cog.get_channel_name(config, count=count)
                    
                    if channel.name != new_name:
                        try:
                            await channel.edit(name=new_name)
                            logger.info(f"Updated {channel.name} to {new_name}")
                            
                            # Log the change
                            await self.bot.redis.lpush(
                                f'count_history:{guild.id}:{config["count_type"]}',
                                f"{datetime.utcnow().isoformat()}:{count}"
                            )
                            # Keep only last 100 entries
                            await self.bot.redis.ltrim(
                                f'count_history:{guild.id}:{config["count_type"]}',
                                0, 99
                            )
                            
                        except Exception as e:
                            logger.error(f"Failed to update channel name: {e}")

            except Exception as e:
                logger.error(f"Error updating member counts in {guild.name}: {e}")

        logger.info("Member count update cycle completed")

    @update_member_counts.before_loop
    async def before_member_update(self):
        """Setup before starting the update loop"""
        await self.bot.wait_until_ready()

    @update_member_counts.after_loop
    async def after_member_update(self):
        """Cleanup after update loop ends"""
        logger.info("Member count update loop ended")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Handle member join events"""
        try:
            # Invalidate cache
            await self.bot.redis.delete(f'count:{member.guild.id}:members')
            # Force immediate update
            await self.update_member_counts()
        except Exception as e:
            logger.error(f"Error handling member join: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Handle member remove events"""
        try:
            # Invalidate cache
            await self.bot.redis.delete(f'count:{member.guild.id}:members')
            # Force immediate update
            await self.update_member_counts()
        except Exception as e:
            logger.error(f"Error handling member remove: {e}")

async def setup(bot):
    """Safe setup function for members cog"""
    try:
        if not bot.get_cog('MembersCog'):
            await bot.add_cog(MembersCog(bot))
            logger.info('Members cog loaded successfully')
        else:
            logger.info('Members cog already loaded, skipping')
    except Exception as e:
        logger.error(f'Error loading members cog: {e}')
        raise
