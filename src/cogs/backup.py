import discord
from discord import app_commands
from discord.ext import commands
import logging
import json
import datetime
from typing import Dict, Any, Optional, List, Tuple
import io
import asyncio

from src.utils.constants import CHANNEL_PERMISSIONS

logger = logging.getLogger('DraXon_OCULUS')

class BackupCog(commands.Cog):
    """Cog for handling server backup and restore operations"""
    
    def __init__(self, bot):
        self.bot = bot
        logger.info("Backup cog initialized")

    def serialize_overwrites(self, overwrites: Dict[Any, discord.PermissionOverwrite]) -> Dict[str, Dict[str, bool]]:
        """Serialize permission overwrites"""
        serialized = {}
        for target, overwrite in overwrites.items():
            # Store the target type and id
            key = f"role:{target.name}" if isinstance(target, discord.Role) else f"member:{target.id}"
            allow, deny = overwrite.pair()
            serialized[key] = {'allow': allow.value, 'deny': deny.value}
        return serialized

    def serialize_role(self, role: discord.Role) -> Dict[str, Any]:
        """Serialize a role's data"""
        return {
            'name': role.name,
            'permissions': role.permissions.value,
            'color': role.color.value,
            'hoist': role.hoist,
            'mentionable': role.mentionable,
            'position': role.position,
            'id': role.id
        }

    async def backup_pins(self, channel: discord.TextChannel) -> List[Dict[str, Any]]:
        """Backup pinned messages from a channel"""
        pins = []
        try:
            # Get all pins first, then iterate over them
            pinned_messages = await channel.pins()
            for message in pinned_messages:
                pins.append({
                    'content': message.content,
                    'author': str(message.author),
                    'created_at': message.created_at.isoformat(),
                    'attachments': [a.url for a in message.attachments]
                })
            logger.info(f"Backed up {len(pins)} pins from {channel.name}")
        except Exception as e:
            logger.error(f"Error backing up pins from {channel.name}: {e}")
        return pins

    async def serialize_channel(self, channel: discord.abc.GuildChannel) -> Dict[str, Any]:
        """Serialize a channel's data"""
        try:
            base_data = {
                'name': channel.name,
                'type': str(channel.type),
                'position': channel.position,
                'overwrites': self.serialize_overwrites(channel.overwrites),
                'id': channel.id,
                'category_id': channel.category.id if channel.category else None
            }

            # Add type-specific data
            if isinstance(channel, discord.TextChannel):
                text_data = {
                    'topic': channel.topic,
                    'nsfw': channel.nsfw,
                    'slowmode_delay': channel.slowmode_delay,
                    'default_auto_archive_duration': channel.default_auto_archive_duration,
                }
                # Get pins separately since it's async
                pins = await self.backup_pins(channel)
                text_data['pins'] = pins
                base_data.update(text_data)
                
            elif isinstance(channel, discord.VoiceChannel):
                voice_data = {
                    'bitrate': channel.bitrate,
                    'user_limit': channel.user_limit,
                }
                base_data.update(voice_data)

            return base_data

        except Exception as e:
            logger.error(f"Error serializing channel {channel.name}: {e}")
            raise

    async def create_backup(self, guild: discord.Guild) -> Dict[str, Any]:
        """Create a comprehensive backup of the guild"""
        try:
            backup_data = {
                'name': guild.name,
                'icon_url': str(guild.icon.url) if guild.icon else None,
                'verification_level': str(guild.verification_level),
                'default_notifications': str(guild.default_notifications),
                'explicit_content_filter': str(guild.explicit_content_filter),
                'backup_date': datetime.datetime.utcnow().isoformat(),
                'roles': [],
                'channels': [],
                'bot_settings': {}
            }

            # Back up roles (excluding @everyone)
            for role in sorted(guild.roles[1:], key=lambda r: r.position):
                backup_data['roles'].append(self.serialize_role(role))

            # Back up channels
            for channel in guild.channels:
                try:
                    if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                        channel_data = await self.serialize_channel(channel)
                        backup_data['channels'].append(channel_data)
                except Exception as e:
                    logger.error(f"Error backing up channel {channel.name}: {e}")

            # Back up bot settings from Redis
            try:
                async with self.bot.redis.pipeline() as pipe:
                    pipe.hgetall('channel_ids')
                    pipe.hgetall('bot_settings')
                    channel_ids, bot_settings = await pipe.execute()
                    
                    # Handle both bytes and string types for Redis values
                    channel_ids_dict = {}
                    for k, v in channel_ids.items():
                        key = k.decode() if isinstance(k, bytes) else k
                        value = int(v.decode() if isinstance(v, bytes) else v)
                        channel_ids_dict[key] = value

                    settings_dict = {}
                    for k, v in bot_settings.items():
                        key = k.decode() if isinstance(k, bytes) else k
                        value = v.decode() if isinstance(v, bytes) else v
                        settings_dict[key] = value
                    
                    backup_data['bot_settings'] = {
                        'channel_ids': channel_ids_dict,
                        'settings': settings_dict
                    }
            except Exception as e:
                logger.error(f"Error backing up Redis settings: {e}")
                backup_data['bot_settings'] = {
                    'channel_ids': {},
                    'settings': {}
                }

            return backup_data

        except Exception as e:
            logger.error(f"Error creating backup: {e}")
            raise

    def deserialize_overwrites(self, 
                           overwrites_data: Dict[str, Dict[str, int]], 
                           guild: discord.Guild) -> Dict[discord.Role, discord.PermissionOverwrite]:
        """Convert serialized overwrites back to Discord permission overwrites"""
        result = {}
        for key, data in overwrites_data.items():
            target_type, target_id = key.split(':', 1)
            
            if target_type == 'role':
                target = discord.utils.get(guild.roles, name=target_id)
            else:  # member
                target = guild.get_member(int(target_id))
                
            if target:
                overwrite = discord.PermissionOverwrite()
                allow = discord.Permissions(data['allow'])
                deny = discord.Permissions(data['deny'])
                
                for perm, value in allow:
                    if value:
                        setattr(overwrite, perm, True)
                for perm, value in deny:
                    if value:
                        setattr(overwrite, perm, False)
                        
                result[target] = overwrite
                
        return result

    async def restore_pins(self, channel: discord.TextChannel, 
                          pins_data: List[Dict[str, Any]]) -> List[str]:
        """Restore pins to a channel"""
        logs = []
        for pin in pins_data:
            try:
                message = await channel.send(
                    f"📌 Restored Pin from {pin['author']}\n{pin['content']}"
                )
                await message.pin()
                logs.append(f"✅ Restored pin in {channel.name}")
            except Exception as e:
                logs.append(f"⚠️ Error restoring pin in {channel.name}: {e}")
        return logs

    async def restore_backup(self, guild: discord.Guild, 
                           backup_data: Dict[str, Any]) -> List[str]:
        """Restore a guild from backup data"""
        logs = []
        logs.append("Starting restore process...")

        try:
            # Delete existing roles and channels
            logs.append("Cleaning up existing server configuration...")
            
            # Delete non-default roles
            for role in reversed(guild.roles[1:]):
                if role != guild.default_role and role < guild.me.top_role:
                    try:
                        await role.delete()
                        logs.append(f"Deleted role: {role.name}")
                    except Exception as e:
                        logs.append(f"⚠️ Could not delete role {role.name}: {e}")

            # Delete all channels
            for channel in guild.channels:
                try:
                    await channel.delete()
                    logs.append(f"Deleted channel: {channel.name}")
                except Exception as e:
                    logs.append(f"⚠️ Could not delete channel {channel.name}: {e}")

            # Create roles
            role_map = {}
            logs.append("Restoring roles...")
            
            for role_data in sorted(backup_data['roles'], key=lambda r: r['position']):
                try:
                    new_role = await guild.create_role(
                        name=role_data['name'],
                        permissions=discord.Permissions(role_data['permissions']),
                        color=discord.Color(role_data['color']),
                        hoist=role_data['hoist'],
                        mentionable=role_data['mentionable']
                    )
                    role_map[role_data['id']] = new_role
                    logs.append(f"Created role: {new_role.name}")
                except Exception as e:
                    logs.append(f"⚠️ Error creating role {role_data['name']}: {e}")

            # Create channels
            logs.append("Restoring channels...")
            
            # Sort channels by category and position
            channels_by_category: Dict[Optional[int], List[Dict[str, Any]]] = {}
            for channel_data in backup_data['channels']:
                category_id = channel_data.get('category_id')
                if category_id not in channels_by_category:
                    channels_by_category[category_id] = []
                channels_by_category[category_id].append(channel_data)

            # Create categories first
            category_map = {}
            for category_id, channels in channels_by_category.items():
                if category_id is None:
                    continue

                category_data = next(
                    (ch for ch in channels if ch.get('type') == 'category'),
                    None
                )
                if category_data:
                    try:
                        overwrites = self.deserialize_overwrites(
                            category_data['overwrites'],
                            guild
                        )
                        category = await guild.create_category(
                            name=category_data['name'],
                            overwrites=overwrites,
                            position=category_data['position']
                        )
                        category_map[category_id] = category
                        logs.append(f"Created category: {category.name}")
                    except Exception as e:
                        logs.append(f"⚠️ Error creating category: {e}")

            # Create other channels
            for category_id, channels in channels_by_category.items():
                category = category_map.get(category_id)
                for channel_data in sorted(channels, key=lambda c: c['position']):
                    try:
                        channel_type = getattr(discord.ChannelType, channel_data['type'].split('.')[-1])
                        if channel_type == discord.ChannelType.category:
                            continue

                        overwrites = self.deserialize_overwrites(
                            channel_data['overwrites'],
                            guild
                        )

                        if channel_type == discord.ChannelType.text:
                            channel = await guild.create_text_channel(
                                name=channel_data['name'],
                                category=category,
                                topic=channel_data.get('topic'),
                                nsfw=channel_data.get('nsfw', False),
                                slowmode_delay=channel_data.get('slowmode_delay', 0),
                                position=channel_data['position'],
                                overwrites=overwrites
                            )
                            
                            # Restore pins
                            if 'pins' in channel_data and channel_data['pins']:
                                pin_logs = await self.restore_pins(
                                    channel,
                                    channel_data['pins']
                                )
                                logs.extend(pin_logs)

                        elif channel_type == discord.ChannelType.voice:
                            channel = await guild.create_voice_channel(
                                name=channel_data['name'],
                                category=category,
                                bitrate=channel_data.get('bitrate', 64000),
                                user_limit=channel_data.get('user_limit', 0),
                                position=channel_data['position'],
                                overwrites=overwrites
                            )

                        logs.append(f"Created channel: {channel.name}")

                    except Exception as e:
                        logs.append(f"⚠️ Error creating channel {channel_data['name']}: {e}")

            # Restore bot settings
            if 'bot_settings' in backup_data:
                logs.append("Restoring bot settings...")
                
                # Restore channel IDs
                channel_ids = backup_data['bot_settings'].get('channel_ids', {})
                await self.bot.redis.hmset('channel_ids', channel_ids)
                
                # Restore other settings
                settings = backup_data['bot_settings'].get('settings', {})
                await self.bot.redis.hmset('bot_settings', settings)
                
                # Update bot's channel IDs
                self.bot.incidents_channel_id = channel_ids.get('incidents')
                self.bot.promotion_channel_id = channel_ids.get('promotion')
                self.bot.demotion_channel_id = channel_ids.get('demotion')
                self.bot.reminder_channel_id = channel_ids.get('reminder')

            logs.append("✅ Restore process completed!")

        except Exception as e:
            logs.append(f"❌ Critical error during restore: {e}")
            logger.error(f"Critical error during restore: {e}")

        return logs

    @app_commands.command(
        name="draxon-backup",
        description="Create a backup of the server configuration"
    )
    @app_commands.checks.has_role("Magnate")
    async def backup(self, interaction: discord.Interaction):
        """Create a backup of the server"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Create backup
            backup_data = await self.create_backup(interaction.guild)
            
            # Convert to JSON and create file
            backup_json = json.dumps(backup_data, indent=2)
            timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            file = discord.File(
                io.StringIO(backup_json),
                filename=f'draxon_oculus_backup_{timestamp}.json'
            )
            
            # Store backup in Redis with timestamp as key
            await self.bot.redis.set(
                f'backup:{timestamp}',
                backup_json,
                ex=86400  # Expire after 24 hours
            )
            
            await interaction.followup.send(
                "✅ Backup created successfully! Here's your backup file:",
                file=file,
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Error creating backup: {e}")
            await interaction.followup.send(
                f"❌ Error creating backup: {str(e)}",
                ephemeral=True
            )

    @app_commands.command(
        name="draxon-restore",
        description="Restore server configuration from a backup file"
    )
    @app_commands.checks.has_role("Magnate")
    async def restore(self, interaction: discord.Interaction, backup_file: discord.Attachment):
        """Restore from a backup file"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            if not backup_file.filename.endswith('.json'):
                await interaction.followup.send(
                    "❌ Please provide a valid JSON backup file.",
                    ephemeral=True
                )
                return
                
            # Read and validate backup data
            backup_content = await backup_file.read()
            backup_data = json.loads(backup_content.decode('utf-8'))
            
            # Confirm with user
            await interaction.followup.send(
                "⚠️ **Warning**: This will delete all current channels and roles before restoring from backup.\n"
                "Are you sure you want to proceed? Reply with `yes` to continue.",
                ephemeral=True
            )
            
            def check(m):
                return (m.author == interaction.user and 
                       m.channel == interaction.channel and 
                       m.content.lower() == 'yes')
            
            try:
                await self.bot.wait_for('message', timeout=30.0, check=check)
                
                # Send initial status message
                status_message = await interaction.followup.send(
                    "🔄 Starting restore process...",
                    ephemeral=True
                )
                
                # Perform restore
                logs = await self.restore_backup(interaction.guild, backup_data)
                
                # Send logs in chunks due to Discord message length limits
                log_chunks = [logs[i:i + 10] for i in range(0, len(logs), 10)]
                for index, chunk in enumerate(log_chunks, 1):
                    await interaction.followup.send(
                        f"**Restore Progress ({index}/{len(log_chunks)}):**\n" + 
                        '\n'.join(chunk),
                        ephemeral=True
                    )
                
                # Save backup to Redis for recovery if needed
                timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                await self.bot.redis.set(
                    f'restore:{timestamp}',
                    json.dumps(backup_data),
                    ex=86400  # Expire after 24 hours
                )
                
                # Final status update
                await interaction.followup.send(
                    "✅ Restore process completed! Please verify all channels and roles.\n"
                    "A backup of the restored configuration has been saved for 24 hours.",
                    ephemeral=True
                )
                
            except asyncio.TimeoutError:
                await interaction.followup.send(
                    "❌ Confirmation timed out. Restore cancelled.",
                    ephemeral=True
                )
                
        except json.JSONDecodeError:
            await interaction.followup.send(
                "❌ Invalid backup file format. Please ensure the file is a valid JSON backup.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error restoring backup: {e}")
            await interaction.followup.send(
                f"❌ Error restoring backup: {str(e)}",
                ephemeral=True
            )

    @app_commands.command(
        name="list-backups",
        description="List available backups"
    )
    @app_commands.checks.has_role("Magnate")
    async def list_backups(self, interaction: discord.Interaction):
        """List available backups in Redis"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get all backup keys
            backup_keys = await self.bot.redis.keys('backup:*')
            restore_keys = await self.bot.redis.keys('restore:*')
            
            if not backup_keys and not restore_keys:
                await interaction.followup.send(
                    "No backups found.",
                    ephemeral=True
                )
                return
                
            embed = discord.Embed(
                title="🗄️ Available Backups",
                color=discord.Color.blue(),
                timestamp=datetime.datetime.utcnow()
            )
            
            # Add manual backups
            if backup_keys:
                backup_list = []
                for key in backup_keys:
                    timestamp = key.split(':')[1]
                    formatted_time = datetime.datetime.strptime(
                        timestamp,
                        "%Y%m%d_%H%M%S"
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    backup_list.append(f"• {formatted_time}")
                    
                embed.add_field(
                    name="Manual Backups",
                    value='\n'.join(backup_list) or "None",
                    inline=False
                )
            
            # Add restore points
            if restore_keys:
                restore_list = []
                for key in restore_keys:
                    timestamp = key.split(':')[1]
                    formatted_time = datetime.datetime.strptime(
                        timestamp,
                        "%Y%m%d_%H%M%S"
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    restore_list.append(f"• {formatted_time}")
                    
                embed.add_field(
                    name="Restore Points",
                    value='\n'.join(restore_list) or "None",
                    inline=False
                )
            
            embed.set_footer(text="Backups are automatically deleted after 24 hours")
            
            await interaction.followup.send(
                embed=embed,
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Error listing backups: {e}")
            await interaction.followup.send(
                "❌ Error retrieving backup list.",
                ephemeral=True
            )

async def setup(bot):
    """Safe setup function for backup cog"""
    try:
        if not bot.get_cog('BackupCog'):
            await bot.add_cog(BackupCog(bot))
            logger.info('Backup cog loaded successfully')
        else:
            logger.info('Backup cog already loaded, skipping')
    except Exception as e:
        logger.error(f'Error loading backup cog: {e}')
        raise
