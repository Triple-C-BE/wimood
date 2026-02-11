import logging
import os


def init_logging_config(env_config: dict):
    """
    Initializes the logging module's global configuration from the ENV dict.
    Configures the root logger so all module loggers (shopify_api, shopify_sync,
    wimood_scraper, etc.) automatically write to main.log and stdout.
    """
    global LOG_TO_STDOUT, LOG_DIR, SCRAPER_LOG_DIR, GLOBAL_LOG_LEVEL

    LOG_TO_STDOUT = env_config.get("LOG_TO_STDOUT", "true")
    LOG_DIR = env_config.get("LOG_DIR", "logs")
    SCRAPER_LOG_DIR = os.path.join(LOG_DIR, "scrapers")
    GLOBAL_LOG_LEVEL = env_config.get("LOG_LEVEL", "INFO").upper()

    # Create required directories
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(SCRAPER_LOG_DIR, exist_ok=True)

    # Configure root logger so ALL loggers inherit handlers
    root_logger = logging.getLogger()
    resolved_level = resolve_log_level(GLOBAL_LOG_LEVEL)
    root_logger.setLevel(resolved_level)

    # Suppress noisy urllib3 retry warnings — retries are handled by RequestManager
    logging.getLogger("urllib3").setLevel(logging.ERROR)

    # Avoid duplicate handlers on re-init
    if not root_logger.hasHandlers():
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        # File handler — all logs go to main.log
        file_handler = logging.FileHandler(
            os.path.join(LOG_DIR, "main.log"), encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        # Stdout handler
        if LOG_TO_STDOUT:
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            root_logger.addHandler(stream_handler)


def resolve_log_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        return getattr(logging, level.upper(), logging.INFO)
    return logging.INFO


def get_logger(name: str, filename: str = None, level: int | str = None) -> logging.Logger:
    """Get a named logger. Optionally add a dedicated file handler."""
    logger = logging.getLogger(name)

    if level:
        logger.setLevel(resolve_log_level(level))

    # Add a dedicated file handler if requested (on top of root handlers)
    if filename and not any(
        isinstance(h, logging.FileHandler) and h.baseFilename == os.path.abspath(filename)
        for h in logger.handlers
    ):
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler = logging.FileHandler(filename, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_main_logger() -> logging.Logger:
    return logging.getLogger("main")
