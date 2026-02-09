import logging
import os

def init_logging_config(env_config: dict):
    """Initializes the logging module's global configuration from the ENV dict."""
    global LOG_TO_STDOUT, LOG_DIR, SCRAPER_LOG_DIR, GLOBAL_LOG_LEVEL

    # Read values from the ENV dictionary
    # NOTE: You must make sure LOG_TO_STDOUT and LOG_DIR are collected in env.py's load_env_variables()
    LOG_TO_STDOUT = env_config.get("LOG_TO_STDOUT", "true")

    LOG_DIR = env_config.get("LOG_DIR", "logs")
    SCRAPER_LOG_DIR = os.path.join(LOG_DIR, "scrapers")
    GLOBAL_LOG_LEVEL = env_config.get("LOG_LEVEL", "INFO").upper()

    # Create required directories only AFTER config is set
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(SCRAPER_LOG_DIR, exist_ok=True)

def get_logger(name: str, filename: str = None, level: int | str = None) -> logging.Logger:
    """Configure and return a logger."""
    logger = logging.getLogger(name)

    # Resolve the log level correctly
    resolved_level = resolve_log_level(level or GLOBAL_LOG_LEVEL)
    logger.setLevel(resolved_level)

    if logger.hasHandlers():
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 🔹 Only log to stdout if explicitly allowed
    if LOG_TO_STDOUT:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    if filename:
        file_handler = logging.FileHandler(filename, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger

def resolve_log_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        return getattr(logging, level.upper(), logging.INFO)
    return logging.INFO

def get_main_logger() -> logging.Logger:
    return get_logger("main", filename=os.path.join(LOG_DIR, "main.log"))