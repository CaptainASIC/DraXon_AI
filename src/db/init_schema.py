import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import asyncio
import logging
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateTable
from .models import Base, RSIMember, RoleHistory, VerificationHistory, IncidentHistory
from src.config.settings import get_settings

logger = logging.getLogger('DraXon_AI')

async def init_database():
    """Initialize database schema"""
    settings = get_settings()
    
    try:
        # Create async engine
        engine = create_async_engine(
            settings.database_url,
            echo=True  # Set to False in production
        )
        
        async with engine.begin() as conn:
            logger.info("Creating database tables...")
            # Drop all tables if they exist
            await conn.run_sync(Base.metadata.drop_all)
            
            # Create all tables
            await conn.run_sync(Base.metadata.create_all)
            
            # Log table creation
            for table in Base.metadata.sorted_tables:
                logger.info(f"Created table: {table.name}")
                
        logger.info("Database initialization completed successfully")
        
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise
    finally:
        await engine.dispose()

def create_init_script(engine):
    """Create SQL initialization script for manual execution"""
    tables = []
    for table in Base.metadata.sorted_tables:
        tables.append(str(CreateTable(table).compile(dialect=engine.dialect)))
    
    with open('init_schema.sql', 'w') as f:
        f.write('\n\n'.join(tables))
    
    logger.info("SQL initialization script created: init_schema.sql")

if __name__ == "__main__":
    asyncio.run(init_database())
