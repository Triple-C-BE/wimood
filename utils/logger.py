import logging
import re
import sys


# ANSI color/style codes
class C:
    RST = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    ITALIC = '\033[3m'
    # Foreground
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    # Bright foreground
    BRED = '\033[91m'
    BGREEN = '\033[92m'
    BYELLOW = '\033[93m'
    BBLUE = '\033[94m'
    BMAGENTA = '\033[95m'
    BCYAN = '\033[96m'
    BWHITE = '\033[97m'
    # Background
    BG_RED = '\033[41m'
    BG_YELLOW = '\033[43m'


# Map logger names to (color, icon, short label)
LOGGER_STYLES = {
    'main':             (C.BOLD + C.BWHITE,   '\u25cf', 'main'),       # ●
    'shopify_api':      (C.BBLUE,              '\u25a0', 'shopify'),    # ■
    'shopify_sync':     (C.BCYAN,              '\u21c4', 'sync'),       # ⇄
    'wimood_api':       (C.BMAGENTA,           '\u25c6', 'wimood'),     # ◆
    'wimood_scraper':   (C.MAGENTA,            '\u2042', 'scraper'),    # ⁂
    'order_sync':       (C.BGREEN,             '\u25b6', 'orders'),     # ▶
    'order_store':      (C.GREEN,              '\u25c8', 'store'),      # ◈
    'request_manager':  (C.DIM,                '\u2192', 'http'),       # →
    'scrape_cache':     (C.DIM,                '\u25cb', 'cache'),      # ○
    'product_mapping':  (C.DIM,                '\u25cb', 'mapping'),    # ○
    'image_downloader': (C.DIM,                '\u25cb', 'images'),     # ○
    'utils.monitor':    (C.DIM,                '\u25cb', 'monitor'),    # ○
}

LEVEL_STYLES = {
    'DEBUG':    (C.DIM,                    '\u00b7'),     # ·
    'INFO':     (C.RST,                    '\u2502'),     # │
    'WARNING':  (C.BOLD + C.BYELLOW,       '\u26a0'),    # ⚠
    'ERROR':    (C.BOLD + C.BRED,          '\u2718'),     # ✘
    'CRITICAL': (C.BOLD + C.BG_RED + C.BWHITE, '\u2718'), # ✘ (with red bg)
}


class ConsoleFormatter(logging.Formatter):
    """Colored, icon-rich console formatter."""

    def format(self, record):
        ts = self.formatTime(record, '%H:%M:%S')

        level = record.levelname
        level_color, level_icon = LEVEL_STYLES.get(level, (C.RST, ' '))

        style = LOGGER_STYLES.get(record.name, (C.DIM, '\u25cb', record.name))
        label_color, label_icon, label = style

        msg = record.getMessage()

        # Color the entire message for warnings/errors, bold for "Next sync" status
        if level in ('WARNING', 'ERROR', 'CRITICAL'):
            msg_color = level_color
        elif msg.startswith('Next sync:'):
            msg_color = C.BOLD
        else:
            msg_color = C.RST

        return (
            f"{C.DIM}{ts}{C.RST} "
            f"{level_color}{level_icon}{C.RST} "
            f"{label_color}{label_icon} {label:<8}{C.RST} "
            f"{msg_color}{msg}{C.RST}"
        )


class PlainFormatter(logging.Formatter):
    """Plain formatter for non-TTY output (piped logs, Docker log drivers)."""

    PLAIN_ICONS = {
        'DEBUG': '.',
        'INFO': '|',
        'WARNING': '!',
        'ERROR': 'x',
        'CRITICAL': 'X',
    }

    def format(self, record):
        ts = self.formatTime(record, '%H:%M:%S')
        icon = self.PLAIN_ICONS.get(record.levelname, ' ')
        label = LOGGER_STYLES.get(record.name, (None, None, record.name))[2]
        return f"{ts} {icon} {label:<8} {record.getMessage()}"


