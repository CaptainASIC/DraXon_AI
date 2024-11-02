import asyncio
import logging
import certifi
import ssl
from typing import Optional, Tuple
import asyncpg
import redis.asyncio as redis
from pathlib import Path

from src.utils.logger import setup_logging
from src.bot.client import DraXonAIBot
from src.config.settings import Settings
from src.db.database import init_db, init_redis
from src.utils.constants import LOG_DIR

# Version Information
APP_VERSION = "1.1.0"

# Initialize logging first
setup_logging()
logger = logging.getLogger('DraXon_AI')

def validate_cog_imports(cog_path: str) -> bool:
    """Validate required imports in a cog before loading"""
    try:
        required_imports = {
            'app_commands': 'from discord import app_commands',
            'commands': 'from discord.ext import commands',
            'tasks': 'from discord.ext import tasks',
            'logging': 'import logging',
            'typing': 'from typing import'
        }
        
        with open(cog_path, 'r') as f:
            content = f.read()
            
        missing_imports = []
        for import_name, import_statement in required_imports.items():
            if import_name not in content and import_statement not in content:
                missing_imports.append(import_statement)
                
        if missing_imports:
            logger.error(f"Missing required imports in {cog_path}:")
            for missing in missing_imports:
                logger.error(f"  - {missing}")
            return False
            
        return True
        
    except Exception as e:
        logger.error(f"Error validating cog {cog_path}: {e}")
        return False

async def check_required_dirs() -> None:
    """Ensure all required directories exist"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Required directories verified")
    except Exception as e:
        logger.error(f"Error creating directories: {e}")
        raise

async def initialize_services(settings: Settings) -> Tuple[asyncpg.Pool, redis.Redis]:
    """Initialize database and Redis connections"""
    try:
        # Initialize PostgreSQL connection
        logger.info("Initializing PostgreSQL connection...")
        db_pool = await init_db(settings.database_url)
        logger.info("PostgreSQL connection established")
        
        # Initialize Redis connection
        logger.info("Initializing Redis connection...")
        redis_pool = await init_redis(settings.redis_url)
        logger.info("Redis connection established")
        
        return db_pool, redis_pool
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        raise

async def cleanup_services(bot: Optional[DraXonAIBot] = None, 
                         db_pool: Optional[asyncpg.Pool] = None, 
                         redis_pool: Optional[redis.Redis] = None) -> None:
    """Cleanup function to properly close connections"""
    try:
        if bot:
            logger.info("Closing bot connection...")
            await bot.close()
        
        if db_pool:
            logger.info("Closing database pool...")
            await db_pool.close()
            
        if redis_pool:
            logger.info("Closing Redis connection...")
            await redis_pool.aclose()  # Using aclose() instead of close()
            
        logger.info("All services cleaned up successfully")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

async def main() -> None:
    """Main entry point for the DraXon AI bot"""
    # Initialize variables
    settings: Optional[Settings] = None
    db_pool: Optional[asyncpg.Pool] = None
    redis_pool: Optional[redis.Redis] = None
    bot: Optional[DraXonAIBot] = None
    
    try:
        logger.info(f"Starting DraXon AI Bot v{APP_VERSION}")
        
        # Check required directories
        await check_required_dirs()
        
        # Load and validate settings
        try:
            settings = Settings()
            logger.info("Settings loaded successfully")
        except Exception as e:
            logger.critical(f"Failed to load settings: {e}")
            raise
        
        # Initialize services
        try:
            db_pool, redis_pool = await initialize_services(settings)
        except Exception as e:
            logger.critical(f"Failed to initialize services: {e}")
            raise
        
        # Set up SSL context for secure connections
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        logger.info("SSL context created")
        
        # Initialize bot
        bot = DraXonAIBot(
            db_pool=db_pool,
            redis_pool=redis_pool,
            ssl_context=ssl_context,
            settings=settings  # Pass settings to bot for use in cogs
        )
        logger.info("Bot initialized")
        
        try:
            # Start the bot
            async with bot:
                logger.info("Starting bot...")
                await bot.start(settings.discord_token)
                
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, initiating shutdown...")
            
        except Exception as e:
            logger.error(f"Error running bot: {e}")
            raise
            
        finally:
            # Ensure proper cleanup
            logger.info("Starting cleanup process...")
            await cleanup_services(bot, db_pool, redis_pool)
            
    except Exception as e:
        logger.critical(f"Critical error in main: {e}")
        raise
        
    finally:
        # Extra safety cleanup in case of errors during initialization
        if any([bot, db_pool, redis_pool]):
            await cleanup_services(bot, db_pool, redis_pool)

if __name__ == "__main__":
    try:
        # Start the bot
        asyncio.run(main())
        
    except KeyboardInterrupt:
        logger.info("Bot shutdown initiated by user")
        
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        raise
    
    finally:
        logger.info("Bot shutdown complete")