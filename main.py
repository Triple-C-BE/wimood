import sys
import time

from integrations import ShopifyAPI, WimoodAPI, WimoodScraper, sync_orders, sync_products
from utils import (
    ImageDownloader,
    MonitorServer,
    OrderStore,
    ProductMapping,
    ScrapeCache,
    format_seconds_to_human_readable,
    get_main_logger,
    init_logging_config,
    init_request_manager,
    load_env_variables,
)

# --- Configuration & Setup ---

try:
    ENV = load_env_variables()
except SystemExit as e:
    print(f"FATAL: Configuration error. {e}")
    sys.exit(1)

init_logging_config(ENV)
LOGGER = get_main_logger()

SYNC_INTERVAL = ENV.get('SYNC_INTERVAL_SECONDS', 3600)
TEST_MODE = ENV.get('TEST_MODE', False)
TEST_PRODUCT_LIMIT = ENV.get('TEST_PRODUCT_LIMIT', 5)
ENABLE_ORDER_SYNC = ENV.get('ENABLE_ORDER_SYNC', False)
ORDER_SYNC_INTERVAL = ENV.get('ORDER_SYNC_INTERVAL_SECONDS', 900)


def preflight_checks(wimood_api, shopify_api, scraper=None):
    """
    Run pre-flight connectivity checks before starting the sync loop.
    Exits the process if any required API is unreachable or misconfigured.
    """
    LOGGER.info("Running pre-flight API checks...")

    wimood_ok = wimood_api.check_connection()
    shopify_ok = shopify_api.check_connection()

    if not wimood_ok:
        LOGGER.critical("Wimood API is not reachable or misconfigured. Exiting.")
        sys.exit(1)

    if not shopify_ok:
        LOGGER.critical("Shopify API is not reachable or credentials are invalid. Exiting.")
        sys.exit(1)

    if scraper:
        scraper_ok = scraper.check_connection()
        if not scraper_ok:
            LOGGER.warning("Wimood website is not reachable. Scraping will be skipped.")
            return False

    LOGGER.info("Pre-flight checks passed.")
    return True


def _format_next_timers(next_product_sync, next_order_sync):
    """Build a 'next sync in ...' status line showing countdowns for both timers."""
    now = time.time()
    parts = []

    product_remaining = max(0, next_product_sync - now)
    parts.append(f"products in {format_seconds_to_human_readable(int(product_remaining))}")

    if next_order_sync < float('inf'):
        order_remaining = max(0, next_order_sync - now)
        parts.append(f"orders in {format_seconds_to_human_readable(int(order_remaining))}")

    return "Next sync: " + ", ".join(parts)


def run_wimood_sync(request_manager, wimood_api, shopify_api, scraper=None, scrape_cache=None,
                    product_mapping=None):
    """
    Main function to execute the product fetching and Shopify synchronization.
    """
    start_time = time.time()
    LOGGER.info("Product sync started")

    # Fetch Core Data
    wimood_core_products = []
    try:
        wimood_core_products = wimood_api.fetch_core_products()
        LOGGER.info(f"Fetched {len(wimood_core_products)} products from Wimood")

        if TEST_MODE:
            wimood_core_products = wimood_core_products[:TEST_PRODUCT_LIMIT]
            LOGGER.warning(f"TEST MODE: Limited to {len(wimood_core_products)} products")
            for i, p in enumerate(wimood_core_products, 1):
                LOGGER.info(
                    f"  [{i}/{len(wimood_core_products)}] "
                    f"{p.get('sku', '')} — {p.get('title', '')} "
                    f"(${p.get('price', '0.00')}, stock: {p.get('stock', '0')})"
                )

    except Exception as e:
        LOGGER.error(f"Failed to fetch from Wimood API, aborting: {e}")
        return None, 0

    # Sync with Shopify
    try:
        sync_results = sync_products(
            wimood_core_products,
            shopify_api,
            test_mode=TEST_MODE,
            scraper=scraper,
            scrape_cache=scrape_cache,
            product_mapping=product_mapping,
        )
    except Exception as e:
        LOGGER.error(f"Failed to sync products to Shopify: {e}")
        return None, 0

    duration = time.time() - start_time

    LOGGER.info(
        f"Product sync done in {duration:.1f}s — "
        f"created: {sync_results['created']}, updated: {sync_results['updated']}, "
        f"deactivated: {sync_results['deactivated']}, skipped: {sync_results['skipped']}, "
        f"errors: {sync_results['errors']}"
    )

    return sync_results, duration


