import asyncio
import logging
import certifi
import ssl
from pathlib import Path
from typing import Optional

from src.utils.logger import setup_logging
from src.bot.client import DraXonAIBot
from src.config.settings import Settings
from src.db.database import init_db, init_redis
from src.utils.constants import LOG_DIR, APP_VERSION

# Initialize logging first
setup_logging()
logger = logging.getLogger('DraXon_AI')

async def initialize_services(settings: Settings):
    """Initialize database and Redis connections"""
    try:
        # Initialize PostgreSQL connection
        db_pool = await init_db(
            user=settings.postgres_user,
            password=settings.postgres_password,
            database=settings.postgres_db,
            host=settings.postgres_host,
            port=settings.postgres_port
        )
        
        # Initialize Redis connection
        redis_pool = await init_redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            db=settings.redis_db
        )
        
        return db_pool, redis_pool
    except Exception as e:
        logging.error(f"Failed to initialize services: {e}")
        raise

async def cleanup_services(bot: Optional[DraXonAIBot] = None, 
                         db_pool = None, 
                         redis_pool = None):
    """Cleanup function to properly close connections"""
    try:
        if bot:
            await bot.close()
        if db_pool:
            await db_pool.close()
        if redis_pool:
            await redis_pool.close()
    except Exception as e:
        logging.error(f"Error during cleanup: {e}")

async def main():
    """Main entry point for the DraXon AI bot"""
    # Initialize logging
    setup_logging()
    logger = logging.getLogger('DraXon_AI')
    
    try:
        logger.info(f"Starting DraXon AI Bot v{APP_VERSION}")
        
        # Load settings
        settings = Settings()
        
        # Initialize services
        db_pool, redis_pool = await initialize_services(settings)
        
        # Set up SSL context for secure connections
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        
        # Initialize bot
        bot = DraXonAIBot(
            db_pool=db_pool,
            redis_pool=redis_pool,
            ssl_context=ssl_context
        )
        
        try:
            # Start the bot
            async with bot:
                logger.info("Starting bot...")
                await bot.start(settings.discord_token)
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, initiating shutdown...")
        except Exception as e:
            logger.error(f"Error running bot: {e}")
        finally:
            # Ensure proper cleanup
            await cleanup_services(bot, db_pool, redis_pool)
            
    except Exception as e:
        logger.critical(f"Critical error in main: {e}")
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot shutdown initiated by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        raise