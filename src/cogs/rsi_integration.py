import discord
from discord import app_commands
from discord.ext import commands
import logging
import aiohttp
import json
from typing import Dict, List, Optional, Any
import io
from datetime import datetime, timedelta

from src.utils.constants import (
    RSI_API,
    COMPARE_STATUS,
    CACHE_SETTINGS,
    SYSTEM_MESSAGES
)

logger = logging.getLogger('DraXon_AI')

class LinkAccountModal(discord.ui.Modal, title='Link RSI Account'):
    def __init__(self):
        super().__init__()
        self.handle = discord.ui.TextInput(
            label='RSI Handle',
            placeholder='Enter your RSI Handle (case sensitive)...',
            required=True,
            max_length=50
        )
        self.add_item(self.handle)
        self.cog = None

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            if not self.cog:
                raise ValueError("Modal not properly initialized")
                
            logger.info(f"Processing RSI handle link: {self.handle.value}")
            
            # Check maintenance window
            if await self.cog.check_maintenance_window():
                await interaction.followup.send(
                    SYSTEM_MESSAGES['MAINTENANCE'].format(
                        start_time=RSI_API['MAINTENANCE_START'],
                        duration=RSI_API['MAINTENANCE_DURATION']
                    ),
                    ephemeral=True
                )
                return

            # Get user info
            user_info = await self.cog.get_user_info(self.handle.value)
            if not user_info:
                await interaction.followup.send(
                    "❌ Invalid RSI Handle or API error. Please check your handle and try again.",
                    ephemeral=True
                )
                return

            # Process the account link
            success = await self.cog.process_account_link(interaction, user_info)
            if not success:
                await interaction.followup.send(
                    "❌ Failed to link account. Please try again later.",
                    ephemeral=True
                )

        except Exception as e:
            logger.error(f"Error processing account link: {e}")
            await interaction.followup.send(
                "❌ An error occurred while linking your account.",
                ephemeral=True
            )

