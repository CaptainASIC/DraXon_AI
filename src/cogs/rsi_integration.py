import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import discord
from discord import app_commands
from discord.ext import commands
import logging
import aiohttp
import json
import io
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import asyncio

from src.utils.constants import (
    COMPARE_STATUS,
    CACHE_SETTINGS,
    SYSTEM_MESSAGES
)
from src.config.settings import get_settings

logger = logging.getLogger('DraXon_OCULUS')

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
        """Handle account linking modal submission"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            if not self.cog:
                raise ValueError("Modal not properly initialized")
                
            logger.info(f"Processing RSI handle link: {self.handle.value}")
            
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
        self.settings = get_settings()
        logger.info("RSI Integration cog initialized")

    async def make_api_request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make request to RSI API with retries and caching"""
        cache_key = f"rsi_api:{endpoint}:{json.dumps(params or {})}"
        
        try:
            # Check cache first
            cached = await self.bot.redis.get(cache_key)
            if cached:
                return json.loads(cached)

            # Construct URL with API key in path
            url = f"{self.settings.rsi_api_base_url}/{self.settings.rsi_api_key}/v1/{self.settings.api_mode}/{endpoint}"
            
            logger.info(f"Making API request to: {url}")
            
            for attempt in range(3):
                try:
                    async with self.bot.session.get(url, params=params) as response:
                        response_text = await response.text()
                        logger.debug(f"API Response: {response_text}")
                        
                        if response.status == 200:
                            try:
                                data = json.loads(response_text)
                                
                                # Check if API request was successful
                                if not data.get('success'):
                                    logger.error(f"API request unsuccessful: {data}")
                                    return None

                                # Cache successful response
                                await self.bot.redis.set(
                                    cache_key,
                                    json.dumps(data),
                                    ex=CACHE_SETTINGS['API_TTL']
                                )
                                
                                return data
                            except json.JSONDecodeError as e:
                                logger.error(f"Failed to parse API response: {e}")
                                logger.error(f"Response text: {response_text}")
                                return None
                        elif response.status == 429:  # Rate limit
                            retry_after = int(response.headers.get('Retry-After', 60))
                            logger.warning(f"Rate limited, waiting {retry_after} seconds")
                            await asyncio.sleep(retry_after)
                        else:
                            logger.error(f"API request failed with status {response.status}: {response_text}")
                            await asyncio.sleep(2 ** attempt)
                            
                except Exception as e:
                    logger.error(f"Request attempt {attempt + 1} failed: {e}")
                    if attempt < 2:  # Don't sleep on last attempt
                        await asyncio.sleep(2 ** attempt)
            
            return None

        except Exception as e:
            logger.error(f"Error making API request: {e}")
            return None

    async def get_org_info(self) -> Optional[Dict[str, Any]]:
        """Get organization information"""
        try:
            # Check Redis cache first
            cache_key = f'org_info:{self.settings.rsi_organization_sid}'
            cached = await self.bot.redis.get(cache_key)
            if cached:
                return json.loads(cached)

            # Make API request
            response = await self.make_api_request(f"organization/{self.settings.rsi_organization_sid}")
            if not response or not response.get('success'):
                logger.error(f"Failed to get org info: {response}")
                return None

            data = response['data']
            
            # Cache the result
            await self.bot.redis.set(
                cache_key,
                json.dumps(data),
                ex=CACHE_SETTINGS['ORG_DATA_TTL']
            )
            
            return data

        except Exception as e:
            logger.error(f"Error fetching org info: {e}")
            return None

    async def get_user_info(self, handle: str) -> Optional[Dict[str, Any]]:
        """Get user information from RSI API"""
        try:
            # Check Redis cache first
            cache_key = f'rsi_user:{handle.lower()}'
            cached = await self.bot.redis.get(cache_key)
            if cached:
                return json.loads(cached)

            # Make API request
            response = await self.make_api_request(f"user/{handle}")
            if not response:
                logger.error(f"Failed to get user info for handle: {handle}")
                return None

            if not response.get('success'):
                logger.error(f"API request unsuccessful for handle {handle}: {response}")
                return None

            data = response['data']
            
            # Cache the result
            await self.bot.redis.set(
                cache_key,
                json.dumps(data),
                ex=CACHE_SETTINGS['MEMBER_DATA_TTL']
            )
            
            return data

        except Exception as e:
            logger.error(f"Error fetching user info: {e}")
            return None

    async def get_org_members(self) -> List[Dict[str, Any]]:
        """Get all organization members from RSI API"""
        try:
            # Check Redis cache
            cache_key = f'org_members:{self.settings.rsi_organization_sid}'
            cached = await self.bot.redis.get(cache_key)
            if cached:
                return json.loads(cached)

            members = []
            page = 1
            
            while True:
                params = {'page': page}
                data = await self.make_api_request(
                    f"organization_members/{self.settings.rsi_organization_sid}",
                    params
                )
                
                if not data:
                    logger.error(f"Failed to get org members page {page}")
                    break

                if not data.get('success'):
                    logger.error(f"API request unsuccessful for page {page}: {data}")
                    break

                if not data.get('data'):
                    break

                members.extend(data['data'])
                
                if len(data['data']) < 32:  # RSI API returns 32 members per page
                    break
                    
                page += 1
                await asyncio.sleep(1)  # Rate limiting

            # Cache the results
            if members:
                await self.bot.redis.set(
                    cache_key,
                    json.dumps(members),
                    ex=CACHE_SETTINGS['ORG_DATA_TTL']
                )
                logger.info(f"Cached {len(members)} org members")
            else:
                logger.error("No org members found")

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
            is_main_org = main_org.get('sid') == self.settings.rsi_organization_sid
            is_affiliate = any(
                org.get('sid') == self.settings.rsi_organization_sid 
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
                     if org.get('sid') == self.settings.rsi_organization_sid)
            )

            # Convert timestamp to datetime
            current_time = datetime.utcnow()

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
                'last_updated': current_time,
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
                    ''', str(interaction.user.id), rsi_data['handle'], rsi_data['sid'],
                        rsi_data['display_name'], rsi_data['enlisted'], rsi_data['org_status'],
                        rsi_data['org_rank'], rsi_data['org_stars'], rsi_data['verified'],
                        rsi_data['last_updated'], json.dumps(rsi_data['raw_data']))

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

            # Cache member data
            await self.bot.redis.set(
                f'member:{interaction.user.id}',
                json.dumps({**rsi_data, 'last_updated': rsi_data['last_updated'].isoformat()}),
                ex=CACHE_SETTINGS['MEMBER_DATA_TTL']
            )

            await interaction.followup.send(embed=embed, ephemeral=True)
            return True

        except Exception as e:
            logger.error(f"Error processing account link: {e}")
            return False

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
    @app_commands.checks.has_role("Magnate")
    async def org_members(self, interaction: discord.Interaction):
        """Command to display organization members"""
        await interaction.response.defer(ephemeral=True)

        try:
            # Get org info first
            org_info = await self.get_org_info()
            if not org_info:
                await interaction.followup.send(
                    "❌ Failed to fetch organization data.",
                    ephemeral=True
                )
                return

            # Get members
            members = await self.get_org_members()
            if not members:
                await interaction.followup.send(
                    "❌ Failed to fetch organization members.",
                    ephemeral=True
                )
                return

            # Create member table
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            lines = [
                "Discord ID | Discord Name | RSI Display | RSI Handle | "
                "Stars | Status | Rank | Roles"
            ]
            lines.append("-" * 140)

            # Sort by stars (descending)
            members.sort(key=lambda x: x.get('stars', 0), reverse=True)

            async with self.bot.db.acquire() as conn:
                # Convert async generator to list
                db_members = await conn.fetch('SELECT handle, discord_id, org_status FROM rsi_members')
                db_members_dict = {
                    m['handle'].lower(): {
                        'discord_id': m['discord_id'],
                        'org_status': m['org_status']
                    } for m in db_members
                }

                for member in members:
                    handle = member['handle']
                    db_data = db_members_dict.get(handle.lower(), {})
                    discord_id = db_data.get('discord_id', 'N/A')
                    org_status = db_data.get('org_status', 'Unknown')

                    discord_member = None
                    if discord_id != 'N/A':
                        discord_member = interaction.guild.get_member(int(discord_id))

                    discord_name = discord_member.name if discord_member else "N/A"
                    roles_str = ", ".join(member.get('roles', []))
                    
                    lines.append(
                        f"{discord_id} | {discord_name} | {member['display']} | "
                        f"{handle} | {member.get('stars', 0)} | {org_status} | "
                        f"{member.get('rank', 'Unknown')} | {roles_str}"
                    )

                # Create and send file
                file = discord.File(
                    io.StringIO('\n'.join(lines)),
                    filename=f'draxon_oculus_members_{timestamp}.txt'
                )

                # Create summary embed
                embed = discord.Embed(
                    title=f"📊 {org_info['name']} Member Summary",
                    description=f"Organization SID: {org_info['sid']}\n"
                               f"Total Members: {org_info['members']}\n"
                               f"Primary Focus: {org_info['focus']['primary']['name']}\n"
                               f"Secondary Focus: {org_info['focus']['secondary']['name']}",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )

                if org_info.get('banner'):
                    embed.set_image(url=org_info['banner'])

                # Add statistics
                total_members = len(members)
                linked_members = len([m for m in members if m['handle'].lower() in db_members_dict])

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
    @app_commands.checks.has_role("Magnate")
    async def compare_members(self, interaction: discord.Interaction):
        """Compare Discord and Org members"""
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
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            lines = [
                "Status | Discord ID | Discord Name | RSI Handle | RSI Display | "
                "Stars | Org Status | Last Updated"
            ]
            lines.append("-" * 140)

            org_by_handle = {m['handle'].lower(): m for m in org_members}
            
            async with self.bot.db.acquire() as conn:
                # Get all member data at once
                db_members = await conn.fetch('SELECT * FROM rsi_members')
                db_members_by_id = {m['discord_id']: m for m in db_members}
                
                # Get total linked count
                total_linked = len(db_members)
                
                # Process Discord members
                for member in interaction.guild.members:
                    if member.bot:
                        continue
                        
                    member_data = db_members_by_id.get(str(member.id))
                    
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

                # Create comparison file
                file = discord.File(
                    io.StringIO('\n'.join(lines)),
                    filename=f'draxon_oculus_comparison_{timestamp}.txt'
                )

                # Create summary embed
                embed = discord.Embed(
                    title="🔍 Member Comparison Results",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )

                # Calculate statistics
                total_discord = len([m for m in interaction.guild.members if not m.bot])
                total_org = len(org_members)
                
                discord_handles = {m['handle'].lower() for m in db_members if m['handle']}
                org_handles = {m['handle'].lower() for m in org_members}
                
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

    @app_commands.command(
        name="draxon-refresh",
        description="Refresh RSI organization data"
    )
    @app_commands.checks.has_role("Magnate")
    async def refresh_org_data(self, interaction: discord.Interaction):
        """Force refresh of organization data"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Clear caches
            await self.bot.redis.delete(f'org_members:{self.settings.rsi_organization_sid}')
            await self.bot.redis.delete(f'org_info:{self.settings.rsi_organization_sid}')
            pattern = f'rsi_user:*'
            keys = await self.bot.redis.keys(pattern)
            if keys:
                await self.bot.redis.delete(*keys)
                
            # Fetch fresh data
            org_info = await self.get_org_info()
            if not org_info:
                await interaction.followup.send(
                    "❌ Failed to fetch organization data.",
                    ephemeral=True
                )
                return

            org_members = await self.get_org_members()
            if not org_members:
                await interaction.followup.send(
                    "❌ Failed to fetch organization members.",
                    ephemeral=True
                )
                return
                
            await interaction.followup.send(
                f"✅ Successfully refreshed organization data.\n"
                f"Organization: {org_info['name']}\n"
                f"Total Members: {len(org_members)}",
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Error refreshing org data: {e}")
            await interaction.followup.send(
                "❌ An error occurred while refreshing data.",
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