def run_order_sync(shopify_api, order_store, wimood_api=None, product_mapping=None):
    """
    Execute dropship order sync: fetch orders, submit to Wimood, poll for status, fulfill.
    """
    start_time = time.time()
    LOGGER.info("Order sync started")

    try:
        order_results = sync_orders(shopify_api, order_store,
                                    wimood_api=wimood_api, product_mapping=product_mapping)
    except Exception as e:
        LOGGER.error(f"Failed to sync orders: {e}")
        return None, 0

    duration = time.time() - start_time

    LOGGER.info(
        f"Order sync done in {duration:.1f}s — "
        f"new: {order_results['new_orders']}, submitted: {order_results['submitted']}, "
        f"fulfilled: {order_results['fulfilled']}, cancelled: {order_results['cancelled']}, "
        f"polled: {order_results['poll_checked']}, "
        f"errors: {order_results['errors']}"
    )

    return order_results, duration


if __name__ == "__main__":
    # Initialize managers once at startup
    try:
        REQUEST_MANAGER = init_request_manager(ENV)
        wimood_api = WimoodAPI(ENV, REQUEST_MANAGER)
        product_mapping = ProductMapping()
        LOGGER.info(f"Loaded {len(product_mapping)} product mappings")
        shopify_api = ShopifyAPI(ENV, REQUEST_MANAGER, product_mapping=product_mapping)
    except Exception as e:
        LOGGER.critical(f"Failed to initialize: {e}")
        sys.exit(1)

    # Initialize scraper + cache (always needed for new product enrichment)
    image_downloader = ImageDownloader(REQUEST_MANAGER)
    scraper = WimoodScraper(ENV, REQUEST_MANAGER, image_downloader=image_downloader)
    scrape_cache = ScrapeCache()

    # Initialize order store if order sync is enabled
    order_store = None
    if ENABLE_ORDER_SYNC:
        order_store = OrderStore()
        LOGGER.info(f"Order store loaded with {len(order_store)} existing orders")

        order_api_ok = wimood_api.check_order_api_connection()
        if not order_api_ok:
            LOGGER.warning("Wimood Order API unreachable. Dropship submission will be disabled.")

    # Run pre-flight checks once at startup
    scraping_ok = preflight_checks(wimood_api, shopify_api, scraper=scraper)
    if not scraping_ok and scraper:
        LOGGER.warning("Disabling scraper due to failed pre-flight check.")
        scraper = None

    # Start monitor server if enabled
    monitor = None
    if ENV.get('ENABLE_MONITORING', False):
        monitor = MonitorServer(port=ENV.get('MONITOR_PORT', 8080))
        monitor.start()

    # Dual-timer loop: track next run time for each sync independently
    next_product_sync = 0  # Run immediately on first iteration
    next_order_sync = 0 if ENABLE_ORDER_SYNC else float('inf')

    while True:
        now = time.time()

        # Product sync
        if now >= next_product_sync:
            if monitor:
                monitor.set_running()

            try:
                sync_results, duration = run_wimood_sync(
                    REQUEST_MANAGER,
                    wimood_api,
                    shopify_api,
                    scraper=scraper,
                    scrape_cache=scrape_cache,
                    product_mapping=product_mapping,
                )
            except Exception as main_e:
                LOGGER.exception(f"Unhandled exception in product sync: {main_e}")
                sync_results, duration = None, 0

            if monitor and sync_results is not None:
                monitor.update_status(
                    sync_results=sync_results,
                    duration=duration,
                    next_sync_in=SYNC_INTERVAL,
                )

            next_product_sync = time.time() + SYNC_INTERVAL
            LOGGER.info(_format_next_timers(next_product_sync, next_order_sync))

        # Order sync
        if ENABLE_ORDER_SYNC and now >= next_order_sync:
            try:
                order_results, order_duration = run_order_sync(
                    shopify_api, order_store,
                    wimood_api=wimood_api, product_mapping=product_mapping,
                )
            except Exception as order_e:
                LOGGER.exception(f"Unhandled exception in order sync: {order_e}")
                order_results, order_duration = None, 0

            if monitor and order_results is not None:
                monitor.update_order_status(
                    order_results=order_results,
                    duration=order_duration,
                    next_sync_in=ORDER_SYNC_INTERVAL,
                )

            next_order_sync = time.time() + ORDER_SYNC_INTERVAL
            LOGGER.info(_format_next_timers(next_product_sync, next_order_sync))

        # Sleep until the next sync is due (check every 10 seconds)
        next_due = min(next_product_sync, next_order_sync)
        sleep_for = max(0, min(next_due - time.time(), 10))
        time.sleep(sleep_for)
