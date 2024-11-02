import discord
from discord import app_commands
from discord.ext import commands, tasks
import logging
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Dict, Optional

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

    async def check_status(self) -> Dict[str, str]:
        """Check current system status"""
        try:
            # Check Redis cache first
            cached = await self.bot.redis.hgetall('system_status')
            if cached:
                self.system_statuses.update(cached)
                return self.system_statuses

            # Fetch status page
            async with self.bot.session.get(RSI_API['STATUS_URL']) as response:
                if response.status != 200:
                    logger.error(f"Status page request failed: {response.status}")
                    return self.system_statuses

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

                return self.system_statuses

        except Exception as e:
            logger.error(f"Error checking status: {e}")
            return self.system_statuses

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
        cached = await self.bot.redis.hgetall('system_status')
        if cached:
            self.system_statuses.update(cached)

    @check_status_task.after_loop
    async def after_status_check(self):
        """Cleanup after status check loop ends"""
        await self.bot.redis.hmset('system_status', self.system_statuses)

    @app_commands.command(
        name="check-status",
        description="Check current RSI system status"
    )
    async def check_status_command(self, interaction: discord.Interaction):
        """Manual status check command"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Force status check
            await self.check_status()
            
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