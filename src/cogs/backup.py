import discord
from discord import app_commands
from discord.ext import commands
import logging
import json
import datetime
from typing import Dict, Any, Optional, List
import io
import asyncio

from src.utils.constants import CHANNEL_PERMISSIONS
from src.db.repository import MemberRepository

logger = logging.getLogger('DraXon_AI')

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

    def serialize_channel(self, channel: discord.abc.GuildChannel) -> Dict[str, Any]:
        """Serialize a channel's data"""
        base_data = {
            'name': channel.name,
            'type': str(channel.type),
            'position': channel.position,
            'overwrites': self.serialize_overwrites(channel.overwrites),
            'id': channel.id,
            'category_id': channel.category.id if channel.category else None
        }

        if isinstance(channel, discord.TextChannel):
            base_data.update({
                'topic': channel.topic,
                'nsfw': channel.nsfw,
                'slowmode_delay': channel.slowmode_delay,
                'default_auto_archive_duration': channel.default_auto_archive_duration,
                'pins': await self.backup_pins(channel)
            })
        elif isinstance(channel, discord.VoiceChannel):
            base_data.update({
                'bitrate': channel.bitrate,
                'user_limit': channel.user_limit,
            })

        return base_data

    async def backup_pins(self, channel: discord.TextChannel) -> List[Dict[str, Any]]:
        """Backup pinned messages from a channel"""
        pins = []
        try:
            async for message in channel.pins():
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
                if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                    channel_data = await self.serialize_channel(channel)
                    backup_data['channels'].append(channel_data)

            # Back up bot settings from Redis
            async with self.bot.redis.pipeline() as pipe:
                pipe.hgetall('channel_ids')
                pipe.hgetall('bot_settings')
                channel_ids, bot_settings = await pipe.execute()
                
                backup_data['bot_settings'] = {
                    'channel_ids': {k.decode(): int(v) for k, v in channel_ids.items()},
                    'settings': {k.decode(): v.decode() for k, v in bot_settings.items()}
                }

            return backup_data

        except Exception as e:
            logger.error(f"Error creating backup: {e}")
            raise

    async def restore_backup(self, guild: discord.Guild, backup_data: Dict[str, Any]) -> List[str]:
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
            for channel_data in sorted(backup_data['channels'], key=lambda c: c['position']):
                try:
                    overwrites = {}
                    for key, data in channel_data['overwrites'].items():
                        target_type, target_id = key.split(':', 1)
                        if target_type == 'role':
                            target = discord.utils.get(guild.roles, name=target_id)
                        else:
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
                            
                            overwrites[target] = overwrite

                    # Create channel based on type
                    if channel_data['type'] == 'text':
                        channel = await guild.create_text_channel(
                            name=channel_data['name'],
                            topic=channel_data.get('topic'),
                            nsfw=channel_data.get('nsfw', False),
                            slowmode_delay=channel_data.get('slowmode_delay', 0),
                            position=channel_data['position'],
                            overwrites=overwrites
                        )
                        
                        # Restore pins
                        if 'pins' in channel_data:
                            for pin in channel_data['pins']:
                                message = await channel.send(
                                    f"📌 Restored Pin from {pin['author']}\n{pin['content']}"
                                )
                                await message.pin()
                                
                    elif channel_data['type'] == 'voice':
                        channel = await guild.create_voice_channel(
                            name=channel_data['name'],
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

    @app_commands.command(name="draxon-backup", description="Create a backup of the server configuration")
    @app_commands.checks.has_role("Chairman")
    async def backup(self, interaction: discord.Interaction):
        """Create a backup of the server"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            backup_data = await self.create_backup(interaction.guild)
            
            # Store backup in Redis with timestamp
            timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            await self.bot.redis.set(
                f'backup:{timestamp}',
                json.dumps(backup_data),
                ex=86400  # Expire after 24 hours
            )
            
            # Create backup file
            backup_json = json.dumps(backup_data, indent=2)
            file = discord.File(
                io.StringIO(backup_json),
                filename=f'draxon_backup_{timestamp}.json'
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

    @app_commands.command(name="draxon-restore", description="Restore server configuration from a backup file")
    @app_commands.checks.has_role("Chairman")
    async def restore(self, interaction: discord.Interaction, backup_file: discord.Attachment):
        """Restore from a backup file"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            if not backup_file.filename.endswith('.json'):
                await interaction.followup.send("❌ Please provide a valid JSON backup file.", ephemeral=True)
                return
                
            backup_content = await backup_file.read()
            backup_data = json.loads(backup_content.decode('utf-8'))
            
            await interaction.followup.send(
                "⚠️ **Warning**: This will delete all current channels and roles before restoring from backup.\n"
                "Are you sure you want to proceed? Reply with `yes` to continue.",
                ephemeral=True
            )
            
            def check(m):
                return m.author == interaction.user and m.channel == interaction.channel
            
            try:
                msg = await self.bot.wait_for('message', timeout=30.0, check=check)
                
                if msg.content.lower() != 'yes':
                    await interaction.followup.send("❌ Restore cancelled.", ephemeral=True)
                    return
                
                # Send initial status message
                status_message = await interaction.followup.send(
                    "🔄 Starting restore process...",
                    ephemeral=True
                )
                
                # Perform restore
                logs = await self.restore_backup(interaction.guild, backup_data)
                
                # Send logs in chunks
                log_chunks = [logs[i:i + 10] for i in range(0, len(logs), 10)]
                for index, chunk in enumerate(log_chunks, 1):
                    await interaction.followup.send(
                        f"**Restore Progress ({index}/{len(log_chunks)}):**\n" + 
                        '\n'.join(chunk),
                        ephemeral=True
                    )
                
                await interaction.followup.send(
                    "✅ Restore process completed! Please verify all channels and roles.",
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