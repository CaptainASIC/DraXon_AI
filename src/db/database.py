import asyncio
import logging
from typing import Optional, Tuple
import asyncpg
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.utils.constants import DB_SETTINGS
from src.config.settings import get_settings
from .init_schema import init_database

logger = logging.getLogger('DraXon_AI')

async def init_db(database_url: str) -> asyncpg.Pool:
    """Initialize PostgreSQL connection pool and create tables"""
    try:
        # Create the connection pool
        pool = await asyncpg.create_pool(
            database_url,
            min_size=DB_SETTINGS['POOL_SIZE'],
            max_size=DB_SETTINGS['POOL_SIZE'] + DB_SETTINGS['MAX_OVERFLOW'],
            command_timeout=DB_SETTINGS['POOL_TIMEOUT'],
            statement_cache_size=0,  # Disable statement cache for better memory usage
        )
        
        if not pool:
            raise Exception("Failed to create database pool")
        
        # Test the connection
        async with pool.acquire() as conn:
            await conn.execute('SELECT 1')
            
            # Create tables if they don't exist
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS rsi_members (
                    discord_id TEXT PRIMARY KEY,
                    handle TEXT,
                    sid TEXT,
                    display_name TEXT,
                    enlisted TEXT,
                    org_status TEXT,
                    org_rank TEXT,
                    org_stars INTEGER,
                    verified BOOLEAN DEFAULT FALSE,
                    last_updated TIMESTAMP WITH TIME ZONE,
                    raw_data JSONB
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS verification_history (
                    id SERIAL PRIMARY KEY,
                    discord_id TEXT,
                    action TEXT,
                    status BOOLEAN,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    details JSONB
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS role_history (
                    id SERIAL PRIMARY KEY,
                    discord_id TEXT,
                    old_rank TEXT,
                    new_rank TEXT,
                    reason TEXT,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS incident_history (
                    id SERIAL PRIMARY KEY,
                    guid TEXT UNIQUE,
                    title TEXT,
                    description TEXT,
                    status TEXT,
                    components TEXT[],
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    raw_data JSONB
                )
            ''')
            
            logger.info("Database tables created/verified successfully")
        
        logger.info("Database pool initialized successfully")
        return pool
        
    except Exception as e:
        logger.error(f"Error initializing database pool: {e}")
        raise

async def init_redis(redis_url: str) -> redis.Redis:
    """Initialize Redis connection"""
    try:
        # Create Redis connection
        redis_client = redis.Redis.from_url(
            redis_url,
            decode_responses=True,  # Automatically decode responses to strings
            socket_timeout=5,
            socket_connect_timeout=5
        )
        
        # Test the connection
        await redis_client.ping()
        
        logger.info("Redis connection initialized successfully")
        return redis_client
        
    except Exception as e:
        logger.error(f"Error initializing Redis connection: {e}")
        raise

def create_sqlalchemy_engine(database_url: str):
    """Create SQLAlchemy async engine"""
    return create_async_engine(
        database_url,
        echo=DB_SETTINGS['ECHO'],
        pool_size=DB_SETTINGS['POOL_SIZE'],
        max_overflow=DB_SETTINGS['MAX_OVERFLOW'],
        pool_timeout=DB_SETTINGS['POOL_TIMEOUT'],
        pool_recycle=DB_SETTINGS['POOL_RECYCLE']
    )
