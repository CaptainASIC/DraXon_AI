import discord
from discord import app_commands
from discord.ext import commands
import logging
import asyncpg
import redis.asyncio as redis
from typing import Optional, Dict, Any
import ssl
import certifi

from src.utils.constants import APP_VERSION, BOT_REQUIRED_PERMISSIONS

logger = logging.getLogger('DraXon_AI')

class DraXonAIBot(commands.Bot):
    """Main bot class for DraXon AI"""
    
    def __init__(self, 
                 db_pool: asyncpg.Pool,
                 redis_pool: redis.Redis,
                 ssl_context: Optional[ssl.SSLContext] = None,
                 *args, **kwargs):
        """Initialize the bot with database and Redis connections"""
        # Set up intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        
        # Initialize base bot
        super().__init__(
            command_prefix='!',
            intents=intents,
            *args, 
            **kwargs
        )
        
        # Store connections
        self.db = db_pool
        self.redis = redis_pool
        self.ssl_context = ssl_context
        
        # Internal state
        self._ready = False
        self._cogs_loaded = False
        
        # Channel IDs storage
        self.incidents_channel_id: Optional[int] = None
        self.promotion_channel_id: Optional[int] = None
        self.demotion_channel_id: Optional[int] = None
        self.reminder_channel_id: Optional[int] = None
        
        logger.info("Bot initialized")

    async def setup_hook(self):
        """Initial setup when bot starts"""
        logger.info("Setup hook starting...")
        try:
            # Define all cogs to load
            cogs = [
                'src.cogs.channels',
                'src.cogs.status',
                'src.cogs.members',
                'src.cogs.promotion',
                'src.cogs.commands',
                'src.cogs.rsi_status_monitor',
                'src.cogs.rsi_incidents_monitor',
                'src.cogs.backup',
                'src.cogs.rsi_integration',
                'src.cogs.membership_monitor'
            ]
            
            # Load each cog
            for cog in cogs:
                try:
                    if cog not in self.extensions:
                        await self.load_extension(cog)
                        logger.info(f"Loaded {cog}")
                    else:
                        logger.info(f"Skipped loading {cog} (already loaded)")
                except Exception as e:
                    logger.error(f"Failed to load {cog}: {e}")
                    raise
            
            self._cogs_loaded = True
            logger.info("All cogs loaded")
            
            # Sync command tree
            await self.tree.sync()
            logger.info("Command tree synced")
            
            # Load stored channel IDs from Redis
            await self._load_channel_ids()
            
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}")
            raise

    async def _load_channel_ids(self):
        """Load stored channel IDs from Redis"""
        try:
            channel_ids = await self.redis.hgetall('channel_ids')
            if channel_ids:
                self.incidents_channel_id = int(channel_ids.get(b'incidents', 0)) or None
                self.promotion_channel_id = int(channel_ids.get(b'promotion', 0)) or None
                self.demotion_channel_id = int(channel_ids.get(b'demotion', 0)) or None
                self.reminder_channel_id = int(channel_ids.get(b'reminder', 0)) or None
                logger.info("Loaded channel IDs from Redis")
        except Exception as e:
            logger.error(f"Error loading channel IDs: {e}")

    async def _save_channel_ids(self):
        """Save channel IDs to Redis"""
        try:
            await self.redis.hmset('channel_ids', {
                'incidents': str(self.incidents_channel_id or 0),
                'promotion': str(self.promotion_channel_id or 0),
                'demotion': str(self.demotion_channel_id or 0),
                'reminder': str(self.reminder_channel_id or 0)
            })
            logger.info("Saved channel IDs to Redis")
        except Exception as e:
            logger.error(f"Error saving channel IDs: {e}")

    async def close(self):
        """Cleanup when bot shuts down"""
        logger.info("Bot shutting down, cleaning up...")
        try:
            # Save channel IDs before shutdown
            await self._save_channel_ids()
            
            # Close connections
            if hasattr(self, 'db'):
                await self.db.close()
            if hasattr(self, 'redis'):
                await self.redis.close()
                
            await super().close()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            raise

    async def on_ready(self):
        """Handle bot ready event"""
        if self._ready:
            return
            
        logger.info(f'DraXon AI Bot v{APP_VERSION} has connected to Discord!')
        try:
            # Set custom activity
            activity = discord.CustomActivity(
                name=f"Ver. {APP_VERSION} Processing..."
            )
            await self.change_presence(activity=activity)
            logger.info("Bot activity status set successfully")
            
            # Mark as ready
            self._ready = True
            
        except Exception as e:
            logger.error(f"Error in on_ready: {e}")

    async def on_command_error(self, ctx, error):
        """Global error handler for commands"""
        if isinstance(error, commands.errors.MissingRole):
            await ctx.send("❌ You don't have permission to use this command.")
        else:
            logger.error(f"Command error: {error}")
            await ctx.send("❌ An error occurred while processing the command.")

    async def on_app_command_error(self, 
                                 interaction: discord.Interaction, 
                                 error: app_commands.AppCommandError):
        """Global error handler for application commands"""
        if isinstance(error, app_commands.errors.MissingRole):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True
            )
        else:
            logger.error(f"Application command error: {error}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ An error occurred while processing the command.",
                    ephemeral=True
                )

    def get_guild_permissions(self, guild: discord.Guild) -> Dict[str, bool]:
        """Get bot's permissions in a guild"""
        permissions = guild.me.guild_permissions
        return {perm: getattr(permissions, perm) for perm in BOT_REQUIRED_PERMISSIONS}

    async def verify_permissions(self, guild: discord.Guild) -> tuple[bool, list[str]]:
        """Verify bot has required permissions in guild"""
        permissions = self.get_guild_permissions(guild)
        missing = [perm for perm, has_perm in permissions.items() if not has_perm]
        return not bool(missing), missing