import asyncio
import logging
import certifi
import ssl
from typing import Optional, Tuple
import asyncpg
import redis.asyncio as redis
from pathlib import Path

from src.utils.logger import setup_logging
from src.bot.client import DraXonOCULUSBot
from src.config.settings import Settings
from src.db.database import init_db, init_redis
from src.utils.constants import LOG_DIR, APP_VERSION

# Initialize logging first
setup_logging()
logger = logging.getLogger('DraXon_OCULUS')

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

async def cleanup_services(bot: Optional[DraXonOCULUSBot] = None, 
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

async def verify_directories() -> None:
    """Ensure all required directories exist"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Required directories verified")
    except Exception as e:
        logger.error(f"Error creating directories: {e}")
        raise

async def verify_env(settings: Settings) -> None:
    """Verify all required environment variables are set"""
    try:
        required_settings = [
            'discord_token',
            'postgres_user',
            'postgres_password',
            'postgres_db',
            'rsi_api_key'
        ]
        
        missing = []
        for setting in required_settings:
            if not getattr(settings, setting, None):
                missing.append(setting)
                
        if missing:
            raise ValueError(f"Missing required settings: {', '.join(missing)}")
            
        logger.info("Environment validation successful")
    except Exception as e:
        logger.error(f"Environment validation failed: {e}")
        raise

async def main() -> None:
    """Main entry point for the DraXon OCULUS bot"""
    # Initialize variables
    settings: Optional[Settings] = None
    db_pool: Optional[asyncpg.Pool] = None
    redis_pool: Optional[redis.Redis] = None
    bot: Optional[DraXonOCULUSBot] = None
    
    try:
        logger.info(f"Starting DraXon OCULUS Bot v{APP_VERSION}")
        
        # Verify directories and environment
        await verify_directories()
        
        # Load and validate settings
        try:
            settings = Settings()
            await verify_env(settings)
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
        bot = DraXonOCULUSBot(
            db_pool=db_pool,
            redis_pool=redis_pool,
            ssl_context=ssl_context,
            settings=settings
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
