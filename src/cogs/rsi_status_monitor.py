import discord
from discord import app_commands
from discord.ext import commands, tasks
import logging
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import Dict, Optional
import asyncio

from src.utils.constants import (
    RSI_API,
    STATUS_EMOJIS,
    CACHE_SETTINGS
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
        self.check_status_task.start()
        logger.info("RSI Status Monitor initialized")

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.check_status_task.cancel()

    async def make_request(self, max_retries: int = 3, timeout: int = 30) -> Optional[str]:
        """Make HTTP request with retries and error handling"""
        if not self.bot.session:
            logger.error("HTTP session not initialized")
            return None

        for attempt in range(max_retries):
            try:
                async with self.bot.session.get(
                    RSI_API['STATUS_URL'],
                    timeout=timeout
                ) as response:
                    if response.status == 200:
                        return await response.text()
                        
                    logger.warning(f"Request attempt {attempt + 1} failed: {response.status}")
                    
            except asyncio.TimeoutError:
                logger.warning(f"Request timeout (attempt {attempt + 1}/{max_retries})")
            except Exception as e:
                logger.error(f"Request error on attempt {attempt + 1}: {e}")
                
            if attempt < max_retries - 1:
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
            
            # Calculate end time
            maintenance_end = (
                datetime.combine(datetime.utcnow().date(), maintenance_start) +
                timedelta(hours=RSI_API['MAINTENANCE_DURATION'])
            ).time()
            
            # Handle window crossing midnight
            if maintenance_end < maintenance_start:
                return (now >= maintenance_start or now <= maintenance_end)
            
            return maintenance_start <= now <= maintenance_end

        except Exception as e:
            logger.error(f"Error checking maintenance window: {e}")
            return False

    async def check_status(self) -> Optional[Dict[str, str]]:
        """Check current system status"""
        try:
            # Check Redis cache first
            cached = await self.bot.redis.hgetall('system_status')
            if cached:
                self.system_statuses.update({k.decode(): v.decode() for k, v in cached.items()})
                return self.system_statuses

            # Check maintenance window
            if await self.check_maintenance_window():
                logger.info("Currently in maintenance window, using default status")
                for key in self.system_statuses:
                    self.system_statuses[key] = 'maintenance'
                return self.system_statuses

            # Make request
            content = await self.make_request()
            if not content:
                logger.error("Failed to fetch status page")
                return None

            # Parse status page
            soup = BeautifulSoup(content, 'html.parser')
            status_changed = False

            for component in soup.find_all('div', class_='component'):
                name = component.find('span', class_='name')
                status = component.find('span', class_='component-status')
                
                if not name or not status:
                    continue
                    
                name = name.text.strip().lower()
                status = status.get('data-status', 'unknown')
                
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
                # Update Redis cache
                await self.bot.redis.hmset(
                    'system_status',
                    self.system_statuses
                )
                await self.bot.redis.expire(
                    'system_status',
                    CACHE_SETTINGS['STATUS_TTL']
                )
                
                logger.info(f"Status changed: {self.system_statuses}")

                # Log the status change
                await self.bot.redis.lpush(
                    'status_history',
                    f"{datetime.utcnow().isoformat()}:{str(self.system_statuses)}"
                )
                await self.bot.redis.ltrim('status_history', 0, 99)  # Keep last 100 changes

            return self.system_statuses

        except Exception as e:
            logger.error(f"Error checking status: {e}")
            return None

    def format_status_embed(self) -> discord.Embed:
        """Format current status for Discord embed"""
        try:
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
                
            embed.set_footer(text="Last updated")
            return embed
            
        except Exception as e:
            logger.error(f"Error formatting status embed: {e}")
            raise

    @tasks.loop(minutes=5)
    async def check_status_task(self):
        """Check status periodically"""
        if not self.bot.is_ready():
            return
            
        try:
            # Update status
            current_status = await self.check_status()
            if not current_status:
                return

            # Check if status cog needs updating
            status_cog = self.bot.get_cog('StatusCog')
            if status_cog:
                await status_cog.update_status_channels(current_status)

        except Exception as e:
            logger.error(f"Error in status check task: {e}")

    @check_status_task.before_loop
    async def before_status_check(self):
        """Wait for bot to be ready before starting checks"""
        await self.bot.wait_until_ready()
        
        # Restore cached status
        try:
            cached = await self.bot.redis.hgetall('system_status')
            if cached:
                self.system_statuses.update({k.decode(): v.decode() for k, v in cached.items()})
        except Exception as e:
            logger.error(f"Error restoring cached status: {e}")

    @check_status_task.after_loop
    async def after_status_check(self):
        """Cleanup after status check loop ends"""
        try:
            await self.bot.redis.hmset('system_status', self.system_statuses)
            logger.info("Final status state saved")
        except Exception as e:
            logger.error(f"Error saving final status state: {e}")

    @app_commands.command(
        name="check-status",
        description="Check current RSI system status"
    )
    @app_commands.checks.cooldown(1, 60)  # Once per minute per user
    async def check_status_command(self, interaction: discord.Interaction):
        """Manual status check command"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Check maintenance window
            if await self.check_maintenance_window():
                await interaction.followup.send(
                    content="⚠️ RSI systems are currently in maintenance window.\n"
                           f"Maintenance period: {RSI_API['MAINTENANCE_START']} UTC "
                           f"for {RSI_API['MAINTENANCE_DURATION']} hours.",
                    ephemeral=True
                )
                return

            # Force status check
            current_status = await self.check_status()
            if not current_status:
                await interaction.followup.send(
                    "❌ Unable to fetch system status. Please try again later.",
                    ephemeral=True
                )
                return
            
            # Create and send embed
            embed = self.format_status_embed()
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in check_status command: {e}")
            await interaction.followup.send(
                "❌ An error occurred while checking system status.",
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
            await interaction.response.send_message(
                "❌ An error occurred while processing the command.",
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