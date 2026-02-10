import os

from dotenv import load_dotenv


def get_env_var(key: str, default=None, var_type=str, required=False):
    """
    Load and cast an environment variable safely.

    Args:
        key (str): The name of the environment variable.
        default: A default value if the env var is not set.
        var_type: The type to cast the value to (e.g., int, float, bool).
        required (bool): Raise error if variable is missing and required.

    Returns:
        The cast value of the environment variable.
    """
    value = os.getenv(key, default)

    if value is None:
        if required:
            raise ValueError(f"Environment variable '{key}' is required but not set.")
        return value

    try:
        if var_type == bool:
            return str(value).lower() in ("1", "true", "yes", "on")
        return var_type(value)
    except (ValueError, TypeError):
        raise ValueError(f"Environment variable '{key}' must be of type {var_type.__name__}")

def load_env_variables():
        """
        Loads all required application environment variables.

        Returns:
            dict: A dictionary of loaded and validated environment settings.
        """
        # Load .env file (if it exists)
        load_dotenv()

        try:
            env = {
                # --- Global environment settings
                'LOG_DIR': get_env_var('LOG_DIR', default='logs', var_type=str, required=False),
                'LOG_LEVEL': get_env_var('LOG_LEVEL', default='INFO', required=False),
                'LOG_TO_STDOUT': get_env_var('LOG_TO_STDOUT', default=True, var_type=bool, required=False),
                'SYNC_INTERVAL_SECONDS': get_env_var('SYNC_INTERVAL_SECONDS', default=3600, var_type=int, required=False),
                'MAX_SCRAPE_RETRIES': get_env_var('MAX_SCRAPE_RETRIES', default=5, var_type=int, required=False),

                # --- Wimood API & Scraping ---
                'WIMOOD_API_KEY': get_env_var('WIMOOD_API_KEY', required=True),
                'WIMOOD_API_URL': get_env_var('WIMOOD_API_URL', required=True),
                'WIMOOD_BASE_URL': get_env_var('WIMOOD_BASE_URL', required=True),
                'WIMOOD_CUSTOMER_ID': get_env_var('WIMOOD_CUSTOMER_ID', required=True),

                # --- Shopify Admin API Credentials ---
                'SHOPIFY_STORE_URL': get_env_var('SHOPIFY_STORE_URL', required=True),  # e.g., https://my-store.myshopify.com
                'SHOPIFY_ACCESS_TOKEN': get_env_var('SHOPIFY_ACCESS_TOKEN', required=True),

                # --- Sync Configuration ---
                'SHOPIFY_VENDOR_TAG': get_env_var('SHOPIFY_VENDOR_TAG', default='Wimood_Sync', required=False),

                # --- Scraping ---
                'ENABLE_SCRAPING': get_env_var('ENABLE_SCRAPING', default=False, var_type=bool, required=False),
                'SCRAPE_DELAY_SECONDS': get_env_var('SCRAPE_DELAY_SECONDS', default=2, var_type=int, required=False),
                'FULL_SYNC_INTERVAL_HOURS': get_env_var('FULL_SYNC_INTERVAL_HOURS', default=24, var_type=int, required=False),

                # --- Test Mode ---
                'TEST_MODE': get_env_var('TEST_MODE', default=False, var_type=bool, required=False),
                'TEST_PRODUCT_LIMIT': get_env_var('TEST_PRODUCT_LIMIT', default=5, var_type=int, required=False),

            }
            return env

        except ValueError as e:
            # Re-raise the error so the main function can handle the fatal exit
            raise SystemExit(f"{e}")
