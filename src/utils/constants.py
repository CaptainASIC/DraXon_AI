# Version info
APP_VERSION = "2.0.5"
BUILD_DATE = "Nov 2024"

# Role Configuration
ROLE_HIERARCHY = [
    'Screening',
    'Applicant',
    'Employee',
    'Team Leader',
    'Executive',
    'Chairman',
    'Magnate'
]

DraXon_ROLES = {
    'leadership': ['Magnate', 'Chairman'],
    'management': ['Executive', 'Team Leader'],
    'staff': ['Employee'],
    'restricted': ['Applicant', 'Screening']
}

# Role Management Settings
ROLE_SETTINGS = {
    'LEADERSHIP_MAX_RANK': "Team Leader",    # Maximum rank for affiliates
    'DEFAULT_DEMOTION_RANK': "Employee",     # Rank to demote affiliates to
    'UNAFFILIATED_RANK': "Screening",        # Rank for members not in org
    'MAX_PROMOTION_OPTIONS': 2,              # Maximum number of ranks to show for promotion
    'PROMOTION_TIMEOUT': 180                 # Seconds before promotion view times out
}

# Import these at top level for backwards compatibility
LEADERSHIP_MAX_RANK = ROLE_SETTINGS['LEADERSHIP_MAX_RANK']
DEFAULT_DEMOTION_RANK = ROLE_SETTINGS['DEFAULT_DEMOTION_RANK']
UNAFFILIATED_RANK = ROLE_SETTINGS['UNAFFILIATED_RANK']
MAX_PROMOTION_OPTIONS = ROLE_SETTINGS['MAX_PROMOTION_OPTIONS']
PROMOTION_TIMEOUT = ROLE_SETTINGS['PROMOTION_TIMEOUT']

# Message Templates
SYSTEM_MESSAGES = {
    'MAINTENANCE': """
⚠️ **RSI API is Currently Unavailable**

The RSI API is experiencing downtime. This is a known issue that occurs daily 
from {start_time} UTC for approximately {duration} hours.

Please try again later when the API service has been restored.
""",
    
    'UNLINKED_REMINDER': """
👋 Hello! This is a friendly reminder to link your RSI account with our Discord server.

You can do this by using the `/draxon-link` command in any channel.

Linking your account helps us maintain proper organization structure and ensures 
you have access to all appropriate channels and features.
""",
    
    'DEMOTION_REASONS': {
        'affiliate': "Affiliate status incompatible with leadership role",
        'not_in_org': "Not found in organization",
        'role_update': "Role updated due to organization status change"
    }
}

# Channel Configuration
CHANNELS_CONFIG = [
    {
        "name": "all-staff",
        "display": "👥 All Staff: {count}",
        "count_type": "members"
    },
    {
        "name": "automated-systems",
        "display": "🤖 Automated Systems: {count}",
        "count_type": "bots"
    },
    {
        "name": "platform-status",
        "display": "{emoji} RSI Platform",
        "count_type": "status"
    },
    {
        "name": "persistent-universe-status",
        "display": "{emoji} Star Citizen (PU)",
        "count_type": "status"
    },
    {
        "name": "electronic-access-status",
        "display": "{emoji} Arena Commander",
        "count_type": "status"
    }
]

# Channel Settings
CHANNEL_SETTINGS = {
    'CATEGORY_NAME': 'DraXon OCULUS',  # Name of the category for bot channels
    'REFRESH_INTERVAL': 300,       # Channel refresh interval in seconds (5 minutes)
    'MAX_RETRIES': 3,             # Maximum retries for channel operations
    'RETRY_DELAY': 5,             # Delay between retries in seconds
    'VOICE_BITRATE': 64000,       # Default bitrate for voice channels
    'USER_LIMIT': 0,              # Default user limit (0 = unlimited)
    'POSITION_START': 1,          # Starting position for channels in category
    'POSITION_INCREMENT': 1,      # Position increment for each channel
    'SYNC_PERMISSIONS': True,     # Whether to sync permissions with category
    'CLEANUP_OLD_CHANNELS': True  # Whether to clean up old/duplicate channels
}

# Status Configuration
STATUS_EMOJIS = {
    'operational': '✅',
    'degraded': '⚠️',
    'partial': '⚠️',
    'major': '❌',
    'maintenance': '🔧',
    'unknown': '❓'
}


COMPARE_STATUS = {
    'match': '✅',      # Member found in both Discord and RSI
    'mismatch': '❌',   # Different data between Discord and RSI
    'missing': '⚠️'     # Missing from either Discord or RSI
}

# RSI API Configuration
RSI_API = {
    'BASE_URL': "https://api.starcitizen-api.com",
    'VERSION': "v1",
    'MODE': "live",
    'ORGANIZATION_SID': "DRAXON",
    'MEMBERS_PER_PAGE': 32,
    'STATUS_URL': "https://status.robertsspaceindustries.com/",
    'FEED_URL': "https://status.robertsspaceindustries.com/index.xml",
    'MAINTENANCE_START': "22:00",  # UTC
    'MAINTENANCE_DURATION': 3      # Hours
}

# Cache Settings
CACHE_SETTINGS = {
    'STATUS_TTL': 300,            # 5 minutes
    'API_TTL': 3600,              # 1 hour
    'MEMBER_DATA_TTL': 3600,      # 1 hour
    'ORG_DATA_TTL': 7200,         # 2 hours
    'VERIFICATION_TTL': 86400     # 24 hours
}

# Database Settings
DB_SETTINGS = {
    'POOL_SIZE': 20,
    'MAX_OVERFLOW': 10,
    'POOL_TIMEOUT': 30,
    'POOL_RECYCLE': 1800,
    'ECHO': False
}

# Channel Permissions
CHANNEL_PERMISSIONS = {
    'display_only': {
        'everyone': {
            'view_channel': True,
            'connect': False,
            'speak': False,
            'send_messages': False,
            'stream': False,
            'use_voice_activation': False
        },
        'bot': {
            'view_channel': True,
            'manage_channels': True,
            'manage_permissions': True,
            'connect': True,
            'manage_roles': True,
            'manage_messages': True,
            'attach_files': True,
            'send_messages_in_threads': True
        }
    }
}

# Bot Configuration
BOT_REQUIRED_PERMISSIONS = [
    'view_channel',
    'manage_channels',
    'manage_roles',
    'send_messages',
    'read_message_history',
    'create_private_threads',
    'read_messages',
    'move_members',
    'manage_messages',
    'attach_files',
    'send_messages_in_threads'
]

# Path Configuration
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOG_DIR = BASE_DIR / "logs"
ENV_DIR = BASE_DIR / "env"
DB_DIR = BASE_DIR / "data"
