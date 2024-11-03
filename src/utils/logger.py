import logging
import logging.handlers
import sys
import os
from pathlib import Path
from typing import Optional, Dict, Any
import json
from datetime import datetime
import colorlog

from src.utils.constants import LOG_DIR

class CustomFormatter(colorlog.ColoredFormatter):
    """Custom formatter with color support and extra fields"""
    
    def __init__(self):
        super().__init__(
            fmt='%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            reset=True,
            log_colors={
                'DEBUG':    'cyan',
                'INFO':     'green',
                'WARNING': 'yellow',
                'ERROR':    'red',
                'CRITICAL': 'red,bg_white',
            },
            secondary_log_colors={},
            style='%'
        )

    def formatException(self, ei) -> str:
        """Enhanced exception formatting"""
        result = super().formatException(ei)
        return f"\n{result}"

    def format(self, record: logging.LogRecord) -> str:
        """Enhanced record formatting with extra fields"""
        # Add timestamp if not present
        if not hasattr(record, 'asctime'):
            record.asctime = self.formatTime(record, self.datefmt)

        # Add extra contextual information if available
        if hasattr(record, 'extra'):
            for key, value in record.extra.items():
                setattr(record, key, value)

        return super().format(record)

class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging"""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format the record as JSON"""
        log_data = {
            'timestamp': self.formatTime(record, self.datefmt),
            'name': record.name,
            'level': record.levelname,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }

        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        # Add extra fields if present
        if hasattr(record, 'extra'):
            log_data['extra'] = record.extra

        return json.dumps(log_data)

def create_rotating_file_handler(filename: str, 
                               max_bytes: int = 10485760,  # 10MB 
                               backup_count: int = 5,
                               formatter: logging.Formatter = None) -> logging.Handler:
    """Create a rotating file handler with the specified configuration"""
    handler = logging.handlers.RotatingFileHandler(
        filename=filename,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    
    if formatter:
        handler.setFormatter(formatter)
        
    return handler

def setup_logging(level: Optional[str] = None,
                 json_logging: bool = False,
                 log_dir: Optional[Path] = None) -> None:
    """
    Set up logging configuration for the application
    
    Args:
        level: Optional override for log level
        json_logging: Whether to use JSON formatting for file logs
        log_dir: Optional override for log directory
    """
    # Use provided log dir or default
    log_directory = log_dir or LOG_DIR
    
    # Create logs directory if it doesn't exist
    log_directory.mkdir(parents=True, exist_ok=True)

    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level or logging.INFO)

    # Remove any existing handlers
    root_logger.handlers.clear()

    # Console handler with color formatting
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(CustomFormatter())
    console_handler.setLevel(level or logging.INFO)
    root_logger.addHandler(console_handler)

    # Main log file handler
    main_formatter = JSONFormatter() if json_logging else logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s'
    )
    
    main_handler = create_rotating_file_handler(
        filename=log_directory / 'draxon_ai.log',
        formatter=main_formatter
    )
    main_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(main_handler)

    # Error log file handler
    error_handler = create_rotating_file_handler(
        filename=log_directory / 'error.log',
        formatter=main_formatter
    )
    error_handler.setLevel(logging.ERROR)
    root_logger.addHandler(error_handler)

    # Create app logger
    logger = logging.getLogger('DraXon_AI')
    logger.setLevel(level or logging.INFO)

    # Set up exception handling
    def handle_exception(exc_type, exc_value, exc_traceback):
        """Handle uncaught exceptions"""
        if issubclass(exc_type, KeyboardInterrupt):
            # Don't log keyboard interrupt
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logger.critical(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_traceback),
            extra={
                'time': datetime.utcnow().isoformat(),
                'type': exc_type.__name__
            }
        )

    sys.excepthook = handle_exception

    # Log startup
    logger.info(
        "Logging system initialized",
        extra={
            'log_dir': str(log_directory),
            'level': logging.getLevelName(logger.getEffectiveLevel()),
            'json_logging': json_logging
        }
    )

class LoggerAdapter(logging.LoggerAdapter):
    """Custom logger adapter for adding context to log messages"""
    
    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        """Add extra context to the log record"""
        extra = kwargs.get('extra', {})
        
        # Add timestamp if not present
        if 'timestamp' not in extra:
            extra['timestamp'] = datetime.utcnow().isoformat()
            
        # Add context from adapter
        extra.update(self.extra)
        
        kwargs['extra'] = extra
        return msg, kwargs

def get_logger(name: str, **kwargs) -> logging.Logger:
    """
    Get a logger with the given name and optional context
    
    Args:
        name: Logger name
        **kwargs: Additional context to add to all log messages
        
    Returns:
        Logger instance with context
    """
    logger = logging.getLogger(f'DraXon_AI.{name}')
    
    if kwargs:
        return LoggerAdapter(logger, kwargs)
    
    return logger

def log_to_file(msg: str, level: int = logging.INFO, 
                filename: str = 'custom.log') -> None:
    """
    Log a message to a specific file
    
    Args:
        msg: Message to log
        level: Log level
        filename: Target log file
    """
    handler = create_rotating_file_handler(
        filename=LOG_DIR / filename,
        formatter=logging.Formatter('%(asctime)s - %(message)s')
    )
    
    logger = get_logger('custom')
    logger.addHandler(handler)
    logger.log(level, msg)
    logger.removeHandler(handler)

# Optional: Add custom log levels
def add_custom_levels():
    """Add custom log levels"""
    # Add TRACE level
    TRACE_LEVEL_NUM = 5
    logging.addLevelName(TRACE_LEVEL_NUM, "TRACE")
    def trace(self, message, *args, **kwargs):
        if self.isEnabledFor(TRACE_LEVEL_NUM):
            self._log(TRACE_LEVEL_NUM, message, args, **kwargs)
    logging.Logger.trace = trace

    # Add SUCCESS level
    SUCCESS_LEVEL_NUM = 25
    logging.addLevelName(SUCCESS_LEVEL_NUM, "SUCCESS")
    def success(self, message, *args, **kwargs):
        if self.isEnabledFor(SUCCESS_LEVEL_NUM):
            self._log(SUCCESS_LEVEL_NUM, message, args, **kwargs)
    logging.Logger.success = success

# Additional utility functions
def add_file_handler(logger: logging.Logger, 
                    filename: str,
                    level: int = logging.INFO) -> None:
    """
    Add a file handler to an existing logger
    
    Args:
        logger: Logger to add handler to
        filename: Log file name
        level: Log level for the handler
    """
    handler = create_rotating_file_handler(
        filename=LOG_DIR / filename,
        formatter=logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    )
    handler.setLevel(level)
    logger.addHandler(handler)

def cleanup_old_logs(days: int = 30) -> None:
    """
    Delete log files older than specified days
    
    Args:
        days: Number of days to keep logs for
    """
    try:
        import time
        current_time = time.time()
        
        for log_file in LOG_DIR.glob('*.log*'):
            file_time = os.path.getmtime(log_file)
            if (current_time - file_time) // (24 * 3600) >= days:
                log_file.unlink()
                
    except Exception as e:
        logger = get_logger('cleanup')
        logger.error(f"Error cleaning up logs: {e}")

# Initialize custom log levels when module is imported
add_custom_levels()