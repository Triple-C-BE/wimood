import sys
import time

from integrations import ShopifyAPI, WimoodAPI, WimoodScraper, sync_products
from utils import (
    ImageDownloader,
    ProductMapping,
    ScrapeCache,
    format_seconds_to_human_readable,
    get_main_logger,
    init_logging_config,
    init_request_manager,
    load_env_variables,
)

FULL_SYNC_FLAG = "--full-sync" in sys.argv

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
ENABLE_SCRAPING = ENV.get('ENABLE_SCRAPING', False)


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
                    product_mapping=None, scrape_mode="new_only"):
    """
    Main function to execute the product fetching and Shopify synchronization.

    Args:
        scrape_mode: "new_only" = only scrape new products, "full" = scrape all products
    """
    start_time = time.time()
    LOGGER.info("====================================================================")
    LOGGER.info(f"STARTING SYNC: Wimood to Shopify (scrape_mode={scrape_mode})")
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
                    f"MSRP={p.get('msrp', '0.00')} | "
                    f"Stock={p.get('stock', '0')}"
                )
            LOGGER.info("---------------------------------")

    except Exception as e:
        LOGGER.error(f"FATAL: Failed to fetch core data from Wimood API. Aborting sync: {e}")
        return

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
            scrape_mode=scrape_mode,
        )
    except Exception as e:
        LOGGER.error(f"FATAL: Failed to sync products to Shopify: {e}")
        return

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


if __name__ == "__main__":
    sleep_display_time = format_seconds_to_human_readable(SYNC_INTERVAL)
    FULL_SYNC_INTERVAL = ENV.get('FULL_SYNC_INTERVAL_HOURS', 24) * 3600

    if TEST_MODE:
        LOGGER.warning(f"TEST MODE ENABLED — product limit: {TEST_PRODUCT_LIMIT}")

    if FULL_SYNC_FLAG:
        LOGGER.info("Full sync requested via --full-sync flag.")

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

    # Initialize scraper + cache if enabled
    scraper = None
    scrape_cache = None
    if ENABLE_SCRAPING:
        LOGGER.info("Scraping is ENABLED.")
        image_downloader = ImageDownloader(REQUEST_MANAGER)
        scraper = WimoodScraper(ENV, REQUEST_MANAGER, image_downloader=image_downloader)
        scrape_cache = ScrapeCache()
    else:
        LOGGER.info("Scraping is DISABLED. Products will sync without images/descriptions.")

    # Run pre-flight checks once at startup
    scraping_ok = preflight_checks(wimood_api, shopify_api, scraper=scraper)
    if not scraping_ok and scraper:
        LOGGER.warning("Disabling scraper due to failed pre-flight check.")
        scraper = None

    # Track when the last full sync was run
    last_full_sync = 0  # Force full sync on first run if --full-sync

    while True:
        # Determine scrape mode for this cycle
        now = time.time()
        time_since_full = now - last_full_sync

        if FULL_SYNC_FLAG and last_full_sync == 0:
            # First run with --full-sync flag
            scrape_mode = "full"
        elif time_since_full >= FULL_SYNC_INTERVAL:
            scrape_mode = "full"
        else:
            scrape_mode = "new_only"

        try:
            run_wimood_sync(
                REQUEST_MANAGER,
                wimood_api,
                shopify_api,
                scraper=scraper,
                scrape_cache=scrape_cache,
                product_mapping=product_mapping,
                scrape_mode=scrape_mode,
            )

            if scrape_mode == "full":
                last_full_sync = time.time()

        except Exception as main_e:
            LOGGER.exception(f"Unhandled critical exception in sync loop: {main_e}")

        # Exit after single run if --full-sync flag was used
        if FULL_SYNC_FLAG:
            LOGGER.info("Full sync complete. Exiting (--full-sync is a one-shot run).")
            break

        next_full_in = FULL_SYNC_INTERVAL - (time.time() - last_full_sync)
        LOGGER.info(
            "Sync cycle complete. Next run in %s. Next full sync in %s.\n",
            sleep_display_time,
            format_seconds_to_human_readable(max(0, int(next_full_in))),
        )
        time.sleep(SYNC_INTERVAL)