class RSIIntegrationCog(commands.Cog):
    """Handles RSI account integration and organization tracking"""
    
    def __init__(self, bot):
        self.bot = bot
        logger.info("RSI Integration cog initialized")

    async def check_maintenance_window(self) -> bool:
        """Check if currently in maintenance window"""
        try:
            current_time = datetime.utcnow()
            maintenance_start = datetime.strptime(
                RSI_API['MAINTENANCE_START'], 
                "%H:%M"
            ).time()
            
            maintenance_end = (
                datetime.combine(current_time.date(), maintenance_start) + 
                timedelta(hours=RSI_API['MAINTENANCE_DURATION'])
            ).time()
            
            current_time = current_time.time()
            
            # Handle maintenance window crossing midnight
            if maintenance_end < maintenance_start:
                return (current_time >= maintenance_start or 
                       current_time <= maintenance_end)
            
            return maintenance_start <= current_time <= maintenance_end
            
        except Exception as e:
            logger.error(f"Error checking maintenance window: {e}")
            return False

    async def get_user_info(self, handle: str) -> Optional[Dict[str, Any]]:
        """Fetch user information from RSI API"""
        try:
            # Check Redis cache first
            cache_key = f'rsi_user:{handle.lower()}'
            cached = await self.bot.redis.get(cache_key)
            if cached:
                return json.loads(cached)

            # Fetch from API
            url = f"{RSI_API['BASE_URL']}/{RSI_API['VERSION']}/{RSI_API['MODE']}/user/{handle}"
            async with self.bot.session.get(url) as response:
                if response.status != 200:
                    return None
                    
                data = await response.json()
                if not data.get('success'):
                    return None

                # Cache the result
                await self.bot.redis.set(
                    cache_key,
                    json.dumps(data['data']),
                    ex=CACHE_SETTINGS['MEMBER_DATA_TTL']
                )
                
                return data['data']

        except Exception as e:
            logger.error(f"Error fetching user info: {e}")
            return None

    async def get_org_members(self) -> List[Dict[str, Any]]:
        """Fetch organization members from RSI API"""
        try:
            # Check Redis cache
            cache_key = f'org_members:{RSI_API["ORGANIZATION_SID"]}'
            cached = await self.bot.redis.get(cache_key)
            if cached:
                return json.loads(cached)

            members = []
            page = 1
            
            while True:
                url = (f"{RSI_API['BASE_URL']}/{RSI_API['VERSION']}/"
                      f"{RSI_API['MODE']}/organization_members/"
                      f"{RSI_API['ORGANIZATION_SID']}")
                
                params = {'page': page}
                
                async with self.bot.session.get(url, params=params) as response:
                    if response.status != 200:
                        break
                        
                    data = await response.json()
                    if not data.get('success') or not data.get('data'):
                        break
                        
                    members.extend(data['data'])
                    
                    if len(data['data']) < RSI_API['MEMBERS_PER_PAGE']:
                        break
                        
                    page += 1

            # Cache the results
            if members:
                await self.bot.redis.set(
                    cache_key,
                    json.dumps(members),
                    ex=CACHE_SETTINGS['ORG_DATA_TTL']
                )

            return members

        except Exception as e:
            logger.error(f"Error fetching org members: {e}")
            return []

    async def process_account_link(self, 
                                 interaction: discord.Interaction,
                                 user_data: Dict[str, Any]) -> bool:
        """Process account linking and verification"""
        try:
            profile = user_data.get('profile', {})
            main_org = user_data.get('organization', {})
            affiliations = user_data.get('affiliation', [])

            if not profile:
                await interaction.followup.send(
                    "❌ Could not retrieve profile information.",
                    ephemeral=True
                )
                return False

            # Check DraXon membership
            is_main_org = main_org.get('sid') == RSI_API['ORGANIZATION_SID']
            is_affiliate = any(
                org.get('sid') == RSI_API['ORGANIZATION_SID'] 
                for org in affiliations
            )

            if not is_main_org and not is_affiliate:
                await interaction.followup.send(
                    "⚠️ Your RSI Handle was found, but you don't appear to be a member "
                    "of our organization. Please join our organization first and try again.",
                    ephemeral=True
                )
                return False

            # Get DraXon org data
            draxon_org = (
                main_org if is_main_org else 
                next(org for org in affiliations 
                     if org.get('sid') == RSI_API['ORGANIZATION_SID'])
            )

            # Prepare data for storage
            rsi_data = {
                'discord_id': str(interaction.user.id),
                'sid': profile.get('id', '').replace('#', ''),
                'handle': profile.get('handle'),
                'display_name': profile.get('display'),
                'enlisted': profile.get('enlisted'),
                'org_sid': draxon_org.get('sid'),
                'org_name': draxon_org.get('name'),
                'org_rank': draxon_org.get('rank'),
                'org_stars': draxon_org.get('stars', 0),
                'org_status': 'Main' if is_main_org else 'Affiliate',
                'verified': True,
                'last_updated': datetime.utcnow().isoformat(),
                'raw_data': user_data
            }

            # Store in database
            async with self.bot.db.acquire() as conn:
                async with conn.transaction():
                    # Store member data
                    await conn.execute('''
                        INSERT INTO rsi_members (
                            discord_id, handle, sid, display_name, enlisted,
                            org_status, org_rank, org_stars, verified,
                            last_updated, raw_data
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                        ON CONFLICT (discord_id) DO UPDATE
                        SET handle = EXCLUDED.handle,
                            sid = EXCLUDED.sid,
                            display_name = EXCLUDED.display_name,
                            enlisted = EXCLUDED.enlisted,
                            org_status = EXCLUDED.org_status,
                            org_rank = EXCLUDED.org_rank,
                            org_stars = EXCLUDED.org_stars,
                            verified = EXCLUDED.verified,
                            last_updated = EXCLUDED.last_updated,
                            raw_data = EXCLUDED.raw_data
                    ''', *rsi_data.values())

                    # Log verification
                    await conn.execute('''
                        INSERT INTO verification_history (
                            discord_id, action, status, timestamp, details
                        ) VALUES ($1, $2, $3, NOW(), $4)
                    ''', str(interaction.user.id), 'link', True, 
                        json.dumps({
                            'handle': rsi_data['handle'],
                            'org_status': rsi_data['org_status']
                        }))

            # Create response embed
            embed = discord.Embed(
                title="✅ RSI Account Successfully Linked!",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            
            # Account Information
            embed.add_field(
                name="Account Information",
                value=f"🔹 Handle: {rsi_data['handle']}\n"
                      f"🔹 Display Name: {rsi_data['display_name']}\n"
                      f"🔹 Citizen ID: {rsi_data['sid']}\n"
                      f"🔹 Enlisted: {rsi_data['enlisted'][:10]}",
                inline=False
            )
            
            # Organization Status
            embed.add_field(
                name="Organization Status",
                value=f"🔹 Organization: {rsi_data['org_name']}\n"
                      f"🔹 Status: {rsi_data['org_status']}\n"
                      f"🔹 Rank: {rsi_data['org_rank']}\n"
                      f"🔹 Stars: {'⭐' * rsi_data['org_stars']}",
                inline=False
            )

            # Send response
            await interaction.followup.send(embed=embed, ephemeral=True)
            return True

        except Exception as e:
            logger.error(f"Error processing account link: {e}")
            return False

    async def create_comparison_file(self, 
                                   guild: discord.Guild,
                                   org_members: List[Dict[str, Any]]) -> discord.File:
        """Create detailed comparison report"""
        try:
            org_by_handle = {m['handle'].lower(): m for m in org_members}
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            
            # Create comparison table
            lines = [
                "Status | Discord ID | Discord Name | RSI Handle | RSI Display | "
                "Stars | Org Status | Last Updated"
            ]
            lines.append("-" * 140)

            async with self.bot.db.acquire() as conn:
                for member in guild.members:
                    if member.bot:
                        continue

                    # Get member data from database
                    member_data = await conn.fetchrow(
                        'SELECT * FROM rsi_members WHERE discord_id = $1',
                        str(member.id)
                    )
                    
                    if member_data:
                        handle = member_data['handle']
                        org_member = org_by_handle.get(handle.lower())
                        
                        status = (
                            COMPARE_STATUS['match'] if org_member 
                            else COMPARE_STATUS['missing']
                        )
                        display = (
                            org_member['display'] if org_member 
                            else member_data['display_name']
                        )
                        stars = (
                            str(org_member['stars']) if org_member 
                            else str(member_data['org_stars'])
                        )
                        org_status = member_data['org_status']
                        last_updated = member_data['last_updated'].strftime("%Y-%m-%d %H:%M")
                    else:
                        status = COMPARE_STATUS['missing']
                        handle = 'N/A'
                        display = 'N/A'
                        stars = 'N/A'
                        org_status = 'N/A'
                        last_updated = 'Never'
                    
                    lines.append(
                        f"{status} | {member.id} | {member.name} | {handle} | "
                        f"{display} | {stars} | {org_status} | {last_updated}"
                    )

            # Create file
            content = '\n'.join(lines)
            file = discord.File(
                io.StringIO(content),
                filename=f'draxon_comparison_{timestamp}.txt'
            )
            
            return file

        except Exception as e:
            logger.error(f"Error creating comparison file: {e}")
            raise

    @app_commands.command(
        name="draxon-link",
        description="Link your RSI account with Discord"
    )
    async def link_account(self, interaction: discord.Interaction):
        """Command to link RSI account"""
        try:
            # Check if already linked
            async with self.bot.db.acquire() as conn:
                existing = await conn.fetchrow(
                    'SELECT * FROM rsi_members WHERE discord_id = $1',
                    str(interaction.user.id)
                )
                
                if existing:
                    await interaction.response.send_message(
                        "⚠️ You already have a linked RSI account. "
                        "Would you like to update it?",
                        ephemeral=True
                    )
                    return

            # Show link modal
            modal = LinkAccountModal()
            modal.cog = self
            await interaction.response.send_modal(modal)

        except Exception as e:
            logger.error(f"Error in link_account command: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while processing your request.",
                ephemeral=True
            )

    @app_commands.command(
        name="draxon-org",
        description="Display organization member list"
    )
    @app_commands.checks.has_role("Chairman")
    async def org_members(self, interaction: discord.Interaction):
        """Command to display organization members"""
        await interaction.response.defer(ephemeral=True)

        try:
            members = await self.get_org_members()
            if not members:
                await interaction.followup.send(
                    "❌ Failed to fetch organization members.",
                    ephemeral=True
                )
                return

            # Create member table
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            lines = ["Discord ID | Discord Name | RSI Display | RSI Handle | Stars | Status | Rank | Roles"]
            lines.append("-" * 140)

            # Sort by stars (descending)
            members.sort(key=lambda x: x.get('stars', 0), reverse=True)

            async with self.bot.db.acquire() as conn:
                for member in members:
                    # Get Discord info from database
                    discord_data = await conn.fetchrow('''
                        SELECT discord_id, org_status
                        FROM rsi_members 
                        WHERE LOWER(handle) = LOWER($1)
                    ''', member['handle'])

                    discord_member = None
                    if discord_data:
                        discord_member = interaction.guild.get_member(
                            int(discord_data['discord_id'])
                        )

                    discord_id = discord_member.id if discord_member else "N/A"
                    discord_name = discord_member.name if discord_member else "N/A"
                    org_status = discord_data['org_status'] if discord_data else 'Unknown'
                    
                    roles_str = ", ".join(member.get('roles', []))
                    
                    lines.append(
                        f"{discord_id} | {discord_name} | {member['display']} | "
                        f"{member['handle']} | {member.get('stars', 0)} | {org_status} | "
                        f"{member.get('rank', 'Unknown')} | {roles_str}"
                    )

            # Create and send file
            file = discord.File(
                io.StringIO('\n'.join(lines)),
                filename=f'draxon_members_{timestamp}.txt'
            )

            # Create summary embed
            embed = discord.Embed(
                title="📊 Organization Member Summary",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )

            # Add statistics
            total_members = len(members)
            linked_members = sum(1 for m in members if any(
                m['handle'].lower() == member_data['handle'].lower()
                for member_data in await conn.fetch(
                    'SELECT handle FROM rsi_members'
                )
            ))

            embed.add_field(
                name="Member Statistics",
                value=f"👥 Total Members: {total_members}\n"
                      f"🔗 Linked Members: {linked_members}\n"
                      f"❌ Unlinked Members: {total_members - linked_members}",
                inline=False
            )

            # Add rank distribution
            rank_counts = {}
            for member in members:
                rank = member.get('rank', 'Unknown')
                rank_counts[rank] = rank_counts.get(rank, 0) + 1

            rank_info = "\n".join(
                f"• {rank}: {count}" 
                for rank, count in sorted(rank_counts.items())
            )
            embed.add_field(
                name="Rank Distribution",
                value=rank_info,
                inline=False
            )

            await interaction.followup.send(
                embed=embed,
                file=file,
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error in org_members command: {e}")
            await interaction.followup.send(
                "❌ An error occurred while fetching member data.",
                ephemeral=True
            )

    @app_commands.command(
        name="draxon-compare",
        description="Compare Discord members with RSI org members"
    )
    @app_commands.checks.has_role("Chairman")
    async def compare_members(self, interaction: discord.Interaction):
        """Command to compare Discord and Org members"""
        await interaction.response.defer(ephemeral=True)

        try:
            # Fetch org members
            org_members = await self.get_org_members()
            if not org_members:
                await interaction.followup.send(
                    "❌ Failed to fetch organization members.",
                    ephemeral=True
                )
                return

            # Create comparison file
            file = await self.create_comparison_file(
                interaction.guild,
                org_members
            )

            # Create summary embed
            embed = discord.Embed(
                title="🔍 Member Comparison Results",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )

            # Calculate statistics
            async with self.bot.db.acquire() as conn:
                total_discord = len([
                    m for m in interaction.guild.members 
                    if not m.bot
                ])
                
                total_linked = await conn.fetchval(
                    'SELECT COUNT(*) FROM rsi_members'
                )
                
                total_org = len(org_members)
                
                # Find mismatches
                discord_handles = set()
                org_handles = {m['handle'].lower() for m in org_members}
                
                member_data = await conn.fetch('SELECT handle FROM rsi_members')
                for data in member_data:
                    if data['handle']:
                        discord_handles.add(data['handle'].lower())
                
                missing_from_discord = len(org_handles - discord_handles)
                missing_from_org = len(discord_handles - org_handles)

            # Add statistics to embed
            embed.add_field(
                name="Member Counts",
                value=f"👥 Discord Members: {total_discord}\n"
                      f"🔗 Linked Accounts: {total_linked}\n"
                      f"🏢 Organization Members: {total_org}",
                inline=False
            )

            embed.add_field(
                name="Discrepancies",
                value=f"❌ Missing from Discord: {missing_from_discord}\n"
                      f"❓ Missing from Organization: {missing_from_org}",
                inline=False
            )

            embed.add_field(
                name="Legend",
                value=f"{COMPARE_STATUS['match']} Matched\n"
                      f"{COMPARE_STATUS['missing']} Missing\n"
                      f"{COMPARE_STATUS['mismatch']} Mismatched",
                inline=False
            )

            await interaction.followup.send(
                embed=embed,
                file=file,
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error in compare_members command: {e}")
            await interaction.followup.send(
                "❌ An error occurred while comparing members.",
                ephemeral=True
            )

    async def cog_command_error(self, interaction: discord.Interaction, 
                               error: app_commands.AppCommandError):
        """Handle errors in cog commands"""
        if isinstance(error, app_commands.errors.MissingRole):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True
            )
        else:
            logger.error(f"Command error: {error}")
            await interaction.response.send_message(
                "❌ An error occurred while processing the command.",
                ephemeral=True
            )

async def setup(bot):
    """Safe setup function for RSI integration cog"""
    try:
        if not bot.get_cog('RSIIntegrationCog'):
            await bot.add_cog(RSIIntegrationCog(bot))
            logger.info('RSI Integration cog loaded successfully')
        else:
            logger.info('RSI Integration cog already loaded, skipping')
    except Exception as e:
        logger.error(f'Error loading RSI Integration cog: {e}')
        raise