import discord
from discord.ext import commands
import logging
import asyncio
from typing import Optional, Dict, List, Tuple

from src.utils.constants import (
    CHANNEL_SETTINGS,
    CHANNELS_CONFIG,
    BOT_REQUIRED_PERMISSIONS,
    CHANNEL_PERMISSIONS
)

logger = logging.getLogger('DraXon_OCULUS')

class ChannelsCog(commands.Cog):
    """Manages dynamic channels and category setup"""
    
    def __init__(self, bot):
        self.bot = bot
        self.category: Optional[discord.CategoryChannel] = None
        self._channels_created = False
        self._setup_complete = False
        logger.info("Channels cog initialized")

    def log_permission_details(self, guild: discord.Guild) -> None:
        """Log detailed permission information for debugging"""
        try:
            logger.info(f"=== Permission Details for {guild.name} ===")
            logger.info(f"Bot's name: {guild.me.name}")
            logger.info(f"Bot's top role: {guild.me.top_role.name}")
            logger.info(f"Bot's role position: {guild.me.top_role.position}")
            logger.info(f"Server owner: {guild.owner}")
            logger.info("Role Hierarchy:")
            for role in reversed(guild.roles):
                logger.info(f"- {role.name} (Position: {role.position})")
            logger.info("=== End Permission Details ===")
        except Exception as e:
            logger.error(f"Error logging permission details: {e}")

    async def check_bot_permissions(self, guild: discord.Guild) -> Tuple[bool, List[str]]:
        """Check if bot has required permissions in the guild"""
        try:
            permissions = guild.me.guild_permissions
            logger.info(f"Checking bot permissions in {guild.name}")
            
            # Log detailed permission state
            self.log_permission_details(guild)
            
            # Check role management capabilities
            can_manage_roles = all([
                permissions.manage_roles,
                guild.me.top_role.position > 1,  # Above @everyone
                permissions.manage_channels
            ])

            if not can_manage_roles:
                logger.error("Bot cannot manage roles effectively:")
                logger.error(f"- Can manage roles: {permissions.manage_roles}")
                logger.error(f"- Role position: {guild.me.top_role.position}")
                logger.error(f"- Can manage channels: {permissions.manage_channels}")
                return False, ["Insufficient role management permissions"]

            # Check other required permissions
            missing_permissions = [
                perm for perm in BOT_REQUIRED_PERMISSIONS 
                if not getattr(permissions, perm)
            ]

            if missing_permissions:
                logger.error(f"Missing permissions: {', '.join(missing_permissions)}")
                return False, missing_permissions

            return True, []

        except Exception as e:
            logger.error(f"Error during permission check: {e}")
            return False, ["Error checking permissions"]

    async def get_category(self, guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        """Get or clean up existing category"""
        # Return cached category if valid
        if self.category and self.category in guild.categories:
            return self.category
        
        # Reset category cache
        self.category = None
        
        # Find existing categories
        existing_categories = [
            c for c in guild.categories 
            if c.name == CHANNEL_SETTINGS['CATEGORY_NAME']
        ]
        
        if existing_categories:
            # Use first category found
            self.category = existing_categories[0]
            logger.info(f"Found existing category: {self.category.name}")
            
            # Clean up duplicates
            if len(existing_categories) > 1:
                logger.warning(f"Found {len(existing_categories)} duplicate categories. Cleaning up...")
                for category in existing_categories[1:]:
                    try:
                        await category.delete()
                        logger.info(f"Deleted duplicate category: {category.name}")
                    except Exception as e:
                        logger.error(f"Failed to delete duplicate category: {e}")
            
        return self.category

    def get_channel_name(self, config: Dict, count: Optional[int] = None, 
                        status: Optional[str] = None) -> str:
        """Generate channel name based on configuration"""
        try:
            if config["count_type"] == "status":
                from src.utils.constants import STATUS_EMOJIS
                emoji = STATUS_EMOJIS.get(status, '❓')
                return config["display"].format(emoji=emoji)
            else:
                return config["display"].format(count=count or 0)
        except Exception as e:
            logger.error(f"Error generating channel name: {e}")
            return config["name"]

    async def create_category(self, guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        """Create the bot category with proper permissions"""
        try:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    **CHANNEL_PERMISSIONS['display_only']['everyone']
                ),
                guild.me: discord.PermissionOverwrite(
                    **CHANNEL_PERMISSIONS['display_only']['bot']
                )
            }
            
            category = await guild.create_category(
                name=CHANNEL_SETTINGS['CATEGORY_NAME'],
                overwrites=overwrites,
                reason="DraXon OCULUS Bot Category Creation"
            )
            
            self.category = category
            logger.info(f"Created new category in {guild.name}")
            return category
            
        except Exception as e:
            logger.error(f"Error creating category: {e}")
            return None

    async def setup_guild(self, guild: discord.Guild) -> None:
        """Setup channels for a guild"""
        logger.info(f"Setting up guild: {guild.name}")
        
        # Check permissions first
        has_perms, missing_perms = await self.check_bot_permissions(guild)
        if not has_perms:
            logger.error(f"Cannot setup channels in {guild.name}")
            logger.error("Missing Permissions: " + ", ".join(missing_perms))
            return
        
        try:
            # Get or create category
            category = await self.get_category(guild)
            if not category:
                category = await self.create_category(guild)
                if not category:
                    logger.error("Failed to create category")
                    return

            # Create configured channels
            for config in CHANNELS_CONFIG:
                try:
                    base_name = config["name"].lower()
                    existing_channel = next(
                        (ch for ch in category.voice_channels 
                         if ch.name.lower().startswith(base_name)),
                        None
                    )
                    
                    if not existing_channel:
                        # Create initial channel name
                        initial_name = self.get_channel_name(
                            config,
                            count=0 if config["count_type"] in ["members", "bots"] else None,
                            status='operational' if config["count_type"] == "status" else None
                        )
                        
                        # Set channel permissions
                        overwrites = {
                            guild.default_role: discord.PermissionOverwrite(
                                **CHANNEL_PERMISSIONS['display_only']['everyone']
                            ),
                            guild.me: discord.PermissionOverwrite(
                                **CHANNEL_PERMISSIONS['display_only']['bot']
                            )
                        }
                        
                        # Create voice channel
                        await category.create_voice_channel(
                            name=initial_name,
                            overwrites=overwrites,
                            reason="DraXon OCULUS Bot Channel Creation"
                        )
                        logger.info(f"Created channel {initial_name}")
                        
                except Exception as e:
                    logger.error(f"Error creating channel {config['name']}: {e}")
                    continue

            # Trigger initial updates
            try:
                members_cog = self.bot.get_cog('MembersCog')
                status_cog = self.bot.get_cog('StatusCog')
                
                if members_cog:
                    await members_cog.update_member_counts()
                if status_cog:
                    await status_cog.update_server_status()
                
                logger.info("Initial channel updates completed")
                
            except Exception as e:
                logger.error(f"Error during initial updates: {e}")

        except Exception as e:
            logger.error(f"Error setting up guild: {e}")

    @commands.command(name="fix-permissions")
    @commands.has_role("Magnate")
    async def fix_permissions(self, ctx: commands.Context):
        """Fix permissions for all DraXon OCULUS channels"""
        try:
            guild = ctx.guild
            has_perms, missing_perms = await self.check_bot_permissions(guild)
            if not has_perms:
                await ctx.send("❌ Bot is missing required permissions: " + ", ".join(missing_perms))
                return

            category = await self.get_category(guild)
            if not category:
                await ctx.send("❌ Could not find DraXon OCULUS category.")
                return

            await ctx.send("🔄 Fixing channel permissions...")

            # Update category permissions
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    **CHANNEL_PERMISSIONS['display_only']['everyone']
                ),
                guild.me: discord.PermissionOverwrite(
                    **CHANNEL_PERMISSIONS['display_only']['bot']
                )
            }

            await category.edit(overwrites=overwrites)
            
            # Update each channel's permissions
            for channel in category.channels:
                await channel.edit(overwrites=overwrites)

            await ctx.send("✅ Successfully updated all channel permissions!")

        except Exception as e:
            logger.error(f"Error fixing permissions: {e}")
            await ctx.send("❌ An error occurred while updating permissions.")

    @commands.Cog.listener()
    async def on_ready(self):
        """Handle initial channel setup when bot is ready"""
        if self._setup_complete:
            return
            
        await self.bot.wait_until_ready()
        logger.info("Starting channel setup...")
        await asyncio.sleep(1)  # Brief delay to ensure everything is ready
        
        for guild in self.bot.guilds:
            await self.setup_guild(guild)
        
        self._setup_complete = True
        self._channels_created = True
        logger.info("All channel setup completed")

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """Handle setup when bot joins a new guild"""
        logger.info(f"Bot joined new guild: {guild.name}")
        await self.setup_guild(guild)

async def setup(bot):
    """Safe setup function for channels cog"""
    try:
        if not bot.get_cog('ChannelsCog'):
            await bot.add_cog(ChannelsCog(bot))
            logger.info('Channels cog loaded successfully')
        else:
            logger.info('Channels cog already loaded, skipping')
    except Exception as e:
        logger.error(f'Error loading channels cog: {e}')
        raise
