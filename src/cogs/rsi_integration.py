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
    RSI_API,
    COMPARE_STATUS,
    CACHE_SETTINGS,
    SYSTEM_MESSAGES,
    ROLE_SETTINGS
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
        """Handle account linking modal submission"""
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
            now = datetime.utcnow().time()
            maintenance_start = datetime.strptime(
                RSI_API['MAINTENANCE_START'], 
                "%H:%M"
            ).time()
            
            # Calculate end time
            maintenance_end = (
                datetime.combine(datetime.utcnow().date(), maintenance_start) +
                timedelta(hours=RSI_API['MAINTENANCE_DURATION'])
            ).time()
            
            # Handle window crossing midnight
            if maintenance_end < maintenance_start:
                return (now >= maintenance_start or now <= maintenance_end)
            
            return maintenance_start <= now <= maintenance_end

        except Exception as e:
            logger.error(f"Error checking maintenance window: {e}")
            return False

    async def make_api_request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make request to RSI API with retries and caching"""
        cache_key = f"rsi_api:{endpoint}:{json.dumps(params or {})}"
        
        try:
            # Check cache first
            cached = await self.bot.redis.get(cache_key)
            if cached:
                return json.loads(cached)

            # Make API request with retries
            url = f"{RSI_API['BASE_URL']}/{RSI_API['VERSION']}/{RSI_API['MODE']}/{endpoint}"
            logger.info(f"Making API request to: {url}")
            
            for attempt in range(3):
                try:
                    async with self.bot.session.get(url, params=params) as response:
                        response_text = await response.text()
                        if response.status == 200:
                            try:
                                data = json.loads(response_text)
                                
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
            cache_key = f'org_members:{RSI_API["ORGANIZATION_SID"]}'
            cached = await self.bot.redis.get(cache_key)
            if cached:
                return json.loads(cached)

            members = []
            page = 1
            
            while True:
                params = {'page': page}
                data = await self.make_api_request(
                    f"organization_members/{RSI_API['ORGANIZATION_SID']}",
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
                
                if len(data['data']) < RSI_API['MEMBERS_PER_PAGE']:
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

    # ... rest of the file remains unchanged ...
