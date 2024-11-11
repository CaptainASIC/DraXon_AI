import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import discord
from discord import app_commands
from discord.ext import commands
import logging
import asyncpg
import redis.asyncio as redis
from typing import Optional, Dict, Any, Tuple, List
import ssl
from datetime import datetime
import aiohttp
import json

from src.utils.constants import (
    APP_VERSION,
    BOT_REQUIRED_PERMISSIONS,
    CACHE_SETTINGS
)

logger = logging.getLogger('DraXon_OCULUS')

class DraXonOCULUSBot(commands.Bot):
    """Main bot class for DraXon OCULUS (Organizational Command & Unified Leadership Implementation System)"""
    
    def __init__(self, 
                 db_pool: asyncpg.Pool,
                 redis_pool: redis.Redis,
                 ssl_context: Optional[ssl.SSLContext] = None,
                 settings: Optional[Any] = None,
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
        
        # Store connections and settings
        self.db = db_pool
        self.redis = redis_pool
        self.ssl_context = ssl_context
        self.settings = settings
        
        # Initialize session as None (will be set in setup_hook)
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Internal state
        self._ready = False
        self._cogs_loaded = False
        
        # Channel IDs storage
        self.incidents_channel_id: Optional[int] = None
        self.promotion_channel_id: Optional[int] = None
        self.demotion_channel_id: Optional[int] = None
        self.reminder_channel_id: Optional[int] = None
        
        # Startup timestamp
        self.start_time = datetime.utcnow()
        
        logger.info("Bot initialized")

    async def setup_hook(self):
        """Initial setup when bot starts"""
        logger.info("Setup hook starting...")
        try:
            # Initialize aiohttp session with SSL context if provided
            if self.ssl_context:
                self.session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=self.ssl_context))
            else:
                self.session = aiohttp.ClientSession()
            logger.info("HTTP session initialized")
            
            # Load stored channel IDs first
            await self._load_channel_ids()
            
            # Define all cogs to load with dependencies
            cogs = [
                # Core functionality
                'src.cogs.channels',      # Channel management
                'src.cogs.members',       # Member management
                'src.cogs.promotion',     # Role management
                'src.cogs.commands',      # Command handling
                
                # RSI Integration
                'src.cogs.rsi_status_monitor',    # RSI status tracking
                'src.cogs.rsi_incidents_monitor', # Incident monitoring
                'src.cogs.rsi_integration',      # Account linking
                
                # Utility
                'src.cogs.backup',             # Server backup
                'src.cogs.membership_monitor'   # Member verification
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
            
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}")
            raise

    async def _load_channel_ids(self):
        """Load stored channel IDs from Redis"""
        try:
            channel_ids = await self.redis.hgetall('channel_ids')
            if channel_ids:
                # Convert bytes to int, handling both string and bytes keys
                self.incidents_channel_id = int(channel_ids.get(b'incidents', channel_ids.get('incidents', 0))) or None
                self.promotion_channel_id = int(channel_ids.get(b'promotion', channel_ids.get('promotion', 0))) or None
                self.demotion_channel_id = int(channel_ids.get(b'demotion', channel_ids.get('demotion', 0))) or None
                self.reminder_channel_id = int(channel_ids.get(b'reminder', channel_ids.get('reminder', 0))) or None
                logger.info("Loaded channel IDs from Redis")
        except Exception as e:
            logger.error(f"Error loading channel IDs: {e}")

    async def _save_channel_ids(self):
        """Save channel IDs to Redis"""
        try:
            channel_data = {
                'incidents': str(self.incidents_channel_id or 0),
                'promotion': str(self.promotion_channel_id or 0),
                'demotion': str(self.demotion_channel_id or 0),
                'reminder': str(self.reminder_channel_id or 0)
            }
            await self.redis.hmset('channel_ids', channel_data)
            logger.info("Saved channel IDs to Redis")
        except Exception as e:
            logger.error(f"Error saving channel IDs: {e}")

    async def close(self):
        """Cleanup when bot shuts down"""
        logger.info("Bot shutting down, cleaning up...")
        try:
            # Close aiohttp session
            if self.session and not self.session.closed:
                await self.session.close()
                logger.info("HTTP session closed")
            
            # Save current state
            await self._save_channel_ids()
            
            # Record shutdown time
            await self.redis.set(
                'last_shutdown',
                datetime.utcnow().isoformat(),
                ex=CACHE_SETTINGS['STATUS_TTL']
            )
            
            # Save bot statistics
            stats = await self.get_bot_stats()
            await self.redis.hmset('bot_stats', {k: str(v) for k, v in stats.items()})
            
            await super().close()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            raise

    async def on_ready(self):
        """Handle bot ready event"""
        if self._ready:
            return
            
        logger.info(f'DraXon OCULUS Bot v{APP_VERSION} has connected to Discord!')
        try:
            # Set custom activity
            activity = discord.CustomActivity(name=f"Ver. {APP_VERSION} Processing...")
            await self.change_presence(activity=activity)
            logger.info("Bot activity status set successfully")
            
            # Record ready state
            self._ready = True
            
            # Store startup info in Redis
            startup_info = {
                'version': APP_VERSION,
                'start_time': self.start_time.isoformat(),
                'guilds': len(self.guilds),
                'ready_time': datetime.utcnow().isoformat()
            }
            
            await self.redis.hmset('bot_info', startup_info)
            logger.info("Startup info recorded")
            
        except Exception as e:
            logger.error(f"Error in on_ready: {e}")

    async def verify_permissions(self, guild: discord.Guild) -> Tuple[bool, List[str]]:
        """Verify bot has required permissions in guild"""
        missing_perms = []
        for perm in BOT_REQUIRED_PERMISSIONS:
            if not getattr(guild.me.guild_permissions, perm):
                missing_perms.append(perm)
        
        return not bool(missing_perms), missing_perms

    async def get_bot_stats(self) -> Dict[str, Any]:
        """Get current bot statistics"""
        try:
            total_members = sum(len(g.members) for g in self.guilds)
            bot_members = sum(1 for g in self.guilds for m in g.members if m.bot)
            
            return {
                'version': APP_VERSION,
                'uptime': (datetime.utcnow() - self.start_time).total_seconds(),
                'guilds': len(self.guilds),
                'total_members': total_members,
                'human_members': total_members - bot_members,
                'bot_members': bot_members,
                'cogs_loaded': len(self.cogs),
                'commands': len(self.tree._global_commands),
                'latency': self.latency
            }
        except Exception as e:
            logger.error(f"Error getting bot stats: {e}")
            return {}

    async def on_guild_join(self, guild: discord.Guild):
        """Handle bot joining a new guild"""
        try:
            # Verify permissions
            has_perms, missing = await self.verify_permissions(guild)
            if not has_perms:
                logger.warning(f"Missing permissions in {guild.name}: {', '.join(missing)}")
                # Try to notify guild owner
                try:
                    await guild.owner.send(
                        f"⚠️ DraXon OCULUS is missing required permissions in {guild.name}:\n"
                        + "\n".join(f"• {perm}" for perm in missing)
                    )
                except Exception as e:
                    logger.error(f"Could not notify guild owner: {e}")

            # Log join event
            logger.info(f"Joined guild: {guild.name} (ID: {guild.id})")
            
            # Record in Redis
            await self.redis.sadd('guilds', str(guild.id))
            
            # Initialize guild setup
            channels_cog = self.get_cog('ChannelsCog')
            if channels_cog:
                await channels_cog.setup_guild(guild)
                
        except Exception as e:
            logger.error(f"Error handling guild join: {e}")

    async def on_guild_remove(self, guild: discord.Guild):
        """Handle bot leaving a guild"""
        try:
            logger.info(f"Left guild: {guild.name} (ID: {guild.id})")
            await self.redis.srem('guilds', str(guild.id))
            
            # Clean up guild data
            await self.redis.delete(f'guild_config:{guild.id}')
            logger.info(f"Cleaned up data for guild: {guild.id}")
            
        except Exception as e:
            logger.error(f"Error handling guild remove: {e}")

    async def on_command_error(self, ctx, error):
        """Global error handler for commands"""
        try:
            if isinstance(error, commands.errors.MissingRole):
                await ctx.send("❌ You don't have permission to use this command.")
            else:
                logger.error(f"Command error: {error}")
                await ctx.send("❌ An error occurred while processing the command.")
        except Exception as e:
            logger.error(f"Error handling command error: {e}")

    async def on_app_command_error(self, 
                                 interaction: discord.Interaction, 
                                 error: app_commands.AppCommandError):
        """Global error handler for application commands"""
        try:
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
        except Exception as e:
            logger.error(f"Error handling app command error: {e}")
