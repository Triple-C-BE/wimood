import os
import sys
import time
from datetime import datetime
from utils import (
    load_env_variables,
    init_logging_config,
    get_main_logger,
    init_request_manager,
    format_seconds_to_human_readable
)
from integrations import WimoodAPI


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

# Extract the synchronization interval from the environment
SYNC_INTERVAL = ENV.get('SYNC_INTERVAL_SECONDS', 3600) # Default to 1 hour (3600s)



def run_wimood_sync():
    """
    Main function to execute the product fetching and Shopify synchronization.
    """
    start_time = time.time()
    LOGGER.info("====================================================================")
    LOGGER.info(f"🔄 STARTING SYNC: Wimood to Shopify")
    LOGGER.info("--------------------------------------------------------------------")

    # Initialize Managers
    try:
        # Managers handle their own sub-logging
        REQUEST_MANAGER = init_request_manager(ENV)
        wimood_api = WimoodAPI(ENV, REQUEST_MANAGER)

    except Exception as e:
        LOGGER.error(f"Failed to initialize managers. Aborting sync: {e}")
        return

    #Fetch Core Data (API - Fast and reliable for price/stock)
    wimood_core_products = []
    try:
        LOGGER.info("Fetching core data (Title, Price, Stock) via Wimood API...")

        wimood_core_products = wimood_api.fetch_core_products()
        LOGGER.info(f"Fetched {len(wimood_core_products)} products from Wimood API.")
    except Exception as e:
        LOGGER.error(f"FATAL: Failed to fetch core data from Wimood API. Aborting sync: {e}")
        return
#
#     # 3. Enrich Data (Targeted Scraping - Only for missing/changed details)
#     SYNC_CYCLE_LOG.info("Step 2: Enriching product details (Description, Images) with targeted scraping...")
#
#     # Get the latest sync map to determine what needs scraping
#     sync_map = sync_manager.load_sync_map()
#     products_to_sync = []
#
#     for product_data in wimood_core_products:
#         product = Product.from_wimood_data(product_data)
#
#         # Check if product is new or needs detail refresh based on your sync_map logic
#         needs_detail_scrape = sync_manager.needs_detail_scrape(product, sync_map)
#
#         if needs_detail_scrape:
#             SYNC_CYCLE_LOG.debug(f"Scraping details for product ID: {product.source_id}")
#             try:
#                 # Assuming the API provides a product URL for the scraper
#                 product_url = f"{WIMOOD_BASE_URL}/product/{product.source_id}"  # Adjust URL pattern as needed
#                 details = detail_scraper.scrape_product_details(product_url)
#                 product.update_details(details)  # Method to merge scraped data into the Product model
#             except Exception as e:
#                 SYNC_CYCLE_LOG.warning(
#                     f"Failed to scrape details for {product.source_id}. Will try next cycle. Error: {e}")
#
#         products_to_sync.append(product)
#
#     SYNC_CYCLE_LOG.info("Detail enrichment complete.")
#
#     # 4. Sync with Shopify
#     SYNC_CYCLE_LOG.info("Step 3: Starting synchronization with Shopify...")
#
#     # Get all products from Shopify that you own (e.g., matching a specific vendor tag)
#     shopify_products_map = shopify_manager.get_synced_products_map(sync_map)
#
#     sync_results = shopify_manager.process_sync(
#         source_products=products_to_sync,
#         shopify_products_map=shopify_products_map,
#         sync_manager=sync_manager
#     )
#
    # Finalize
    end_time = time.time()
    duration = end_time - start_time

    #LOGGER.info(f"Products Created: {sync_results['created']}")
    #LOGGER.info(f"Products Updated: {sync_results['updated']}")
    #LOGGER.info(f"Products Deactivated: {sync_results['deactivated']}")

    LOGGER.info("--------------------------------------------------------------------")
    LOGGER.info(f"✅ SYNC COMPLETE | Duration: {duration:.2f} seconds")
    LOGGER.info("====================================================================")


if __name__ == "__main__":
    sleep_display_time = format_seconds_to_human_readable(SYNC_INTERVAL)

    while True:
        try:
            # Execute the full synchronization run
            run_wimood_sync()

        except Exception as main_e:
            # The logging.exception function prints the traceback automatically
            LOGGER.exception(f"❌ Unhandled critical exception in sync loop: {main_e}")

        LOGGER.info("😴 Sync cycle complete. Next run in %s...\n", sleep_display_time)
        time.sleep(SYNC_INTERVAL)