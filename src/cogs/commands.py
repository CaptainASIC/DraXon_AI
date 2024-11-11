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

logger = logging.getLogger('DraXon_OCULUS')

class ChannelSelectView(discord.ui.View):
    """View for channel selection during setup"""
    
    def __init__(self, bot, timeout=180):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.incidents_channel = None
        self.promotion_channel = None
        self.demotion_channel = None
        self.reminder_channel = None

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select Incidents Channel",
        min_values=1,
        max_values=1
    )
    async def incidents_select(self, interaction: discord.Interaction, 
                             select: discord.ui.Select):
        """Handle incidents channel selection"""
        self.incidents_channel = select.values[0]
        select.disabled = True
        select.placeholder = f"Incidents Channel: {self.incidents_channel.name}"
        await self.check_completion(interaction)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select Promotion Channel",
        min_values=1,
        max_values=1
    )
    async def promotion_select(self, interaction: discord.Interaction, 
                             select: discord.ui.Select):
        """Handle promotion channel selection"""
        self.promotion_channel = select.values[0]
        select.disabled = True
        select.placeholder = f"Promotion Channel: {self.promotion_channel.name}"
        await self.check_completion(interaction)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select Demotion Channel",
        min_values=1,
        max_values=1
    )
    async def demotion_select(self, interaction: discord.Interaction, 
                             select: discord.ui.Select):
        """Handle demotion channel selection"""
        self.demotion_channel = select.values[0]
        select.disabled = True
        select.placeholder = f"Demotion Channel: {self.demotion_channel.name}"
        await self.check_completion(interaction)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select Reminder Channel",
        min_values=1,
        max_values=1
    )
    async def reminder_select(self, interaction: discord.Interaction, 
                            select: discord.ui.Select):
        """Handle reminder channel selection"""
        self.reminder_channel = select.values[0]
        select.disabled = True
        select.placeholder = f"Reminder Channel: {self.reminder_channel.name}"
        await self.check_completion(interaction)

    @discord.ui.button(label="Reset Selections", style=discord.ButtonStyle.secondary)
    async def reset_button(self, interaction: discord.Interaction, 
                          button: discord.ui.Button):
        """Reset all selections"""
        for child in self.children:
            if isinstance(child, discord.ui.ChannelSelect):
                child.disabled = False
                child.placeholder = child.placeholder.split(":")[0]
        
        self.incidents_channel = None
        self.promotion_channel = None
        self.demotion_channel = None
        self.reminder_channel = None
        
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Confirm Setup", style=discord.ButtonStyle.green, disabled=True)
    async def confirm_button(self, interaction: discord.Interaction, 
                           button: discord.ui.Button):
        """Process the final setup"""
        try:
            # Store channel IDs in Redis
            channel_data = {
                'incidents': str(self.incidents_channel.id),
                'promotion': str(self.promotion_channel.id),
                'demotion': str(self.demotion_channel.id),
                'reminder': str(self.reminder_channel.id)
            }
            
            await self.bot.redis.hmset('channel_ids', channel_data)
            
            # Update bot's channel IDs
            self.bot.incidents_channel_id = self.incidents_channel.id
            self.bot.promotion_channel_id = self.promotion_channel.id
            self.bot.demotion_channel_id = self.demotion_channel.id
            self.bot.reminder_channel_id = self.reminder_channel.id

            # Create confirmation embed
            embed = discord.Embed(
                title="✅ Setup Complete",
                description="Channel configuration has been updated:",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="Channel Assignments",
                value=f"📢 Incidents: {self.incidents_channel.mention}\n"
                      f"🎉 Promotions: {self.promotion_channel.mention}\n"
                      f"🔄 Demotions: {self.demotion_channel.mention}\n"
                      f"📋 Reminders: {self.reminder_channel.mention}",
                inline=False
            )

            # Disable all components
            for child in self.children:
                child.disabled = True

            await interaction.response.edit_message(embed=embed, view=self)

        except Exception as e:
            logger.error(f"Error in setup confirmation: {e}")
            await interaction.response.send_message(
                "❌ An error occurred during setup. Please try again.",
                ephemeral=True
            )

    async def check_completion(self, interaction: discord.Interaction):
        """Check if all channels have been selected"""
        all_selected = all([
            self.incidents_channel,
            self.promotion_channel,
            self.demotion_channel,
            self.reminder_channel
        ])
        
        # Enable/disable confirm button based on completion
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.label == "Confirm Setup":
                child.disabled = not all_selected
        
        await interaction.response.edit_message(view=self)

    async def on_timeout(self):
        """Handle timeout by disabling all components"""
        for child in self.children:
            child.disabled = True

