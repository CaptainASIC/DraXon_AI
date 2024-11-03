import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import discord
from discord import app_commands
from discord.ext import commands
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from src.utils.constants import (
    APP_VERSION,
    DraXon_ROLES,
    STATUS_EMOJIS,
    ROLE_HIERARCHY
)

logger = logging.getLogger('DraXon_AI')

# ... [ChannelSelectView class remains unchanged] ...

class CommandsCog(commands.Cog):
    """Cog for handling bot commands"""
    
    def __init__(self, bot):
        self.bot = bot
        logger.info("Commands cog initialized")

    @app_commands.command(name="draxon-stats", 
                         description="Display DraXon member statistics")
    @app_commands.checks.has_any_role("Chairman", "Director")
    async def draxon_stats(self, interaction: discord.Interaction):
        """Command to display member statistics"""
        try:
            total_members = 0
            role_counts = {}
            
            # Calculate member counts
            for category, roles in DraXon_ROLES.items():
                category_total = 0
                for role_name in roles:
                    role = discord.utils.get(interaction.guild.roles, name=role_name)
                    if role:
                        members = len([m for m in role.members if not m.bot])
                        role_counts[role_name] = members
                        category_total += members
                role_counts[f"Total {category.title()}"] = category_total
                total_members += category_total

            # Get bot count
            bot_role = discord.utils.get(interaction.guild.roles, name="Bots")
            bot_count = len(bot_role.members) if bot_role else 0

            # Create embed
            embed = discord.Embed(
                title="📊 DraXon Member Statistics",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )

            # Add role counts by category
            for category in DraXon_ROLES:
                roles_in_category = DraXon_ROLES[category]
                field_value = "\n".join(
                    f"└ {role}: {role_counts.get(role, 0)}" 
                    for role in roles_in_category
                )
                field_value += f"\n**Total {category.title()}: {role_counts.get(f'Total {category.title()}', 0)}**"
                
                embed.add_field(
                    name=f"{category.title()} Roles",
                    value=field_value,
                    inline=False
                )

            # Add totals
            embed.add_field(
                name="Overall Statistics",
                value=f"👥 Total Human Members: {total_members}\n"
                      f"🤖 Total Automated Systems: {bot_count}",
                inline=False
            )

            embed.set_footer(text=f"DraXon AI v{APP_VERSION}")

            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in stats command: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while fetching statistics.",
                ephemeral=True
            )

    @app_commands.command(name="refresh-channels", 
                         description="Manually refresh DraXon AI channels")
    @app_commands.checks.has_role("Chairman")
    async def refresh_channels(self, interaction: discord.Interaction):
        """Manually trigger channel refresh"""
        try:
            members_cog = self.bot.get_cog('MembersCog')
            status_cog = self.bot.get_cog('StatusCog')
            
            if not members_cog or not status_cog:
                await interaction.response.send_message(
                    "❌ Required cogs not found.",
                    ephemeral=True
                )
                return

            # Update channels
            await members_cog.update_member_counts()
            await status_cog.update_server_status()
            
            await interaction.response.send_message(
                "✅ Channels refreshed successfully!", 
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Error refreshing channels: {e}")
            await interaction.response.send_message(
                "❌ Failed to refresh channels. Check logs for details.", 
                ephemeral=True
            )

    @app_commands.command(name="setup", description="Configure bot channels")
    @app_commands.checks.has_role("Chairman")
    async def setup(self, interaction: discord.Interaction):
        """Setup command using channel selection view"""
        try:
            embed = discord.Embed(
                title="DraXon AI Channel Setup",
                description="Please select the channels for each notification type below.\n"
                           "All channels must be selected before confirming the setup.",
                color=discord.Color.blue()
            )
            
            view = ChannelSelectView(self.bot)
            await interaction.response.send_message(
                embed=embed,
                view=view,
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error in setup command: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while initializing setup.",
                ephemeral=True
            )

    @app_commands.command(name="force-check", 
                         description="Force check for new incidents and status")
    @app_commands.checks.has_role("Chairman")
    async def force_check(self, interaction: discord.Interaction):
        """Manually trigger status and incident checks"""
        try:
            status_monitor = self.bot.get_cog('RSIStatusMonitorCog')
            incident_monitor = self.bot.get_cog('RSIIncidentMonitorCog')
            
            if not status_monitor or not incident_monitor:
                await interaction.response.send_message(
                    "❌ Required monitors not available.",
                    ephemeral=True
                )
                return
            
            await interaction.response.defer(ephemeral=True)
            
            # Perform checks
            await status_monitor.check_status()
            await incident_monitor.check_incidents()
            
            await interaction.followup.send(
                "✅ Manual check completed successfully!",
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Error in force check: {e}")
            await interaction.followup.send(
                "❌ Error during manual check. Check logs for details.",
                ephemeral=True
            )

    @app_commands.command(name="help", description="Display available DraXon AI commands")
    async def help_command(self, interaction: discord.Interaction):
        """Display help information for all commands"""
        try:
            user_roles = [role.name for role in interaction.user.roles]
            is_leadership = any(role in DraXon_ROLES['leadership'] for role in user_roles)

            embed = discord.Embed(
                title=f"DraXon AI Commands v{APP_VERSION}",
                description="Available commands and their descriptions:",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )

            # Basic commands section
            basic_commands = [
                ("/check-status", "Display current status of RSI systems"),
                ("/draxon-link", "Link your RSI account with Discord"),
                ("/help", "Display this help message")
            ]
            
            embed.add_field(
                name="📌 Basic Commands",
                value="\n".join(f"`{cmd}`: {desc}" for cmd, desc in basic_commands),
                inline=False
            )
            
            if is_leadership:
                # Leadership commands section
                leadership_commands = [
                    ("/draxon-stats", "Display detailed member statistics"),
                    ("/promote", "Promote a member with role selection"),
                    ("/demote", "Demote a member with role selection"),
                    ("/draxon-compare", "Compare Discord and RSI members")
                ]

                embed.add_field(
                    name="👥 Leadership Commands",
                    value="\n".join(f"`{cmd}`: {desc}" for cmd, desc in leadership_commands),
                    inline=False
                )

                if "Chairman" in user_roles:
                    # Chairman-only commands section
                    chairman_commands = [
                        ("/refresh-channels", "Manually refresh status channels"),
                        ("/setup", "Configure bot channels and notifications"),
                        ("/force-check", "Force status and incident checks"),
                        ("/draxon-backup", "Create server backup"),
                        ("/draxon-restore", "Restore from backup"),
                        ("/draxon-org", "View organization member list")
                    ]
                    
                    embed.add_field(
                        name="⚡ Chairman Commands",
                        value="\n".join(f"`{cmd}`: {desc}" for cmd, desc in chairman_commands),
                        inline=False
                    )

            # Features section
            embed.add_field(
                name="🆕 New Features v2.0.0",
                value="• Enhanced promotion and demotion system\n"
                      "• Improved channel configuration interface\n"
                      "• Advanced role management\n"
                      "• Real-time status monitoring\n"
                      "• Backup and restore functionality\n"
                      "• Improved error handling and reliability\n"
                      "• Enhanced security features",
                inline=False
            )

            # Usage tips
            embed.add_field(
                name="💡 Tips",
                value="• Most commands can be used in any channel\n"
                      "• Command responses are usually ephemeral (only visible to you)\n"
                      "• Use `/help` anytime to see this list again\n"
                      "• Status updates occur automatically every 5 minutes",
                inline=False
            )

            # Add support information
            embed.add_field(
                name="🔧 Support",
                value="If you encounter any issues or need assistance, "
                      "please contact a server administrator.",
                inline=False
            )

            embed.set_footer(text=f"DraXon AI v{APP_VERSION} • Commands available based on your roles")
            
            # Add timestamp to know when help was last viewed
            await self.bot.redis.hset(
                f'help_viewed:{interaction.user.id}',
                mapping={
                    'timestamp': datetime.utcnow().isoformat(),
                    'version': APP_VERSION
                }
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in help command: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while displaying help information.",
                ephemeral=True
            )

    async def cog_command_error(self, interaction: discord.Interaction, 
                               error: app_commands.AppCommandError):
        """Handle command errors for this cog"""
        if isinstance(error, app_commands.errors.MissingRole):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True
            )
        else:
            logger.error(f"Command error in {interaction.command.name}: {error}")
            await interaction.response.send_message(
                "❌ An error occurred while processing the command.",
                ephemeral=True
            )

async def setup(bot):
    """Safe setup function for commands cog"""
    try:
        if not bot.get_cog('CommandsCog'):
            await bot.add_cog(CommandsCog(bot))
            logger.info('Commands cog loaded successfully')
        else:
            logger.info('Commands cog already loaded, skipping')
    except Exception as e:
        logger.error(f'Error loading commands cog: {e}')
        raise
