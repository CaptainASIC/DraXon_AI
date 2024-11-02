import discord
from discord.ext import commands, tasks
import logging
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Set, Optional, Tuple

from src.utils.constants import (
    ROLE_HIERARCHY,
    ROLE_SETTINGS,
    SYSTEM_MESSAGES,
    CACHE_SETTINGS,
    RSI_API
)

logger = logging.getLogger('DraXon_AI')

class MembershipMonitorCog(commands.Cog):
    """Monitor and manage member roles and verification"""
    
    def __init__(self, bot):
        self.bot = bot
        self.last_check = None
        self.daily_checks.start()
        logger.info("Membership monitor initialized")

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.daily_checks.cancel()

    async def get_unlinked_members(self, guild: discord.Guild) -> List[discord.Member]:
        """Get list of members who haven't linked their RSI account"""
        try:
            # Check Redis cache first
            cache_key = f'unlinked_members:{guild.id}'
            cached = await self.bot.redis.get(cache_key)
            
            if cached:
                member_ids = cached.split(',')
                return [m for m in guild.members if str(m.id) in member_ids and not m.bot]

            # No cache, query database
            unlinked_members = []
            for member in guild.members:
                if member.bot:
                    continue
                
                # Check if member exists in database
                exists = await self.bot.db.fetchval(
                    'SELECT EXISTS(SELECT 1 FROM rsi_members WHERE discord_id = $1)',
                    str(member.id)
                )
                
                if not exists:
                    unlinked_members.append(member)

            # Cache results
            if unlinked_members:
                await self.bot.redis.set(
                    cache_key,
                    ','.join(str(m.id) for m in unlinked_members),
                    ex=CACHE_SETTINGS['VERIFICATION_TTL']
                )

            return unlinked_members

        except Exception as e:
            logger.error(f"Error getting unlinked members: {e}")
            return []

    async def check_member_roles(self, guild: discord.Guild) -> List[Dict]:
        """Check and adjust member roles based on org status"""
        try:
            demotion_log = []
            employee_role = discord.utils.get(guild.roles, name=ROLE_SETTINGS['DEFAULT_DEMOTION_RANK'])
            screening_role = discord.utils.get(guild.roles, name=ROLE_SETTINGS['UNAFFILIATED_RANK'])

            if not employee_role or not screening_role:
                logger.error("Required roles not found")
                return []

            # Get RSI integration cog for org data
            rsi_cog = self.bot.get_cog('RSIIntegrationCog')
            if not rsi_cog:
                logger.error("RSIIntegrationCog not found")
                return []

            # Get current org members from cache or API
            cache_key = f'org_members:{guild.id}'
            cached_members = await self.bot.redis.get(cache_key)
            
            if cached_members:
                org_handles = set(cached_members.split(','))
            else:
                org_members = await rsi_cog.get_org_members()
                if org_members is None:
                    logger.error("Failed to fetch organization members")
                    return []
                
                org_handles = {m['handle'].lower() for m in org_members}
                
                # Cache the handles
                await self.bot.redis.set(
                    cache_key,
                    ','.join(org_handles),
                    ex=CACHE_SETTINGS['ORG_DATA_TTL']
                )

            # Check each member
            async with self.bot.db.acquire() as conn:
                for member in guild.members:
                    if member.bot:
                        continue

                    try:
                        # Get member data
                        member_data = await conn.fetchrow(
                            'SELECT * FROM rsi_members WHERE discord_id = $1',
                            str(member.id)
                        )
                        
                        if not member_data:
                            continue

                        current_roles = [role.name for role in member.roles]
                        current_rank = next((r for r in current_roles if r in ROLE_HIERARCHY), None)
                        
                        # Check if member is in org
                        member_handle = member_data['handle'].lower()
                        in_org = member_handle in org_handles

                        if not in_org:
                            # Member not in org - set to Screening
                            if current_rank != ROLE_SETTINGS['UNAFFILIATED_RANK']:
                                await self._handle_demotion(
                                    member,
                                    guild,
                                    current_rank,
                                    ROLE_SETTINGS['UNAFFILIATED_RANK'],
                                    SYSTEM_MESSAGES['DEMOTION_REASONS']['not_in_org'],
                                    demotion_log
                                )
                            continue

                        # Check affiliate status
                        is_affiliate = member_data['org_status'] == 'Affiliate'
                        
                        if is_affiliate and current_rank:
                            max_allowed_index = ROLE_HIERARCHY.index(ROLE_SETTINGS['LEADERSHIP_MAX_RANK'])
                            current_index = ROLE_HIERARCHY.index(current_rank)
                            
                            if current_index > max_allowed_index:
                                await self._handle_demotion(
                                    member,
                                    guild,
                                    current_rank,
                                    ROLE_SETTINGS['DEFAULT_DEMOTION_RANK'],
                                    SYSTEM_MESSAGES['DEMOTION_REASONS']['affiliate'],
                                    demotion_log
                                )

                    except Exception as e:
                        logger.error(f"Error processing member {member.name}: {e}")
                        continue

            return demotion_log

        except Exception as e:
            logger.error(f"Error in check_member_roles: {e}")
            return []

    async def _handle_demotion(self, 
                             member: discord.Member,
                             guild: discord.Guild,
                             old_rank: str,
                             new_rank: str,
                             reason: str,
                             demotion_log: List[Dict]) -> None:
        """Handle member demotion process"""
        try:
            # Remove current rank role
            if old_rank:
                old_role = discord.utils.get(guild.roles, name=old_rank)
                if old_role and old_role in member.roles:
                    await member.remove_roles(old_role)

            # Add new role
            new_role = discord.utils.get(guild.roles, name=new_rank)
            if new_role:
                await member.add_roles(new_role)

            # Log the demotion
            demotion_log.append({
                'member': member,
                'old_rank': old_rank or "None",
                'new_rank': new_rank,
                'reason': reason
            })

            # Record in database
            async with self.bot.db.acquire() as conn:
                await conn.execute('''
                    INSERT INTO role_history (discord_id, old_rank, new_rank, reason)
                    VALUES ($1, $2, $3, $4)
                ''', str(member.id), old_rank, new_rank, reason)

        except Exception as e:
            logger.error(f"Error handling demotion for {member.name}: {e}")

    async def send_demotion_notifications(self, guild: discord.Guild, 
                                        demotions: List[Dict]) -> None:
        """Send notifications about demotions"""
        if not demotions or not self.bot.demotion_channel_id:
            return

        channel = self.bot.get_channel(self.bot.demotion_channel_id)
        if not channel:
            logger.error("Demotion channel not found")
            return

        for demotion in demotions:
            try:
                embed = discord.Embed(
                    title="🔄 Rank Update",
                    description=f"{demotion['member'].mention} has been updated to {demotion['new_rank']}",
                    color=discord.Color.orange(),
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(name="Previous Rank", value=demotion['old_rank'], inline=True)
                embed.add_field(name="New Rank", value=demotion['new_rank'], inline=True)
                embed.add_field(name="Reason", value=demotion['reason'], inline=False)

                await channel.send(embed=embed)
                
                # Try to DM the member
                try:
                    await demotion['member'].send(
                        f"Your rank has been updated from {demotion['old_rank']} to "
                        f"{demotion['new_rank']} due to: {demotion['reason']}"
                    )
                except discord.Forbidden:
                    logger.warning(f"Could not send DM to {demotion['member'].name}")

            except Exception as e:
                logger.error(f"Error sending demotion notification: {e}")

    async def send_unlinked_reminders(self, guild: discord.Guild) -> None:
        """Send reminders to unlinked members and summary to notification channel"""
        if not self.bot.reminder_channel_id:
            return

        try:
            unlinked_members = await self.get_unlinked_members(guild)
            if not unlinked_members:
                return

            # Send DMs to unlinked members
            for member in unlinked_members:
                try:
                    await member.send(SYSTEM_MESSAGES['UNLINKED_REMINDER'])
                except discord.Forbidden:
                    logger.warning(f"Could not send DM to {member.name}")
                except Exception as e:
                    logger.error(f"Error sending reminder to {member.name}: {e}")

            # Send summary to notification channel
            channel = self.bot.get_channel(self.bot.reminder_channel_id)
            if channel:
                embed = discord.Embed(
                    title="📊 Unlinked Members Report",
                    description="The following members have not yet linked their RSI accounts:",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                members_list = "\n".join([f"• {member.mention}" for member in unlinked_members])
                if len(members_list) > 1024:  # Discord field value limit
                    members_list = members_list[:1021] + "..."
                
                embed.add_field(
                    name=f"Unlinked Members ({len(unlinked_members)})",
                    value=members_list or "No unlinked members",
                    inline=False
                )
                
                await channel.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in send_unlinked_reminders: {e}")

    @tasks.loop(hours=24)
    async def daily_checks(self):
        """Run daily membership checks"""
        logger.info("Starting daily membership checks")
        
        current_time = datetime.utcnow()
        if self.last_check:
            time_since_check = (current_time - self.last_check).total_seconds() / 3600
            if time_since_check < 23:  # Ensure at least 23 hours between checks
                return

        self.last_check = current_time
        
        for guild in self.bot.guilds:
            try:
                logger.info(f"Running checks for guild: {guild.name}")
                
                # Perform role checks and get demotion log
                demotions = await self.check_member_roles(guild)
                logger.info(f"Found {len(demotions)} role updates needed")
                
                # Send demotion notifications
                await self.send_demotion_notifications(guild, demotions)
                
                # Send reminders to unlinked members
                await self.send_unlinked_reminders(guild)
                
                logger.info(f"Completed daily checks for guild: {guild.name}")
                
            except Exception as e:
                logger.error(f"Error in daily checks for guild {guild.name}: {e}")

    @daily_checks.before_loop
    async def before_daily_checks(self):
        """Wait for bot to be ready before starting checks"""
        await self.bot.wait_until_ready()
        
        # Wait until configured time
        now = datetime.utcnow()
        target_hour = int(RSI_API['MAINTENANCE_START'].split(':')[0])
        
        if now.hour >= target_hour:
            tomorrow = now + timedelta(days=1)
            next_run = tomorrow.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        else:
            next_run = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
            
        await discord.utils.sleep_until(next_run)

async def setup(bot):
    """Safe setup function for membership monitor cog"""
    try:
        if not bot.get_cog('MembershipMonitorCog'):
            await bot.add_cog(MembershipMonitorCog(bot))
            logger.info('Membership monitor cog loaded successfully')
        else:
            logger.info('Membership monitor cog already loaded, skipping')
    except Exception as e:
        logger.error(f'Error loading membership monitor cog: {e}')
        raise