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
from src.utils.constants import LOG_DIR, APP_VERSION

# Initialize logging first
setup_logging()
logger = logging.getLogger('DraXon_AI')

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
            await redis_pool.aclose()  # Changed from close() to aclose()
            
        logger.info("All services cleaned up successfully")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

async def main() -> None:
    """Main entry point for the DraXon AI bot"""
    # Initialize logging
    settings: Optional[Settings] = None
    db_pool: Optional[asyncpg.Pool] = None
    redis_pool: Optional[redis.Redis] = None
    bot: Optional[DraXonAIBot] = None
    
    try:
        logger.info(f"Starting DraXon AI Bot v{APP_VERSION}")
        
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
        # Create required directories
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        
        # Start the bot
        asyncio.run(main())
        
    except KeyboardInterrupt:
        logger.info("Bot shutdown initiated by user")
        
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        raise
    
    finally:
        logger.info("Bot shutdown complete")