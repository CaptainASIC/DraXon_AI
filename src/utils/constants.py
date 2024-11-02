from pathlib import Path
from typing import Dict, List

# Version Information
APP_VERSION = "2.0.0"
BUILD_DATE = "2024-03"
API_VERSION = "v1"

# Project Structure
BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOG_DIR = BASE_DIR / "logs"
ENV_DIR = BASE_DIR / "env"
MIGRATIONS_DIR = BASE_DIR / "migrations"

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

# Request Configuration
REQUEST_HEADERS = {
    'User-Agent': f'DraXon_AI_Bot/{APP_VERSION}'
}
MAX_RETRIES = 3
REQUEST_TIMEOUT = 10  # seconds

# Role Configuration
ROLE_HIERARCHY: List[str] = [
    'Screening',
    'Applicant',
    'Employee',
    'Team Leader',
    'Manager',
    'Director',
    'Chairman'
]

DraXon_ROLES: Dict[str, List[str]] = {
    'leadership': ['Chairman', 'Director'],
    'management': ['Manager', 'Team Leader'],
    'staff': ['Employee'],
    'restricted': ['Applicant', 'Screening']
}

ROLE_SETTINGS = {
    'LEADERSHIP_MAX_RANK': "Team Leader",    # Maximum rank for affiliates
    'DEFAULT_DEMOTION_RANK': "Employee",     # Rank to demote affiliates to
    'UNAFFILIATED_RANK': "Screening",        # Rank for members not in org
    'MAX_PROMOTION_OPTIONS': 2,              # Maximum number of ranks to show for promotion
    'PROMOTION_TIMEOUT': 180                 # Seconds before promotion view times out
}

# Channel Configuration
CHANNEL_SETTINGS = {
    'CATEGORY_NAME': "🖥️ DraXon AI 🖥️",
    'REFRESH_INTERVAL': 300,  # 5 minutes in seconds
    'STATUS_CHECK_INTERVAL': 1800  # 30 minutes in seconds
}

CHANNELS_CONFIG: List[Dict] = [
    {
        "name": "all-staff",
        "display": "👥 All Staff: {count}",
        "count_type": "members",
        "description": "Shows total member count"
    },
    {
        "name": "automated-systems",
        "display": "🤖 Automated Systems: {count}",
        "count_type": "bots",
        "description": "Shows bot count"
    },
    {
        "name": "platform-status",
        "display": "{emoji} RSI Platform",
        "count_type": "status",
        "description": "RSI platform status"
    },
    {
        "name": "persistent-universe-status",
        "display": "{emoji} Star Citizen (PU)",
        "count_type": "status",
        "description": "PU status"
    },
    {
        "name": "electronic-access-status",
        "display": "{emoji} Arena Commander",
        "count_type": "status",
        "description": "EA status"
    }
]

# Permission Configuration
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

# Status Configuration
STATUS_EMOJIS: Dict[str, str] = {
    'operational': '✅',
    'degraded': '⚠️',
    'partial': '⚠️',
    'major': '❌',
    'maintenance': '🔧'
}

COMPARE_STATUS: Dict[str, str] = {
    'match': '✅',      # Member found in both Discord and RSI
    'mismatch': '❌',   # Different data between Discord and RSI
    'missing': '⚠️'     # Missing from either Discord or RSI
}

# RSI API Configuration
RSI_API = {
    'BASE_URL': "https://api.starcitizen-api.com",
    'VERSION': API_VERSION,
    'MODE': "live",
    'ORGANIZATION_SID': "DRAXON",
    'MEMBERS_PER_PAGE': 32,
    'STATUS_URL': "https://status.robertsspaceindustries.com/",
    'FEED_URL': "https://status.robertsspaceindustries.com/index.xml",
    'MAINTENANCE_START': "22:00",  # UTC
    'MAINTENANCE_DURATION': 3      # Hours
}

# Cache Configuration
CACHE_SETTINGS = {
    'STATUS_TTL': 300,            # 5 minutes
    'MEMBER_DATA_TTL': 3600,      # 1 hour
    'ORG_DATA_TTL': 7200,         # 2 hours
    'VERIFICATION_TTL': 86400     # 24 hours
}

# Database Configuration
DB_SETTINGS = {
    'POOL_SIZE': 20,
    'MAX_OVERFLOW': 10,
    'POOL_TIMEOUT': 30,
    'POOL_RECYCLE': 1800,
    'ECHO': False
}

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

# Logging Configuration
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        },
        'detailed': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s'
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
            'level': 'INFO'
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'DraXon_ai.log',
            'formatter': 'detailed',
            'level': 'DEBUG',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 5
        }
    },
    'loggers': {
        'DraXon_AI': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False
        }
    }
}