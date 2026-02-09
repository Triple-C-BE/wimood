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
from integrations import WimoodAPI, ShopifyAPI, sync_products


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
        shopify_api = ShopifyAPI(ENV, REQUEST_MANAGER)

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

    # Sync with Shopify
    LOGGER.info("Starting synchronization with Shopify...")
    try:
        sync_results = sync_products(wimood_core_products, shopify_api)
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