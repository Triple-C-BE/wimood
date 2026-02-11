import sys
import time

from integrations import ShopifyAPI, WimoodAPI, WimoodScraper, sync_products
from utils import (
    ImageDownloader,
    MonitorServer,
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
    # This call now performs all validation and type casting
    ENV = load_env_variables()
except SystemExit as e:
    # Catches the error raised by utils/env.py when a required variable is missing
    print(f"FATAL: Configuration error. {e}")
    sys.exit(1)

# Initialize the logger's global settings using the validated ENV
init_logging_config(ENV)
# Get the actual logger instance
LOGGER = get_main_logger()

# Extract config from the environment
SYNC_INTERVAL = ENV.get('SYNC_INTERVAL_SECONDS', 3600)
TEST_MODE = ENV.get('TEST_MODE', False)
TEST_PRODUCT_LIMIT = ENV.get('TEST_PRODUCT_LIMIT', 5)


def preflight_checks(wimood_api, shopify_api, scraper=None):
    """
    Run pre-flight connectivity checks before starting the sync loop.
    Exits the process if any required API is unreachable or misconfigured.
    """
    LOGGER.info("Running pre-flight API checks...")

    wimood_ok = wimood_api.check_connection()
    shopify_ok = shopify_api.check_connection()

    if not wimood_ok:
        LOGGER.critical("Pre-flight FAILED: Wimood API is not reachable or misconfigured. Exiting.")
        sys.exit(1)

    if not shopify_ok:
        LOGGER.critical("Pre-flight FAILED: Shopify API is not reachable or credentials are invalid. Exiting.")
        sys.exit(1)

    if scraper:
        scraper_ok = scraper.check_connection()
        if not scraper_ok:
            LOGGER.warning("Pre-flight WARNING: Wimood website is not reachable. Scraping will be skipped.")
            return False

    LOGGER.info("Pre-flight checks passed.")
    return True


def run_wimood_sync(request_manager, wimood_api, shopify_api, scraper=None, scrape_cache=None,
                    product_mapping=None):
    """
    Main function to execute the product fetching and Shopify synchronization.
    """
    start_time = time.time()
    LOGGER.info("====================================================================")
    LOGGER.info("STARTING SYNC: Wimood to Shopify")
    LOGGER.info("--------------------------------------------------------------------")

    # Fetch Core Data (API - Fast and reliable for price/stock)
    wimood_core_products = []
    try:
        LOGGER.info("Fetching core data (Title, Price, Stock) via Wimood API...")

        wimood_core_products = wimood_api.fetch_core_products()
        LOGGER.info(f"Fetched {len(wimood_core_products)} products from Wimood API.")

        if TEST_MODE:
            wimood_core_products = wimood_core_products[:TEST_PRODUCT_LIMIT]
            LOGGER.warning(f"TEST MODE: Limiting sync to first {len(wimood_core_products)} products.")
            LOGGER.info("--- Test Mode Product Summary ---")
            for i, p in enumerate(wimood_core_products, 1):
                LOGGER.info(
                    f"  [{i}/{len(wimood_core_products)}] "
                    f"SKU={p.get('sku', '')} | "
                    f"Title={p.get('title', '')} | "
                    f"Brand={p.get('brand', '')} | "
                    f"EAN={p.get('ean', '')} | "
                    f"Price={p.get('price', '0.00')} | "
                    f"Wholesale={p.get('wholesale_price', '0.00')} | "
                    f"Stock={p.get('stock', '0')}"
                )
            LOGGER.info("---------------------------------")

    except Exception as e:
        LOGGER.error(f"FATAL: Failed to fetch core data from Wimood API. Aborting sync: {e}")
        return None, 0

    # Sync with Shopify (enrichment happens inside sync_products if scraper is provided)
    LOGGER.info("Starting synchronization with Shopify...")
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
        LOGGER.error(f"FATAL: Failed to sync products to Shopify: {e}")
        return None, 0

    # Finalize
    end_time = time.time()
    duration = end_time - start_time

    LOGGER.info(f"Products Created: {sync_results['created']}")
    LOGGER.info(f"Products Updated: {sync_results['updated']}")
    LOGGER.info(f"Products Deactivated: {sync_results['deactivated']}")
    LOGGER.info(f"Products Skipped: {sync_results['skipped']}")
    LOGGER.info(f"Errors: {sync_results['errors']}")

    LOGGER.info("--------------------------------------------------------------------")
    LOGGER.info(f"SYNC COMPLETE | Duration: {duration:.2f} seconds")
    LOGGER.info("====================================================================")

    return sync_results, duration


if __name__ == "__main__":
    sleep_display_time = format_seconds_to_human_readable(SYNC_INTERVAL)

    if TEST_MODE:
        LOGGER.warning(f"TEST MODE ENABLED — product limit: {TEST_PRODUCT_LIMIT}")

    # Initialize managers once at startup
    try:
        REQUEST_MANAGER = init_request_manager(ENV)
        wimood_api = WimoodAPI(ENV, REQUEST_MANAGER)
        product_mapping = ProductMapping()
        LOGGER.info(f"Product mapping loaded with {len(product_mapping)} existing mappings.")
        shopify_api = ShopifyAPI(ENV, REQUEST_MANAGER, product_mapping=product_mapping)
    except Exception as e:
        LOGGER.critical(f"Failed to initialize managers: {e}")
        sys.exit(1)

    # Initialize scraper + cache (always needed for new product enrichment)
    image_downloader = ImageDownloader(REQUEST_MANAGER)
    scraper = WimoodScraper(ENV, REQUEST_MANAGER, image_downloader=image_downloader)
    scrape_cache = ScrapeCache()

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

    while True:
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
            LOGGER.exception(f"Unhandled critical exception in sync loop: {main_e}")
            sync_results, duration = None, 0

        if monitor and sync_results is not None:
            monitor.update_status(
                sync_results=sync_results,
                duration=duration,
                next_sync_in=SYNC_INTERVAL,
            )

        LOGGER.info("Sync cycle complete. Next run in %s.\n", sleep_display_time)
        time.sleep(SYNC_INTERVAL)
