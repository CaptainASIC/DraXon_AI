import discord
from discord import app_commands
from discord.ext import commands, tasks
import logging
import feedparser
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup

from src.utils.constants import (
    RSI_API,
    STATUS_EMOJIS,
    CACHE_SETTINGS,
    SYSTEM_MESSAGES
)

logger = logging.getLogger('DraXon_AI')

class RSIIncidentMonitorCog(commands.Cog):
    """Monitor and report RSI service incidents"""
    
    def __init__(self, bot):
        self.bot = bot
        self.last_incident_guid = None
        self.max_retries = 3
        self.timeout = 10
        self.check_incidents_task.start()
        logger.info("RSI Incident Monitor initialized")

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.check_incidents_task.cancel()

    async def make_request(self) -> Optional[str]:
        """Make HTTP request with retries and error handling"""
        for attempt in range(self.max_retries):
            try:
                async with self.bot.session.get(
                    RSI_API['FEED_URL'],
                    timeout=self.timeout
                ) as response:
                    if response.status == 200:
                        return await response.text()
                        
                    logger.warning(f"Request attempt {attempt + 1} failed: {response.status}")
                    
            except asyncio.TimeoutError:
                logger.warning(f"Request timeout (attempt {attempt + 1}/{self.max_retries})")
            except Exception as e:
                logger.error(f"Request error: {e}")
                
            if attempt < self.max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                
        return None

    def clean_html_content(self, html_content: str) -> str:
        """Clean and format HTML content for Discord"""
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

    async def get_latest_incident(self) -> Optional[Dict[str, Any]]:
        """Fetch and process the latest incident"""
        try:
            # Check maintenance window
            if await self.check_maintenance_window():
                logger.info("Currently in maintenance window, skipping check")
                return None

            # Check Redis cache first
            cached = await self.bot.redis.get('latest_incident')
            if cached:
                return json.loads(cached)

            # Fetch from feed
            content = await self.make_request()
            if not content:
                return None

            feed = feedparser.parse(content)
            if not feed.entries:
                return None

            # Process latest entry
            latest = feed.entries[0]
            incident = {
                'guid': latest.guid,
                'title': latest.title,
                'description': latest.description,
                'link': latest.link,
                'timestamp': datetime.now(),
                'components': [
                    tag.term for tag in getattr(latest, 'tags', [])
                    if tag.term not in STATUS_EMOJIS
                ],
                'status': next(
                    (tag.term for tag in getattr(latest, 'tags', [])
                     if tag.term in STATUS_EMOJIS),
                    'unknown'
                )
            }

            # Cache the incident
            await self.bot.redis.set(
                'latest_incident',
                json.dumps(incident),
                ex=CACHE_SETTINGS['STATUS_TTL']
            )
            
            # Store in history
            await self.store_incident_history(incident)

            return incident

        except Exception as e:
            logger.error(f"Error getting latest incident: {e}")
            return None

    async def store_incident_history(self, incident: Dict[str, Any]) -> None:
        """Store incident in database for history"""
        try:
            async with self.bot.db.acquire() as conn:
                await conn.execute('''
                    INSERT INTO incident_history (
                        guid, title, description, status, 
                        components, link, timestamp
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                ''', incident['guid'], incident['title'], 
                    incident['description'], incident['status'],
                    json.dumps(incident['components']), incident['link'],
                    incident['timestamp']
                )
        except Exception as e:
            logger.error(f"Error storing incident history: {e}")

    @tasks.loop(minutes=5)
    async def check_incidents_task(self):
        """Check for new incidents periodically"""
        if not self.bot.is_ready() or not self.bot.incidents_channel_id:
            return

        try:
            # Check for new incidents
            incident = await self.get_latest_incident()
            if not incident or incident['guid'] == self.last_incident_guid:
                return

            self.last_incident_guid = incident['guid']
            logger.info(f"New incident detected: {incident['title']}")
            
            # Get notification channel
            channel = self.bot.get_channel(self.bot.incidents_channel_id)
            if not channel:
                logger.error("Incidents channel not found")
                return

            # Create and send embed
            embed = self.create_incident_embed(incident)
            
            # Add mentions based on severity
            content = "@everyone" if "major" in incident['title'].lower() else None
            
            message = await channel.send(content=content, embed=embed)
            
            # Pin major incidents
            if "major" in incident['title'].lower():
                await message.pin()
                
            # Store in Redis for quick access
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

    @check_incidents_task.after_loop
    async def after_incidents_check(self):
        """Cleanup after incident check loop ends"""
        if self.last_incident_guid:
            await self.bot.redis.set('last_incident_id', self.last_incident_guid)

    @app_commands.command(
        name="incidents",
        description="View recent RSI incidents"
    )
    async def view_incidents(self, interaction: discord.Interaction):
        """View recent incidents command"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get recent incidents from database
            async with self.bot.db.acquire() as conn:
                incidents = await conn.fetch('''
                    SELECT * FROM incident_history
                    ORDER BY timestamp DESC
                    LIMIT 5
                ''')
                
            if not incidents:
                await interaction.followup.send(
                    "No recent incidents found.",
                    ephemeral=True
                )
                return
                
            # Create embed for each incident
            embeds = []
            for incident in incidents:
                embed = discord.Embed(
                    title=incident['title'],
                    description=self.clean_html_content(incident['description']),
                    color=(discord.Color.green() if 'resolved' in incident['title'].lower()
                          else discord.Color.red() if 'major' in incident['title'].lower()
                          else discord.Color.orange() if 'partial' in incident['title'].lower()
                          else discord.Color.blue()),
                    timestamp=incident['timestamp']
                )
                
                if incident['status']:
                    embed.add_field(
                        name="Status",
                        value=f"{STATUS_EMOJIS.get(incident['status'], '❓')} {incident['status'].title()}",
                        inline=False
                    )
                    
                if components := json.loads(incident['components']):
                    embed.add_field(
                        name="🎯 Affected Systems",
                        value="\n".join(f"- {component}" for component in components),
                        inline=False
                    )
                    
                if incident['link']:
                    embed.add_field(
                        name="📑 More Information",
                        value=f"[View on RSI Status Page]({incident['link']})",
                        inline=False
                    )
                    
                embeds.append(embed)
                
            await interaction.followup.send(
                content="Recent RSI Incidents:",
                embeds=embeds,
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Error in view_incidents command: {e}")
            await interaction.followup.send(
                "❌ Error retrieving incidents.",
                ephemeral=True
            )

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