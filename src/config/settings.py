from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import urllib.parse
from pathlib import Path
import logging

logger = logging.getLogger('DraXon_AI')

class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Environment Configuration
    environment: str = "development"
    debug: bool = False
    app_version: str = "2.0.0"
    
    # Discord Configuration
    discord_token: str
    command_prefix: str = "!"
    
    # PostgreSQL Configuration
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    
    # Redis Configuration
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: Optional[str] = None
    redis_db: int = 0
    
    # RSI API Configuration
    rsi_api_key: str
    rsi_organization_sid: str = "DRAXON"
    rsi_api_base_url: str = "https://api.starcitizen-api.com"
    api_version: str = "v1"
    api_mode: str = "live"
    
    # Rate Limiting
    rate_limit_commands: int = 5  # commands per minute
    rate_limit_api: int = 60      # API calls per minute
    
    # Cache Settings
    cache_ttl: int = 300          # 5 minutes
    org_cache_ttl: int = 3600     # 1 hour
    member_cache_ttl: int = 7200  # 2 hours
    
    # Maintenance Window (UTC)
    maintenance_start: str = "22:00"
    maintenance_duration: int = 3
    
    # Database Pool Settings
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800
    
    # Path Configuration
    base_dir: Path = Path(__file__).resolve().parent.parent.parent
    log_dir: Path = base_dir / "logs"
    data_dir: Path = base_dir / "data"
    
    # Security Settings
    ssl_verify: bool = True
    api_timeout: int = 30
    
    # Docker Settings
    docker_restart_policy: str = "unless-stopped"
    docker_memory_limit: str = "512m"
    docker_cpu_limit: float = 0.5
    
    @property
    def database_url(self) -> str:
        """Get PostgreSQL URL formatted for asyncpg"""
        try:
            # URL encode the password to handle special characters
            encoded_password = urllib.parse.quote_plus(self.postgres_password)
            return (
                f"postgresql://{self.postgres_user}:{encoded_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        except Exception as e:
            logger.error(f"Error creating database URL: {e}")
            raise

    @property
    def sqlalchemy_url(self) -> str:
        """Get PostgreSQL URL formatted for SQLAlchemy"""
        try:
            # URL encode the password to handle special characters
            encoded_password = urllib.parse.quote_plus(self.postgres_password)
            return (
                f"postgresql+asyncpg://{self.postgres_user}:{encoded_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        except Exception as e:
            logger.error(f"Error creating SQLAlchemy URL: {e}")
            raise

    @property
    def redis_url(self) -> str:
        """Get Redis URL"""
        try:
            if self.redis_password:
                encoded_password = urllib.parse.quote_plus(self.redis_password)
                auth = f":{encoded_password}@"
            else:
                auth = "@"
            return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"
        except Exception as e:
            logger.error(f"Error creating Redis URL: {e}")
            raise

    @property
    def rsi_api_url(self) -> str:
        """Get RSI API URL"""
        return f"{self.rsi_api_base_url}/{self.api_version}/{self.api_mode}"
    
    @property
    def is_production(self) -> bool:
        """Check if running in production environment"""
        return self.environment.lower() == "production"

    @property
    def logging_config(self) -> dict:
        """Get logging configuration"""
        return {
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
                    'filename': str(self.log_dir / 'draxon_ai.log'),
                    'formatter': 'detailed',
                    'level': 'DEBUG',
                    'maxBytes': 10485760,  # 10MB
                    'backupCount': 5
                }
            },
            'loggers': {
                'DraXon_AI': {
                    'handlers': ['console', 'file'],
                    'level': 'DEBUG' if self.debug else 'INFO',
                    'propagate': False
                }
            }
        }

    def ensure_directories(self) -> None:
        """Ensure required directories exist"""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self.data_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Required directories created successfully")
        except Exception as e:
            logger.error(f"Error creating directories: {e}")
            raise

    def validate_settings(self) -> None:
        """Validate critical settings"""
        try:
            # Check token length
            if len(self.discord_token) < 50:
                raise ValueError("Invalid Discord token length")
            
            # Check port ranges
            if not (1 <= self.postgres_port <= 65535):
                raise ValueError("Invalid PostgreSQL port number")
            if not (1 <= self.redis_port <= 65535):
                raise ValueError("Invalid Redis port number")
            
            # Check maintenance time format
            try:
                hour, minute = self.maintenance_start.split(":")
                if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
                    raise ValueError
            except:
                raise ValueError("Invalid maintenance time format")
            
            # Check positive values
            if self.maintenance_duration <= 0:
                raise ValueError("Maintenance duration must be positive")
            if self.cache_ttl <= 0:
                raise ValueError("Cache TTL must be positive")
            
            logger.info("Settings validated successfully")
            
        except Exception as e:
            logger.error(f"Settings validation error: {e}")
            raise ValueError(f"Invalid settings: {str(e)}")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        validate_assignment=True
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ensure_directories()
        self.validate_settings()
        logger.info(f"Settings initialized for environment: {self.environment}")

# Optional: Create a settings instance for use throughout the application
def get_settings() -> Settings:
    """Get validated settings instance"""
    try:
        settings = Settings()
        return settings
    except Exception as e:
        logger.critical(f"Failed to load settings: {e}")
        raise