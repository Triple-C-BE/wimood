import logging
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from requests import Response

# Get a dedicated logger for API calls
API_LOGGER = logging.getLogger('wimood_api')


class WimoodAPI:
    """
    Manages communication with the Wimood XML API to fetch core product data.
    """

    def __init__(self, env: Dict[str, str], request_manager):
        """
        Initializes the fetcher with necessary configuration and a RequestManager.
        """
        self.api_url = env.get('WIMOOD_API_URL')
        self.api_key = env.get('WIMOOD_API_KEY')
        self.customer_id = env.get('WIMOOD_CUSTOMER_ID')
        self.request_manager = request_manager

        # Construct the full URL for the product feed
        # Assuming the API requires the key as a query parameter
        self.full_url = f"{self.api_url}/index.php?api_key={self.api_key}&klantnummer={self.customer_id}"

        API_LOGGER.info(f"WimoodAPIFetcher initialized for URL: {self.api_url}")

    def check_connection(self) -> bool:
        """
        Pre-flight check: verify we can reach the Wimood API and get valid XML with products.

        Returns:
            True if connection is healthy, False otherwise.
        """
        API_LOGGER.info("Running Wimood API pre-flight check...")
        response = self.request_manager.request('GET', self.full_url)

        if response is None:
            API_LOGGER.error("Pre-flight FAILED: Could not reach Wimood API (network error or timeout).")
            return False

        if response.status_code != 200:
            API_LOGGER.error(f"Pre-flight FAILED: Wimood API returned status {response.status_code}.")
            return False

        if "Invalid API Key" in response.text:
            API_LOGGER.error("Pre-flight FAILED: Wimood API returned 'Invalid API Key'.")
            return False

        try:
            root = ET.fromstring(response.content.decode('utf-8'))
        except ET.ParseError as e:
            API_LOGGER.error(f"Pre-flight FAILED: Response is not valid XML: {e}")
            return False

        products = root.findall('.//product')
        if not products:
            API_LOGGER.error("Pre-flight FAILED: XML contains no <product> elements.")
            return False

        API_LOGGER.info(f"Pre-flight OK: Wimood API reachable, found {len(products)} products in feed.")
        return True

    def fetch_core_products(self) -> Optional[List[Dict]]:
        """
        Fetches the XML product feed, parses it, and returns a list of product dictionaries.

        Returns:
            List[Dict] or None: List of product data or None on critical failure.
        """
        API_LOGGER.info(f"Attempting to fetch data from: {self.api_url}")

        # 1. Execute the Request
        response: Optional[Response] = self.request_manager.request('GET', self.full_url)

        if response is None:
            # RequestManager already logged the retry errors
            API_LOGGER.error("Request failed after all retries. Cannot proceed with fetching.")
            return None

        # 2. Check for XML Specific Errors (like 401 or invalid key)
        if "Invalid API Key" in response.text or response.status_code == 401:
            API_LOGGER.critical(
                f"API Key check failed. Response status: {response.status_code}. "
                "Check WIMOOD_API_KEY and WIMOOD_API_URL."
            )
            return None

        # 3. Parse the XML Content
        try:
            # Decode content and parse the XML tree
            root = ET.fromstring(response.content.decode('utf-8'))
        except ET.ParseError as e:
            API_LOGGER.error(f"Failed to parse XML response from API. Content might be corrupted: {e}")
            return None

        # 4. Extract Product Data
        products_data = []

        # Adjust this XPath based on your actual XML structure.
        # Common structure: <root><product_list><product>...</product></product_list></root>
        product_elements = root.findall('.//product')

        if not product_elements:
            API_LOGGER.warning("No <product> elements found in the XML feed. Check XML structure.")
            return products_data  # Return empty list, not None

        for element in product_elements:
            try:
                product = {
                    'product_id': element.findtext('product_id', default=''),
                    'sku': element.findtext('product_code', default=''),
                    'title': element.findtext('product_name', default=''),
                    'brand': element.findtext('brand', default=''),
                    'ean': element.findtext('ean', default='').strip(),
                    'price': element.findtext('prijs', default='0.00'),
                    'msrp': element.findtext('msrp', default='0.00'),
                    'stock': element.findtext('stock', default='0'),
                }
                API_LOGGER.debug(f"Parsed product: {product}")
                products_data.append(product)
            except Exception as e:
                # Log an error but continue processing other products
                API_LOGGER.warning(
                    f"Skipping product due to parsing error: {e}. Element XML: {ET.tostring(element)[:100]}")

        return products_data
