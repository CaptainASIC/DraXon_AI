import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import discord
from discord import app_commands
from discord.ext import commands, tasks
import logging
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
import asyncio
import json
import aiohttp

from src.utils.constants import (
    RSI_API,
    STATUS_EMOJIS,
    CACHE_SETTINGS,
    CHANNELS_CONFIG
)

logger = logging.getLogger('DraXon_AI')

class RSIStatusMonitorCog(commands.Cog):
    """Monitor RSI platform status"""
    
    def __init__(self, bot):
        self.bot = bot
        self.system_statuses = {
            'platform': 'operational',
            'persistent-universe': 'operational',
            'electronic-access': 'operational'
        }
        self.last_check = None
        self.check_status_task.start()
        logger.info("RSI Status Monitor initialized")

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        try:
            self.check_status_task.cancel()
            logger.info("Status monitor tasks cancelled")
        except Exception as e:
            logger.error(f"Error unloading status monitor: {e}")

    async def make_request(self, url: str = None, timeout: int = 30) -> Optional[str]:
        """Make HTTP request with retries and error handling"""
        if not hasattr(self.bot, 'session') or not self.bot.session:
            logger.error("HTTP session not initialized")
            return None

        request_url = url or RSI_API['STATUS_URL']
        
        for attempt in range(3):  # 3 retries
            try:
                async with self.bot.session.get(
                    request_url,
                    timeout=timeout
                ) as response:
                    if response.status == 200:
                        return await response.text()
                    logger.warning(f"Request to {request_url} failed with status {response.status}")
            except asyncio.TimeoutError:
                logger.warning(f"Request timeout on attempt {attempt + 1}")
            except aiohttp.ClientError as e:
                logger.error(f"HTTP client error: {str(e)}")
            except Exception as e:
                logger.error(f"Unexpected error making request: {str(e)}")
            
            if attempt < 2:  # Don't sleep on last attempt
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        return None

    async def check_maintenance_window(self) -> bool:
        """Check if currently in maintenance window"""
        try:
            now = datetime.utcnow().time()
            maintenance_start = datetime.strptime(
                RSI_API['MAINTENANCE_START'], 
                "%H:%M"
            ).time()
            
            maintenance_end = (
                datetime.combine(datetime.utcnow().date(), maintenance_start) +
                timedelta(hours=RSI_API['MAINTENANCE_DURATION'])
            ).time()
            
            if maintenance_end < maintenance_start:
                return (now >= maintenance_start or now <= maintenance_end)
            
            return maintenance_start <= now <= maintenance_end

        except Exception as e:
            logger.error(f"Error checking maintenance window: {e}")
            return False

    async def check_status(self) -> Optional[Dict[str, str]]:
        """Check current system status"""
        try:
            # Check cache first
            cached = await self.bot.redis.get('system_status')
            if cached:
                self.system_statuses = json.loads(cached)
                return self.system_statuses

            # Check maintenance window
            if await self.check_maintenance_window():
                for key in self.system_statuses:
                    self.system_statuses[key] = 'maintenance'
                return self.system_statuses

            content = await self.make_request()
            if not content:
                return None

            soup = BeautifulSoup(content, 'html.parser')
            status_changed = False

            for component in soup.find_all('div', class_='component'):
                name = component.find('span', class_='name')
                status = component.find('span', class_='component-status')
                
                if not name or not status:
                    continue
                    
                name = name.text.strip().lower()
                status = status.get('data-status', 'unknown')
                
                if 'platform' in name:
                    if self.system_statuses['platform'] != status:
                        status_changed = True
                    self.system_statuses['platform'] = status
                elif 'persistent universe' in name:
                    if self.system_statuses['persistent-universe'] != status:
                        status_changed = True
                    self.system_statuses['persistent-universe'] = status
                elif 'arena commander' in name:
                    if self.system_statuses['electronic-access'] != status:
                        status_changed = True
                    self.system_statuses['electronic-access'] = status

            if status_changed:
                # Cache the new status
                await self.bot.redis.set(
                    'system_status',
                    json.dumps(self.system_statuses),
                    ex=CACHE_SETTINGS['STATUS_TTL']
                )
                
                # Record the status change
                await self.record_status_change()
                logger.info(f"Status changed: {self.system_statuses}")

            return self.system_statuses

        except Exception as e:
            logger.error(f"Error checking status: {str(e)}")
            return None

    async def record_status_change(self):
        """Record status change in history"""
        try:
            timestamp = datetime.utcnow().isoformat()
            history_entry = {
                'timestamp': timestamp,
                'statuses': self.system_statuses.copy()
            }
            
            await self.bot.redis.lpush(
                'status_history',
                json.dumps(history_entry)
            )
            
            # Keep last 100 entries
            await self.bot.redis.ltrim('status_history', 0, 99)
        except Exception as e:
            logger.error(f"Error recording status change: {e}")

    def format_status_embed(self) -> discord.Embed:
        """Format current status for Discord embed"""
        try:
            embed = discord.Embed(
                title="🖥️ RSI System Status",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            for system, status in self.system_statuses.items():
                emoji = STATUS_EMOJIS.get(status, STATUS_EMOJIS['unknown'])
                system_name = system.replace('-', ' ').title()
                embed.add_field(
                    name=system_name,
                    value=f"{emoji} {status.title()}",
                    inline=False
                )
            
            if self.last_check:
                embed.set_footer(text=f"Last checked: {self.last_check.strftime('%Y-%m-%d %H:%M:%S')} UTC")
            
            return embed
        except Exception as e:
            logger.error(f"Error formatting status embed: {e}")
            raise

    async def update_status_channels(self, guild: discord.Guild):
        """Update status display channels"""
        try:
            channels_cog = self.bot.get_cog('ChannelsCog')
            if not channels_cog:
                logger.error("ChannelsCog not found")
                return

            category = await channels_cog.get_category(guild)
            if not category:
                logger.error("Category not found")
                return

            # Get status channel configs
            status_channels = [
                config for config in CHANNELS_CONFIG 
                if config["count_type"] == "status"
            ]

            for channel in category.voice_channels:
                # Find matching config for this channel
                config = next(
                    (c for c in status_channels 
                     if c["name"].lower() in channel.name.lower()),
                    None
                )
                
                if not config:
                    continue

                # Extract system name from config
                system = config["name"].replace("-status", "")
                
                if system in self.system_statuses:
                    status = self.system_statuses[system]
                    emoji = STATUS_EMOJIS.get(status, STATUS_EMOJIS['unknown'])
                    
                    # Use the display format from config
                    new_name = config["display"].format(emoji=emoji)
                    
                    if channel.name != new_name:
                        try:
                            await channel.edit(name=new_name)
                            logger.info(f"Updated status channel: {new_name}")
                        except Exception as e:
                            logger.error(f"Error updating channel {channel.name}: {e}")

        except Exception as e:
            logger.error(f"Error updating status channels: {e}")

    @tasks.loop(minutes=5)
    async def check_status_task(self):
        """Check status periodically"""
        if not self.bot.is_ready():
            return

        try:
            current_status = await self.check_status()
            if current_status:
                self.last_check = datetime.utcnow()
                
                # Update status channels in all guilds
                for guild in self.bot.guilds:
                    await self.update_status_channels(guild)

        except Exception as e:
            logger.error(f"Error in status check task: {e}")

    @check_status_task.before_loop
    async def before_status_check(self):
        """Setup before starting the status check loop"""
        await self.bot.wait_until_ready()
        logger.info("Starting status check loop")

    @check_status_task.after_loop
    async def after_status_check(self):
        """Cleanup after status check loop ends"""
        try:
            if self.system_statuses:
                await self.bot.redis.set(
                    'system_status',
                    json.dumps(self.system_statuses),
                    ex=CACHE_SETTINGS['STATUS_TTL']
                )
            logger.info("Status check loop ended")
        except Exception as e:
            logger.error(f"Error in status check cleanup: {e}")

    @app_commands.command(
        name="check-status",
        description="Check current RSI system status"
    )
    @app_commands.checks.cooldown(1, 60)  # Once per minute per user
    async def check_status_command(self, interaction: discord.Interaction):
        """Manual status check command"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            if await self.check_maintenance_window():
                await interaction.followup.send(
                    "⚠️ RSI systems are currently in maintenance window.\n"
                    f"Maintenance period: {RSI_API['MAINTENANCE_START']} UTC "
                    f"for {RSI_API['MAINTENANCE_DURATION']} hours.",
                    ephemeral=True
                )
                return

            current_status = await self.check_status()
            
            if not current_status:
                await interaction.followup.send(
                    "Unable to fetch system status. Please try again later.",
                    ephemeral=True
                )
                return
            
            embed = self.format_status_embed()
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in check_status command: {e}")
            await interaction.followup.send(
                "An error occurred while checking the status.",
                ephemeral=True
            )

    @app_commands.command(
        name="status-history",
        description="View RSI status change history"
    )
    async def status_history_command(self, interaction: discord.Interaction):
        """View status change history"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            history = await self.bot.redis.lrange('status_history', 0, 9)  # Get last 10 changes
            
            if not history:
                await interaction.followup.send(
                    "No status change history available.",
                    ephemeral=True
                )
                return
            
            embed = discord.Embed(
                title="📊 RSI Status History",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            for entry in history:
                data = json.loads(entry)
                timestamp = datetime.fromisoformat(data['timestamp'])
                statuses = data['statuses']
                
                status_text = "\n".join(
                    f"{STATUS_EMOJIS.get(status, '❓')} {system.replace('-', ' ').title()}: {status.title()}"
                    for system, status in statuses.items()
                )
                
                embed.add_field(
                    name=timestamp.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    value=status_text,
                    inline=False
                )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in status history command: {e}")
            await interaction.followup.send(
                "An error occurred while fetching status history.",
                ephemeral=True
            )

    async def cog_app_command_error(self, 
                                  interaction: discord.Interaction,
                                  error: app_commands.AppCommandError):
        """Handle application command errors"""
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"⏳ Command on cooldown. Try again in {error.retry_after:.0f} seconds.",
                ephemeral=True
            )
        else:
            logger.error(f"Command error: {error}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "An error occurred while processing the command.",
                    ephemeral=True
                )

async def setup(bot):
    """Safe setup function for RSI status monitor cog"""
    try:
        if not bot.get_cog('RSIStatusMonitorCog'):
            await bot.add_cog(RSIStatusMonitorCog(bot))
            logger.info('RSI Status Monitor cog loaded successfully')
        else:
            logger.info('RSI Status Monitor cog already loaded, skipping')
    except Exception as e:
        logger.error(f'Error loading RSI Status Monitor cog: {e}')
        raise
