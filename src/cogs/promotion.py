import discord
from discord import app_commands
from discord.ext import commands
import logging
import random
from typing import Optional, List, Dict
from datetime import datetime

from src.utils.constants import (
    ROLE_HIERARCHY,
    ROLE_SETTINGS,
    SYSTEM_MESSAGES,
    CACHE_SETTINGS
)

logger = logging.getLogger('DraXon_AI')

class PromotionModal(discord.ui.Modal, title='Member Promotion'):
    def __init__(self, member: discord.Member, new_rank: str):
        super().__init__()
        self.member = member
        self.new_rank = new_rank
        
        self.reason = discord.ui.TextInput(
            label='Promotion Reason',
            placeholder='Enter the reason for promotion...',
            required=True,
            min_length=10,
            max_length=1000,
            style=discord.TextStyle.paragraph
        )
        
        self.add_item(self.reason)
        self.cog = None

    async def on_submit(self, interaction: discord.Interaction):
        """Handle promotion modal submission"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            if not self.cog:
                raise ValueError("Modal not properly initialized")

            await self.cog.process_promotion(
                interaction,
                self.member,
                self.new_rank,
                str(self.reason),
                notify=True
            )

        except Exception as e:
            logger.error(f"Error in promotion modal: {e}")
            await interaction.followup.send(
                "❌ An error occurred processing the promotion.",
                ephemeral=True
            )

class DemotionModal(discord.ui.Modal, title='Member Demotion'):
    def __init__(self, member: discord.Member, new_rank: str):
        super().__init__()
        self.member = member
        self.new_rank = new_rank
        
        self.reason = discord.ui.TextInput(
            label='Demotion Reason',
            placeholder='Enter the reason for demotion...',
            required=True,
            min_length=10,
            max_length=1000,
            style=discord.TextStyle.paragraph
        )
        
        self.add_item(self.reason)
        self.cog = None

    async def on_submit(self, interaction: discord.Interaction):
        """Handle demotion modal submission"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            if not self.cog:
                raise ValueError("Modal not properly initialized")

            await self.cog.process_demotion(
                interaction,
                self.member,
                self.new_rank,
                str(self.reason),
                notify=True
            )

        except Exception as e:
            logger.error(f"Error in demotion modal: {e}")
            await interaction.followup.send(
                "❌ An error occurred processing the demotion.",
                ephemeral=True
            )

class RankSelectionView(discord.ui.View):
    def __init__(self, cog, members: List[discord.Member], mode: str = 'promote'):
        super().__init__(timeout=ROLE_SETTINGS['PROMOTION_TIMEOUT'])
        self.cog = cog
        self.mode = mode
        self.selected_member = None
        
        # Add member select
        self.member_select = discord.ui.Select(
            placeholder="Select member...",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=member.display_name,
                    value=str(member.id),
                    description=f"Current Role: {next((r.name for r in member.roles if r.name in ROLE_HIERARCHY), 'None')}"
                ) for member in members
            ]
        )
        self.member_select.callback = self.handle_member_select
        self.add_item(self.member_select)
        
        # Add disabled role select (will be updated when member is selected)
        self.role_select = discord.ui.Select(
            placeholder="Select new role (select member first)...",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="Select member first",
                    value="none",
                    description="Please select a member before choosing a role"
                )
            ],
            disabled=True
        )
        self.role_select.callback = self.handle_role_select
        self.add_item(self.role_select)

    async def handle_member_select(self, interaction: discord.Interaction):
        """Handle member selection"""
        try:
            member = interaction.guild.get_member(int(self.member_select.values[0]))
            if not member:
                await interaction.response.send_message(
                    "❌ Selected member not found.",
                    ephemeral=True
                )
                return

            # Get available roles
            available_roles = (
                self.cog.get_available_roles(member)
                if self.mode == 'promote'
                else self.cog.get_available_demotion_roles(member)
            )
            
            if not available_roles:
                await interaction.response.send_message(
                    "❌ No roles available for this member.",
                    ephemeral=True
                )
                return

            # Update role select
            self.selected_member = member
            self.role_select.options = [
                discord.SelectOption(
                    label=role,
                    value=role,
                    description=f"Change to {role}"
                ) for role in available_roles
            ]
            self.role_select.disabled = False
            self.role_select.placeholder = (
                "Select new role..."
                if self.mode == 'promote'
                else "Select new (lower) rank..."
            )

            await interaction.response.edit_message(view=self)

        except Exception as e:
            logger.error(f"Error in member selection: {e}")
            await interaction.response.send_message(
                "❌ An error occurred processing the selection.",
                ephemeral=True
            )

    async def handle_role_select(self, interaction: discord.Interaction):
        """Handle role selection"""
        try:
            if not self.selected_member:
                await interaction.response.send_message(
                    "❌ Please select a member first.",
                    ephemeral=True
                )
                return

            # Show appropriate modal
            modal = (
                PromotionModal(self.selected_member, self.role_select.values[0])
                if self.mode == 'promote'
                else DemotionModal(self.selected_member, self.role_select.values[0])
            )
            modal.cog = self.cog
            await interaction.response.send_modal(modal)

        except Exception as e:
            logger.error(f"Error in role selection: {e}")
            await interaction.response.send_message(
                "❌ An error occurred processing the selection.",
                ephemeral=True
            )

    async def on_timeout(self):
        """Disable all components on timeout"""
        for child in self.children:
            child.disabled = True

