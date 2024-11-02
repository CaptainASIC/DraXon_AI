import discord
from discord.ext import commands, tasks
import logging
import feedparser
import aiohttp
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup

from src.utils.constants import (
    RSI_API,
    STATUS_EMOJIS,
    CACHE_SETTINGS
)

logger = logging.getLogger('DraXon_AI')

class RSIIncidentMonitorCog(commands.Cog):
    """Monitor RSI platform incidents and status"""
    
    def __init__(self, bot):
        self.bot = bot
        self.last_incident_guid = None
        self.max_retries = 3
        self.timeout = 10
        self.system_statuses = {
            'platform': 'operational',
            'persistent-universe': 'operational',
            'electronic-access': 'operational'
        }
        self.check_incidents_task.start()
        logger.info("RSI Incident Monitor initialized")

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.check_incidents_task.cancel()

    async def make_request(self, url: str) -> Optional[str]:
        """Make HTTP request with retries and timeout"""
        for attempt in range(self.max_retries):
            try:
                async with self.bot.session.get(url, timeout=self.timeout) as response:
                    if response.status == 200:
                        return await response.text()
                    
                    logger.warning(f"Request failed with status {response.status}")
                    
            except asyncio.TimeoutError:
                logger.warning(f"Request timeout (attempt {attempt + 1}/{self.max_retries})")
            except Exception as e:
                logger.error(f"Request error: {e}")
            
            if attempt < self.max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        return None

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
                    
                if text.startswith('[20'):  # Date headers
                    if current_section:
                        formatted_text.append('\n'.join(current_section))
                        current_section = []
                    formatted_text.append(f"\n**{text}**")
                else:
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
        """Create rich embed for incident notification"""
        try:
            # Determine color based on incident type
            color = (discord.Color.green() if 'resolved' in incident['title'].lower() else
                    discord.Color.red() if 'major' in incident['title'].lower() else
                    discord.Color.orange() if 'partial' in incident['title'].lower() else
                    discord.Color.blue())

            embed = discord.Embed(
                title=incident['title'],
                description=self.clean_html_content(incident['description']),
                color=color,
                timestamp=incident['timestamp']
            )

            # Add status if available
            if status := incident.get('status'):
                embed.add_field(
                    name="Status",
                    value=f"{STATUS_EMOJIS.get(status, '❓')} {status.title()}",
                    inline=False
                )

            # Add affected systems
            if components := incident.get('components'):
                embed.add_field(
                    name="🎯 Affected Systems",
                    value="\n".join(f"- {component}" for component in components),
                    inline=False
                )

            # Add link if available
            if link := incident.get('link'):
                embed.add_field(
                    name="📑 More Information",
                    value=f"[View on RSI Status Page]({link})",
                    inline=False
                )

            embed.set_footer(text="RSI Status Update")
            return embed
            
        except Exception as e:
            logger.error(f"Error creating incident embed: {e}")
            raise

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

    async def get_latest_incident(self) -> Optional[Dict[str, Any]]:
        """Fetch and process the latest incident"""
        try:
            # Check maintenance window
            if await self.check_maintenance_window():
                logger.info("Currently in maintenance window, skipping check")
                return None

            # Check Redis cache
            cached = await self.bot.redis.get('latest_incident')
            if cached:
                return eval(cached)  # Convert string representation back to dict

            # Fetch from RSS feed
            content = await self.make_request(RSI_API['FEED_URL'])
            if not content:
                return None

            feed = feedparser.parse(content)
            if not feed.entries:
                return None

            latest = feed.entries[0]
            
            # Parse incident data
            incident = {
                'id': latest.guid,
                'title': latest.title,
                'description': latest.description,
                'link': latest.link,
                'timestamp': datetime.now(),
                'components': [
                    cat.term for cat in getattr(latest, 'tags', [])
                    if cat.term not in STATUS_EMOJIS
                ],
                'status': next(
                    (cat.term for cat in getattr(latest, 'tags', [])
                     if cat.term in STATUS_EMOJIS),
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

    async def check_system_status(self) -> Dict[str, str]:
        """Check current system status"""
        try:
            content = await self.make_request(RSI_API['STATUS_URL'])
            if not content:
                return self.system_statuses

            soup = BeautifulSoup(content, 'html.parser')
            status_changed = False

            for component in soup.find_all('div', class_='component'):
                name = component.find('span', class_='name').text.strip().lower()
                status = component.find('span', class_='component-status')
                
                if not status:
                    continue
                    
                status = status.get('data-status', 'unknown')
                
                # Map component to our tracking
                if 'platform' in name:
                    if self.system_statuses['platform'] != status:
                        status_changed = True
                    self.system_statuses['platform'] = status
                elif 'persistent universe' in name:
                    if self.system_statuses['persistent-universe'] != status:
                        status_changed = True
                    self.system_statuses['persistent-universe'] = status
                elif 'arena commander' in name:
                    if self.system_statuses['electronic-access'] != status:
                        status_changed = True
                    self.system_statuses['electronic-access'] = status

            if status_changed:
                # Update Redis cache
                await self.bot.redis.hmset(
                    'system_status',
                    self.system_statuses
                )
                logger.info(f"Status changed: {self.system_statuses}")

            return self.system_statuses

        except Exception as e:
            logger.error(f"Error checking system status: {e}")
            return self.system_statuses

    @tasks.loop(minutes=5)
    async def check_incidents_task(self):
        """Check for new incidents periodically"""
        if not self.bot.is_ready() or not self.bot.incidents_channel_id:
            return

        try:
            # Update system status
            await self.check_system_status()

            # Check for new incidents
            incident = await self.get_latest_incident()
            if not incident or incident['id'] == self.last_incident_guid:
                return

            self.last_incident_guid = incident['id']
            logger.info(f"New incident detected: {incident['title']}")
            
            # Get the notification channel
            channel = self.bot.get_channel(self.bot.incidents_channel_id)
            if not channel:
                logger.error("Incidents channel not found")
                return

            # Create and send embed
            embed = self.create_incident_embed(incident)
            await channel.send(
                content="@everyone New RSI Status Update:",
                embed=embed
            )
            
            # Update Redis
            await self.bot.redis.set('last_incident_id', self.last_incident_guid)
            logger.info(f"Posted new incident: {incident['title']}")

        except Exception as e:
            logger.error(f"Error checking incidents: {e}")

    @check_incidents_task.before_loop
    async def before_incidents_check(self):
        """Setup before starting the incident check loop"""
        await self.bot.wait_until_ready()
        
        # Restore last incident ID from Redis
        self.last_incident_guid = await self.bot.redis.get('last_incident_id')
        
        # Restore system status from Redis
        cached_status = await self.bot.redis.hgetall('system_status')
        if cached_status:
            self.system_statuses.update(cached_status)

    @check_incidents_task.after_loop
    async def after_incidents_check(self):
        """Cleanup after incident check loop ends"""
        if self.last_incident_guid:
            await self.bot.redis.set('last_incident_id', self.last_incident_guid)
        await self.bot.redis.hmset('system_status', self.system_statuses)

async def setup(bot):
    """Safe setup function for RSI incidents monitor cog"""
    try:
        if not bot.get_cog('RSIIncidentMonitorCog'):
            await bot.add_cog(RSIIncidentMonitorCog(bot))
            logger.info('RSI Incidents Monitor cog loaded successfully')
        else:
            logger.info('RSI Incidents Monitor cog already loaded, skipping')
    except Exception as e:
        logger.error(f'Error loading RSI Incidents Monitor cog: {e}')
        raise