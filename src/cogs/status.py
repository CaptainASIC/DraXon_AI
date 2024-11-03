import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import discord
from discord import app_commands
from discord.ext import commands, tasks
import logging
from typing import Dict, Optional
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import json

from src.utils.constants import (
    CHANNELS_CONFIG,
    STATUS_EMOJIS,
    CACHE_SETTINGS,
    RSI_API
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
            # Check maintenance window first
            if await self.check_maintenance_window():
                logger.info("Currently in maintenance window")
                for key in self.system_statuses:
                    self.system_statuses[key] = 'maintenance'
                return self.system_statuses

            # Check Redis cache
            cached = await self.bot.redis.hgetall('system_status')
            if cached:
                # Convert bytes to str if needed
                cached_statuses = {
                    k.decode() if isinstance(k, bytes) else k: 
                    v.decode() if isinstance(v, bytes) else v 
                    for k, v in cached.items()
                }
                self.system_statuses.update(cached_statuses)
                logger.debug(f"Using cached status: {self.system_statuses}")
                return self.system_statuses

            # Fetch status page
            logger.info("Fetching RSI status page")
            async with self.bot.session.get(RSI_API['STATUS_URL']) as response:
                if response.status != 200:
                    logger.error(f"Status page request failed: {response.status}")
                    response_text = await response.text()
                    logger.error(f"Response content: {response_text}")
                    return None

                content = await response.text()
                soup = BeautifulSoup(content, 'html.parser')
                status_changed = False

                for component in soup.find_all('div', class_='component'):
                    name = component.find('span', class_='name')
                    status = component.find('span', class_='component-status')
                    
                    if not name or not status:
                        continue
                        
                    name = name.text.strip().lower()
                    status = status.get('data-status', 'unknown')
                    logger.debug(f"Found component: {name} with status: {status}")
                    
                    # Map component to our tracking
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
                    logger.info(f"Status changed, updating cache: {self.system_statuses}")
                    # Update Redis cache
                    await self.bot.redis.delete('system_status')  # Clear existing hash
                    await self.bot.redis.hmset('system_status', self.system_statuses)
                    await self.bot.redis.expire('system_status', CACHE_SETTINGS['STATUS_TTL'])
                    
                    # Store in history
                    history_entry = {
                        'timestamp': datetime.utcnow().isoformat(),
                        'statuses': self.system_statuses.copy()
                    }
                    await self.bot.redis.lpush(
                        'status_history',
                        json.dumps(history_entry)
                    )
                    await self.bot.redis.ltrim('status_history', 0, 99)  # Keep last 100 entries

                self.last_check = datetime.utcnow()
                return self.system_statuses

        except Exception as e:
            logger.error(f"Error checking status: {e}")
            return None

    def format_status_embed(self) -> discord.Embed:
        """Format current status for Discord embed"""
        embed = discord.Embed(
            title="🖥️ RSI System Status",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        
        for system, status in self.system_statuses.items():
            emoji = STATUS_EMOJIS.get(status, '❓')
            system_name = system.replace('-', ' ').title()
            embed.add_field(
                name=system_name,
                value=f"{emoji} {status.title()}",
                inline=False
            )
        
        if self.last_check:
            embed.set_footer(text=f"Last checked: {self.last_check.strftime('%Y-%m-%d %H:%M:%S')} UTC")
            
        return embed

    @tasks.loop(minutes=5)
    async def check_status_task(self):
        """Check status periodically"""
        if not self.bot.is_ready():
            return
            
        try:
            # Update status
            current_status = await self.check_status()
            if not current_status:
                logger.warning("Failed to get current status")
                return

            # Check if status cog needs updating
            status_cog = self.bot.get_cog('StatusCog')
            if status_cog:
                await status_cog.update_status_channels(current_status)
            else:
                logger.debug("StatusCog not found, skipping channel updates")

        except Exception as e:
            logger.error(f"Error in status check task: {e}")

    @check_status_task.before_loop
    async def before_status_check(self):
        """Setup before starting status check loop"""
        await self.bot.wait_until_ready()
        logger.info("Starting status check loop")
        
        # Restore cached status
        try:
            cached = await self.bot.redis.hgetall('system_status')
            if cached:
                cached_statuses = {
                    k.decode() if isinstance(k, bytes) else k: 
                    v.decode() if isinstance(v, bytes) else v 
                    for k, v in cached.items()
                }
                self.system_statuses.update(cached_statuses)
                logger.info("Restored cached status")
        except Exception as e:
            logger.error(f"Error restoring cached status: {e}")

    @check_status_task.after_loop
    async def after_status_check(self):
        """Cleanup after status check loop ends"""
        try:
            if self.system_statuses:
                await self.bot.redis.hmset('system_status', self.system_statuses)
                logger.info("Saved final status to cache")
        except Exception as e:
            logger.error(f"Error saving final status: {e}")

    @app_commands.command(
        name="check-status",
        description="Check current RSI system status"
    )
    async def check_status_command(self, interaction: discord.Interaction):
        """Manual status check command"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Check maintenance window
            if await self.check_maintenance_window():
                await interaction.followup.send(
                    "⚠️ RSI systems are currently in maintenance window.\n"
                    f"Maintenance period: {RSI_API['MAINTENANCE_START']} UTC "
                    f"for {RSI_API['MAINTENANCE_DURATION']} hours.",
                    ephemeral=True
                )
                return

            # Force status check
            current_status = await self.check_status()
            if not current_status:
                await interaction.followup.send(
                    "Unable to fetch system status. Please try again later.",
                    ephemeral=True
                )
                return
            
            # Create and send embed
            embed = self.format_status_embed()
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in check_status command: {e}")
            await interaction.followup.send(
                "❌ Error checking system status.",
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
