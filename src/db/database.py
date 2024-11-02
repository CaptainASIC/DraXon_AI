import asyncio
import logging
from typing import Optional, Tuple
import asyncpg
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from src.utils.constants import DB_SETTINGS
from src.config.settings import get_settings

logger = logging.getLogger('DraXon_AI')

async def init_db() -> asyncpg.Pool:
    """Initialize PostgreSQL connection pool"""
    settings = get_settings()
    
    try:
        # Create the connection pool
        pool = await asyncpg.create_pool(
            user=settings.postgres_user,
            password=settings.postgres_password,
            database=settings.postgres_db,
            host=settings.postgres_host,
            port=settings.postgres_port,
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
        
        logger.info("Database pool initialized successfully")
        return pool
        
    except Exception as e:
        logger.error(f"Error initializing database pool: {e}")
        raise

async def init_redis() -> redis.Redis:
    """Initialize Redis connection"""
    settings = get_settings()
    
    try:
        # Create Redis connection
        redis_client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            db=settings.redis_db,
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

def create_sqlalchemy_engine():
    """Create SQLAlchemy async engine"""
    settings = get_settings()
    
    return create_async_engine(
        settings.database_url,
        echo=DB_SETTINGS['ECHO'],
        pool_size=DB_SETTINGS['POOL_SIZE'],
        max_overflow=DB_SETTINGS['MAX_OVERFLOW'],
        pool_timeout=DB_SETTINGS['POOL_TIMEOUT'],
        pool_recycle=DB_SETTINGS['POOL_RECYCLE']
    )

async def get_db_session() -> AsyncSession:
    """Get SQLAlchemy async session"""
    engine = create_sqlalchemy_engine()
    async_session = sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    
    async with async_session() as session:
        yield session

async def import_sqlite_data(sqlite_path: str, pool: asyncpg.Pool):
    """Import data from existing SQLite database"""
    import sqlite3
    import json
    from datetime import datetime
    
    logger.info(f"Starting import from SQLite database: {sqlite_path}")
    
    try:
        # Connect to SQLite database
        sqlite_conn = sqlite3.connect(sqlite_path)
        sqlite_conn.row_factory = sqlite3.Row
        
        # Get SQLite data
        sqlite_cur = sqlite_conn.cursor()
        
        # Import RSI members
        sqlite_cur.execute('SELECT * FROM rsi_members')
        members = sqlite_cur.fetchall()
        
        async with pool.acquire() as conn:
            # Create a transaction
            async with conn.transaction():
                # Import members
                for member in members:
                    await conn.execute('''
                        INSERT INTO rsi_members (
                            discord_id, handle, sid, display_name, enlisted,
                            org_status, org_rank, org_stars, verified,
                            last_updated, raw_data
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                        ON CONFLICT (discord_id) DO UPDATE SET
                            handle = EXCLUDED.handle,
                            sid = EXCLUDED.sid,
                            display_name = EXCLUDED.display_name,
                            enlisted = EXCLUDED.enlisted,
                            org_status = EXCLUDED.org_status,
                            org_rank = EXCLUDED.org_rank,
                            org_stars = EXCLUDED.org_stars,
                            verified = EXCLUDED.verified,
                            last_updated = EXCLUDED.last_updated,
                            raw_data = EXCLUDED.raw_data
                    ''', 
                    member['discord_id'],
                    member['handle'],
                    member['sid'],
                    member['display_name'],
                    member['enlisted'],
                    member['org_status'],
                    member['org_rank'],
                    member['org_stars'],
                    member['verified'],
                    member['last_updated'],
                    json.loads(member['raw_data']) if member['raw_data'] else None
                    )
                
                # Import role history
                sqlite_cur.execute('SELECT * FROM role_history')
                role_history = sqlite_cur.fetchall()
                
                for history in role_history:
                    await conn.execute('''
                        INSERT INTO role_history (
                            discord_id, old_rank, new_rank, reason, timestamp
                        ) VALUES ($1, $2, $3, $4, $5)
                    ''',
                    history['discord_id'],
                    history['old_rank'],
                    history['new_rank'],
                    history['reason'],
                    history['timestamp']
                    )
                
                # Import verification history
                sqlite_cur.execute('SELECT * FROM verification_history')
                verify_history = sqlite_cur.fetchall()
                
                for history in verify_history:
                    await conn.execute('''
                        INSERT INTO verification_history (
                            discord_id, action, status, timestamp, details
                        ) VALUES ($1, $2, $3, $4, $5)
                    ''',
                    history['discord_id'],
                    history['action'],
                    history['status'],
                    history['timestamp'],
                    json.loads(history['details']) if history['details'] else None
                    )
        
        logger.info("Data import completed successfully")
        
    except Exception as e:
        logger.error(f"Error importing data: {e}")
        raise
    finally:
        sqlite_conn.close()