class CommandsCog(commands.Cog):
    """Cog for handling bot commands"""
    
    def __init__(self, bot):
        self.bot = bot
        logger.info("Commands cog initialized")

    @app_commands.command(name="draxon-stats", 
                         description="Display DraXon member statistics")
    @app_commands.checks.has_any_role("Magnate", "Chairman")
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

            embed.set_footer(text=f"DraXon OCULUS v{APP_VERSION}")

            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in stats command: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while fetching statistics.",
                ephemeral=True
            )

    @app_commands.command(name="refresh-channels", 
                         description="Manually refresh DraXon OCULUS channels")
    @app_commands.checks.has_role("Magnate")
    async def refresh_channels(self, interaction: discord.Interaction):
        """Manually trigger channel refresh"""
        try:
            members_cog = self.bot.get_cog('MembersCog')
            status_cog = self.bot.get_cog('RSIStatusMonitorCog')
            
            if not members_cog or not status_cog:
                await interaction.response.send_message(
                    "❌ Required cogs not found. Make sure MembersCog and RSIStatusMonitorCog are loaded.",
                    ephemeral=True
                )
                return

            # Update channels
            await members_cog.update_member_counts()
            await status_cog.check_status()  # This will trigger channel updates
            
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
    @app_commands.checks.has_role("Magnate")
    async def setup(self, interaction: discord.Interaction):
        """Setup command using channel selection view"""
        try:
            embed = discord.Embed(
                title="DraXon OCULUS Channel Setup",
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
    @app_commands.checks.has_role("Magnate")
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
            current_status = await status_monitor.check_status()
            incident = await incident_monitor.get_latest_incident(force=True)
            
            # Create status embed
            status_embed = status_monitor.format_status_embed()  # Removed await
            
            # Create incident embed if there is one
            embeds = [status_embed]
            if incident:
                incident_embed = incident_monitor.create_incident_embed(incident)
                embeds.append(incident_embed)
            
            await interaction.followup.send(
                content="✅ Manual check completed successfully!",
                embeds=embeds,
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Error in force check: {e}")
            await interaction.followup.send(
                "❌ Error during manual check. Check logs for details.",
                ephemeral=True
            )

    @app_commands.command(name="help", description="Display available DraXon OCULUS commands")
    async def help_command(self, interaction: discord.Interaction):
        """Display help information for all commands"""
        try:
            user_roles = [role.name for role in interaction.user.roles]
            is_leadership = any(role in DraXon_ROLES['leadership'] for role in user_roles)

            embed = discord.Embed(
                title=f"DraXon OCULUS Commands v{APP_VERSION}",
                description="Organizational Command & Unified Leadership Implementation System",
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

                if "Magnate" in user_roles:
                    # Magnate-only commands section
                    magnate_commands = [
                        ("/refresh-channels", "Manually refresh status channels"),
                        ("/setup", "Configure bot channels and notifications"),
                        ("/force-check", "Force status and incident checks"),
                        ("/draxon-backup", "Create server backup"),
                        ("/draxon-restore", "Restore from backup"),
                        ("/draxon-org", "View organization member list")
                    ]
                    
                    embed.add_field(
                        name="⚡ Magnate Commands",
                        value="\n".join(f"`{cmd}`: {desc}" for cmd, desc in magnate_commands),
                        inline=False
                    )

            # Features section
            embed.add_field(
                name="🆕 New Features v2.0.5",
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

            embed.set_footer(text=f"DraXon OCULUS v{APP_VERSION} • Commands available based on your roles")
            
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
