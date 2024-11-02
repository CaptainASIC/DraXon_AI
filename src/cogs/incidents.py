import discord
from discord.ext import commands, tasks
import logging
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from src.utils.constants import (
    STATUS_EMOJIS,
    RSI_API,
    CACHE_SETTINGS
)

logger = logging.getLogger('DraXon_AI')

class IncidentsCog(commands.Cog):
    """Cog for handling RSI incident monitoring and notifications"""
    
    def __init__(self, bot):
        self.bot = bot
        self.last_incident_id = None
        self.check_incidents.start()
        logger.info("Incidents cog initialized")

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.check_incidents.cancel()

    def clean_html_content(self, html_content: str) -> str:
        """Clean and format HTML content"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            formatted_text = []
            current_section = []
            
            for p in soup.find_all('p'):
                text = p.get_text().strip()
                if not text:
                    continue
                    
                # Check if this is a date header
                if text.startswith('[20'):  # Date headers like [2024-10-26 Updates]
                    if current_section:
                        formatted_text.append('\n'.join(current_section))
                        current_section = []
                    formatted_text.append(f"\n**{text}**")
                else:
                    # Clean up UTC timestamps
                    if ' UTC - ' in text:
                        time, message = text.split(' UTC - ', 1)
                        text = f"`{time} UTC` - {message}"
                    current_section.append(text)
            
            if current_section:
                formatted_text.append('\n'.join(current_section))
            
            return '\n'.join(formatted_text)
            
        except Exception as e:
            logger.error(f"Error cleaning HTML content: {e}")
            return html_content

    def create_incident_embed(self, incident: Dict[str, Any]) -> discord.Embed:
        """Create an embed for incident notification"""
        try:
            # Determine embed color based on incident type
            color = discord.Color.green() if 'resolved' in incident['title'].lower() else \
                   discord.Color.red() if 'major' in incident['title'].lower() else \
                   discord.Color.orange() if 'partial' in incident['title'].lower() else \
                   discord.Color.blue()

            embed = discord.Embed(
                title=incident['title'],
                description=self.clean_html_content(incident['description']),
                color=color,
                timestamp=incident['timestamp']
            )

            # Add status if available
            if 'status' in incident:
                embed.add_field(
                    name="Status",
                    value=f"{STATUS_EMOJIS.get(incident['status'], '❓')} {incident['status'].title()}",
                    inline=False
                )

            # Add affected systems
            if 'components' in incident:
                embed.add_field(
                    name="🎯 Affected Systems",
                    value="\n".join(f"- {component}" for component in incident['components']),
                    inline=False
                )

            embed.set_footer(text="RSI Status Update")
            return embed
            
        except Exception as e:
            logger.error(f"Error creating incident embed: {e}")
            raise

    async def get_latest_incident(self) -> Optional[Dict[str, Any]]:
        """Fetch the latest incident from RSI feed"""
        try:
            # Check Redis cache first
            cached = await self.bot.redis.get('latest_incident')
            if cached:
                return eval(cached)  # Convert string representation back to dict

            # Fetch from RSI API if no cache
            async with self.bot.session.get(RSI_API['FEED_URL']) as response:
                if response.status != 200:
                    logger.error(f"Failed to fetch incidents: {response.status}")
                    return None

                feed = await response.text()
                soup = BeautifulSoup(feed, 'xml')
                latest = soup.find('item')

                if not latest:
                    return None

                incident = {
                    'id': latest.guid.text if latest.guid else None,
                    'title': latest.title.text if latest.title else 'Unknown Issue',
                    'description': latest.description.text if latest.description else '',
                    'link': latest.link.text if latest.link else None,
                    'timestamp': datetime.now(),
                    'components': [
                        cat.text for cat in latest.find_all('category')
                        if cat.text not in STATUS_EMOJIS
                    ],
                    'status': next(
                        (cat.text for cat in latest.find_all('category')
                         if cat.text in STATUS_EMOJIS),
                        'unknown'
                    )
                }

                # Cache the incident
                await self.bot.redis.set(
                    'latest_incident',
                    str(incident),
                    ex=CACHE_SETTINGS['STATUS_TTL']
                )

                return incident

        except Exception as e:
            logger.error(f"Error fetching latest incident: {e}")
            return None

    @tasks.loop(minutes=5)
    async def check_incidents(self):
        """Check for new incidents periodically"""
        if not self.bot.is_ready() or not self.bot.incidents_channel_id:
            return

        try:
            incident = await self.get_latest_incident()
            if not incident or incident['id'] == self.last_incident_id:
                return

            self.last_incident_id = incident['id']
            
            # Get the notification channel
            channel = self.bot.get_channel(self.bot.incidents_channel_id)
            if not channel:
                logger.error("Incidents channel not found")
                return

            # Create and send embed
            embed = self.create_incident_embed(incident)
            await channel.send(embed=embed)
            
            # Update last incident in Redis
            await self.bot.redis.set('last_incident_id', self.last_incident_id)
            logger.info(f"Posted new incident: {incident['title']}")

        except Exception as e:
            logger.error(f"Error checking incidents: {e}")

    @check_incidents.before_loop
    async def before_incidents_check(self):
        """Setup before starting the incident check loop"""
        await self.bot.wait_until_ready()
        # Restore last incident ID from Redis
        self.last_incident_id = await self.bot.redis.get('last_incident_id')

    @check_incidents.after_loop
    async def after_incidents_check(self):
        """Cleanup after incident check loop ends"""
        if self.last_incident_id:
            await self.bot.redis.set('last_incident_id', self.last_incident_id)

async def setup(bot):
    """Safe setup function for incidents cog"""
    try:
        if not bot.get_cog('IncidentsCog'):
            await bot.add_cog(IncidentsCog(bot))
            logger.info('Incidents cog loaded successfully')
        else:
            logger.info('Incidents cog already loaded, skipping')
    except Exception as e:
        logger.error(f'Error loading incidents cog: {e}')
        raise