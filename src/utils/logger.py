import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional
import colorlog

from src.utils.constants import (
    LOG_DIR
)

def setup_logging(level: Optional[str] = None) -> None:
    """
    Set up logging configuration for the application
    
    Args:
        level: Optional override for log level
    """
    # Create logs directory if it doesn't exist
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Create color formatter for console output
    console_formatter = colorlog.ColoredFormatter(
        '%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_white',
        }
    )

    # Create file formatter
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s'
    )

    # Create console handler with color formatting
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(level or logging.INFO)

    # Create rotating file handler
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / 'draxon_ai.log',
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)

    # Create error file handler
    error_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / 'error.log',
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    error_handler.setFormatter(file_formatter)
    error_handler.setLevel(logging.ERROR)

    # Get the root logger and set its level
    root_logger = logging.getLogger()
    root_logger.setLevel(level or logging.INFO)

    # Remove any existing handlers
    root_logger.handlers.clear()

    # Add the handlers
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)

    # Create logger for our application
    logger = logging.getLogger('DraXon_AI')
    logger.setLevel(level or logging.INFO)

    # Log startup message
    logger.info("Logging system initialized")

    # Log any uncaught exceptions
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            # Don't log keyboard interrupt
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logger.critical("Uncaught exception", 
                       exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception

def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the given name
    
    Args:
        name: Name for the logger
        
    Returns:
        Logger instance
    """
    return logging.getLogger(f'DraXon_AI.{name}')

# Optional: Add custom log levels if needed
def add_custom_log_levels():
    """Add custom log levels to the logging module"""
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