def print_banner(env_config: dict):
    """Print a startup banner box with key configuration info."""
    test_mode = env_config.get('TEST_MODE', False)
    test_limit = env_config.get('TEST_PRODUCT_LIMIT', 5)
    sync_interval = env_config.get('PRODUCT_SYNC_INTERVAL_SECONDS', 3600)
    order_sync = env_config.get('ENABLE_ORDER_SYNC', False)
    order_interval = env_config.get('ORDER_SYNC_INTERVAL_SECONDS', 300)
    product_on_start = env_config.get('PRODUCT_SYNC_ON_START', True)
    order_on_start = env_config.get('ORDER_SYNC_ON_START', True)
    monitoring = env_config.get('ENABLE_MONITORING', False)
    monitor_port = env_config.get('MONITOR_PORT', 8080)
    store_url = env_config.get('SHOPIFY_STORE_URL', '?')
    log_level = env_config.get('LOG_LEVEL', 'INFO')

    is_tty = sys.stdout.isatty()

    if is_tty:
        dim = C.DIM
        rst = C.RST
        bold = C.BOLD
        cyan = C.BCYAN
        green = C.BGREEN
        yellow = C.BYELLOW
    else:
        dim = rst = bold = cyan = green = yellow = ''

    def yn(val):
        if val:
            return f"{green}ON{rst}"
        return f"{dim}OFF{rst}"

    def fmt_interval(secs):
        secs = int(secs)
        if secs >= 3600:
            h, r = divmod(secs, 3600)
            m = r // 60
            return f"{h}h{m}m" if m else f"{h}h"
        if secs >= 60:
            m, s = divmod(secs, 60)
            return f"{m}m{s}s" if s else f"{m}m"
        return f"{secs}s"

    lines = [
        f"{bold}{cyan}  Wimood → Shopify Sync Service{rst}",
        "",
        f"  {dim}Store{rst}      {bold}{store_url}{rst}",
        f"  {dim}Products{rst}   every {bold}{fmt_interval(sync_interval)}{rst}{'  ' + dim + '(start: immediate)' + rst if product_on_start else '  ' + yellow + '(start: deferred)' + rst}",
        f"  {dim}Orders{rst}     {yn(order_sync)}{f'  every {bold}{fmt_interval(order_interval)}{rst}' if order_sync else ''}{('  ' + dim + '(start: immediate)' + rst if order_on_start else '  ' + yellow + '(start: deferred)' + rst) if order_sync else ''}",
        f"  {dim}Monitor{rst}    {yn(monitoring)}{f'  port {bold}{monitor_port}{rst}' if monitoring else ''}",
        f"  {dim}Log level{rst}  {bold}{log_level}{rst}",
    ]

    if test_mode:
        lines.append(f"  {yellow}{bold}TEST MODE{rst}  {yellow}limit: {test_limit} products{rst}")

    # Calculate box width (strip ANSI for width calculation)
    ansi_re = re.compile(r'\033\[[0-9;]*m')
    max_w = max(len(ansi_re.sub('', line)) for line in lines)
    box_w = max_w + 2  # padding

    border_color = cyan if is_tty else ''
    top = f"{border_color}\u250c{'─' * box_w}\u2510{rst}"
    bot = f"{border_color}\u2514{'─' * box_w}\u2518{rst}"
    sep = f"{border_color}\u2502{rst}"

    print(f"\n{top}")
    for line in lines:
        visible_len = len(ansi_re.sub('', line))
        pad = box_w - visible_len
        print(f"{sep}{line}{' ' * pad}{sep}")
    print(f"{bot}\n")


def init_logging_config(env_config: dict):
    """Initialize logging — stdout only, with colors when running in a terminal."""
    log_level = env_config.get("LOG_LEVEL", "INFO").upper()

    root_logger = logging.getLogger()
    resolved_level = resolve_log_level(log_level)
    root_logger.setLevel(resolved_level)

    # Suppress noisy urllib3 retry warnings — retries are handled by RequestManager
    logging.getLogger("urllib3").setLevel(logging.ERROR)

    # Avoid duplicate handlers on re-init
    if not root_logger.hasHandlers():
        handler = logging.StreamHandler(sys.stdout)

        if sys.stdout.isatty():
            handler.setFormatter(ConsoleFormatter())
        else:
            handler.setFormatter(PlainFormatter())

        root_logger.addHandler(handler)

    # Print the startup banner
    print_banner(env_config)


def resolve_log_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        return getattr(logging, level.upper(), logging.INFO)
    return logging.INFO


def get_logger(name: str, filename: str = None, level: int | str = None) -> logging.Logger:
    """Get a named logger. The filename parameter is kept for API compat but ignored."""
    logger = logging.getLogger(name)
    if level:
        logger.setLevel(resolve_log_level(level))
    return logger


def get_main_logger() -> logging.Logger:
    return logging.getLogger("main")