class PromotionCog(commands.Cog):
    """Handles member promotions and demotions"""
    
    def __init__(self, bot):
        self.bot = bot
        logger.info("Promotion cog initialized")

    def get_available_roles(self, member: discord.Member) -> List[str]:
        """Get available promotion roles for a member"""
        current_rank = next(
            (role.name for role in member.roles if role.name in ROLE_HIERARCHY),
            None
        )

        if not current_rank:
            return ROLE_HIERARCHY[:ROLE_SETTINGS['MAX_PROMOTION_OPTIONS']]

        current_index = ROLE_HIERARCHY.index(current_rank)
        if current_index + 1 >= len(ROLE_HIERARCHY):
            return []
            
        return ROLE_HIERARCHY[
            current_index + 1:
            current_index + 1 + ROLE_SETTINGS['MAX_PROMOTION_OPTIONS']
        ]

    def get_available_demotion_roles(self, member: discord.Member) -> List[str]:
        """Get available demotion roles for a member"""
        current_rank = next(
            (role.name for role in member.roles if role.name in ROLE_HIERARCHY),
            None
        )

        if not current_rank or current_rank == ROLE_HIERARCHY[0]:
            return []

        current_index = ROLE_HIERARCHY.index(current_rank)
        return ROLE_HIERARCHY[
            max(0, current_index - ROLE_SETTINGS['MAX_PROMOTION_OPTIONS']):
            current_index
        ]

    def format_promotion_announcement(self, member: discord.Member, new_rank: str, previous_rank: str, reason: str) -> str:
        """Format a professional promotion announcement"""
        announcements = [
            f"🎉 **DraXon Promotion Announcement** 🎉\n\n"
            f"@everyone\n\n"
            f"It is with great pleasure that we announce the promotion of {member.mention} "
            f"to the position of **{new_rank}**!\n\n"
            f"📋 **Promotion Details**\n"
            f"• Previous Role: {previous_rank or 'None'}\n"
            f"• New Role: {new_rank}\n"
            f"• Reason: {reason}\n\n"
            f"Please join us in congratulating {member.mention} on this well-deserved promotion! 🚀",

            f"🌟 **Promotion Announcement** 🌟\n\n"
            f"@everyone\n\n"
            f"We are delighted to announce that {member.mention} has been promoted to "
            f"the role of **{new_rank}**!\n\n"
            f"🎯 **Achievement Details**\n"
            f"• Advanced from: {previous_rank or 'None'}\n"
            f"• New Position: {new_rank}\n"
            f"• Reason: {reason}\n\n"
            f"Congratulations on this outstanding achievement! 🏆"
        ]
        
        return random.choice(announcements)

    def format_demotion_announcement(self, member: discord.Member, new_rank: str, previous_rank: str, reason: str) -> str:
        """Format a professional demotion announcement"""
        announcements = [
            f"📢 **DraXon Personnel Notice** 📢\n\n"
            f"@everyone\n\n"
            f"This notice serves to inform all members that {member.mention} has been reassigned to the position of **{new_rank}**.\n\n"
            f"📋 **Position Update**\n"
            f"• Previous Role: {previous_rank or 'None'}\n"
            f"• New Role: {new_rank}\n"
            f"• Reason: {reason}\n\n"
            f"This change is effective immediately. 📝",

            f"⚠️ **DraXon Rank Adjustment** ⚠️\n\n"
            f"@everyone\n\n"
            f"Please be advised that {member.mention}'s position has been adjusted to **{new_rank}**.\n\n"
            f"📊 **Status Update**\n"
            f"• Previous Position: {previous_rank or 'None'}\n"
            f"• Updated Position: {new_rank}\n"
            f"• Reason: {reason}\n\n"
            f"This change takes effect immediately. 📌"
        ]
        
        return random.choice(announcements)

    def format_rank_announcement(self, 
                               member: discord.Member,
                               old_rank: str,
                               new_rank: str,
                               reason: str,
                               is_promotion: bool = True) -> discord.Embed:
        """Format a rank change announcement embed for logging"""
        embed = discord.Embed(
            title="🎉 DraXon Promotion" if is_promotion else "🔄 DraXon Demotion",
            description=f"{member.mention} has been "
                       f"{'promoted' if is_promotion else 'reassigned'} "
                       f"to **{new_rank}**",
            color=discord.Color.green() if is_promotion else discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="Previous Rank", value=old_rank or "None", inline=True)
        embed.add_field(name="New Rank", value=new_rank, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        
        return embed

    async def process_rank_change(self,
                                member: discord.Member,
                                new_rank: str,
                                reason: str,
                                notify: bool = True,
                                is_promotion: bool = True) -> bool:
        """Process rank change in database and Discord"""
        try:
            guild = member.guild
            # Store current rank before making any changes
            current_rank = next(
                (role.name for role in member.roles if role.name in ROLE_HIERARCHY),
                None
            )

            # Get the new role
            new_role = discord.utils.get(guild.roles, name=new_rank)
            if not new_role:
                logger.error(f"Role {new_rank} not found")
                return False

            # Remove current rank role
            if current_rank:
                current_role = discord.utils.get(guild.roles, name=current_rank)
                if current_role:
                    await member.remove_roles(current_role)

            # Add new role
            await member.add_roles(new_role)
            
            # Record in database
            async with self.bot.db.acquire() as conn:
                async with conn.transaction():
                    # Record role change
                    await conn.execute('''
                        INSERT INTO role_history (discord_id, old_rank, new_rank, reason)
                        VALUES ($1, $2, $3, $4)
                    ''', str(member.id), current_rank, new_rank, reason)
                    
                    # Update member's org rank
                    await conn.execute('''
                        UPDATE rsi_members 
                        SET org_rank = $1, last_updated = NOW()
                        WHERE discord_id = $2
                    ''', new_rank, str(member.id))

            # Send notifications if requested
            if notify:
                # Get appropriate channel
                channel_id = (
                    self.bot.promotion_channel_id if is_promotion
                    else self.bot.demotion_channel_id
                )
                
                if channel_id:
                    channel = self.bot.get_channel(channel_id)
                    if channel:
                        # Send announcement using stored current_rank
                        announcement = (
                            self.format_promotion_announcement(member, new_rank, current_rank, reason)
                            if is_promotion else
                            self.format_demotion_announcement(member, new_rank, current_rank, reason)
                        )
                        await channel.send(announcement)

                # Log to Redis for tracking
                await self.bot.redis.lpush(
                    f'rank_changes:{member.guild.id}',
                    f"{datetime.utcnow().isoformat()}:{member.id}:{current_rank}:{new_rank}"
                )
                await self.bot.redis.ltrim(
                    f'rank_changes:{member.guild.id}',
                    0, 99
                )  # Keep last 100 changes

                # Try to DM the member
                try:
                    dm_message = (
                        f"🎉 Congratulations! You have been promoted to {new_rank}!\n\n"
                        if is_promotion else
                        f"Your rank has been updated to {new_rank}.\n\n"
                    )
                    dm_message += f"Previous Rank: {current_rank or 'None'}\n"
                    dm_message += f"Reason: {reason}"
                    
                    await member.send(dm_message)
                except discord.Forbidden:
                    logger.warning(f"Could not send DM to {member.name}")

            return True

        except Exception as e:
            logger.error(f"Error processing rank change: {e}")
            return False

    async def process_promotion(self,
                              interaction: discord.Interaction,
                              member: discord.Member,
                              new_rank: str,
                              reason: str,
                              notify: bool = True):
        """Process promotion request"""
        success = await self.process_rank_change(
            member,
            new_rank,
            reason,
            notify,
            is_promotion=True
        )
        
        if success:
            await interaction.followup.send(
                f"✅ Successfully promoted {member.mention} to {new_rank}!",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "❌ Failed to process promotion.",
                ephemeral=True
            )

    async def process_demotion(self,
                             interaction: discord.Interaction,
                             member: discord.Member,
                             new_rank: str,
                             reason: str,
                             notify: bool = True):
        """Process demotion request"""
        success = await self.process_rank_change(
            member,
            new_rank,
            reason,
            notify,
            is_promotion=False
        )
        
        if success:
            await interaction.followup.send(
                f"✅ Successfully updated {member.mention} to {new_rank}.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "❌ Failed to process rank change.",
                ephemeral=True
            )

    @app_commands.command(
        name="promote",
        description="Promote a member to a higher rank"
    )
    @app_commands.checks.has_any_role("Magnate", "Chairman")
    async def promote(self, interaction: discord.Interaction):
        """Promote command with role selection interface"""
        try:
            # Get eligible members
            eligible_members = [
                member for member in interaction.guild.members
                if not member.bot and
                not any(role.name == ROLE_HIERARCHY[-1] for role in member.roles)
            ]

            if not eligible_members:
                await interaction.response.send_message(
                    "❌ No members available for promotion.",
                    ephemeral=True
                )
                return

            # Create and send view
            view = RankSelectionView(self, eligible_members, mode='promote')
            await interaction.response.send_message(
                "Please select a member to promote:",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error in promote command: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while initializing promotion.",
                ephemeral=True
            )

    @app_commands.command(
        name="demote",
        description="Update a member's rank to a lower position"
    )
    @app_commands.checks.has_any_role("Magnate", "Chairman")
    async def demote(self, interaction: discord.Interaction):
        """Demotion command with role selection interface"""
        try:
            # Get eligible members
            eligible_members = [
                member for member in interaction.guild.members
                if not member.bot and
                any(role.name in ROLE_HIERARCHY[1:] for role in member.roles)
            ]

            if not eligible_members:
                await interaction.response.send_message(
                    "❌ No members available for rank adjustment.",
                    ephemeral=True
                )
                return

            # Create and send view
            view = RankSelectionView(self, eligible_members, mode='demote')
            await interaction.response.send_message(
                "Please select a member to adjust rank:",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error in demote command: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while initializing rank adjustment.",
                ephemeral=True
            )

    @app_commands.command(
        name="rank-history",
        description="View a member's rank history"
    )
    @app_commands.checks.has_any_role("Magnate", "Chairman")
    async def rank_history(self, interaction: discord.Interaction, 
                         member: discord.Member):
        """View rank history for a member"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            async with self.bot.db.acquire() as conn:
                # Get rank history
                history = await conn.fetch('''
                    SELECT old_rank, new_rank, reason, timestamp
                    FROM role_history
                    WHERE discord_id = $1
                    ORDER BY timestamp DESC
                    LIMIT 10
                ''', str(member.id))
                
                if not history:
                    await interaction.followup.send(
                        f"No rank history found for {member.mention}",
                        ephemeral=True
                    )
                    return
                
                # Create embed
                embed = discord.Embed(
                    title=f"📊 Rank History for {member.display_name}",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                for record in history:
                    embed.add_field(
                        name=f"{record['timestamp'].strftime('%Y-%m-%d %H:%M')}",
                        value=f"From: {record['old_rank'] or 'None'}\n"
                              f"To: {record['new_rank']}\n"
                              f"Reason: {record['reason']}",
                        inline=False
                    )
                
                await interaction.followup.send(
                    embed=embed,
                    ephemeral=True
                )
                
        except Exception as e:
            logger.error(f"Error retrieving rank history: {e}")
            await interaction.followup.send(
                "❌ Error retrieving rank history.",
                ephemeral=True
            )

async def setup(bot):
    """Safe setup function for promotion cog"""
    try:
        if not bot.get_cog('PromotionCog'):
            await bot.add_cog(PromotionCog(bot))
            logger.info('Promotion cog loaded successfully')
        else:
            logger.info('Promotion cog already loaded, skipping')
    except Exception as e:
        logger.error(f'Error loading promotion cog: {e}')
        raise
