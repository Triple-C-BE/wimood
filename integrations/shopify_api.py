import time
import logging
from typing import List, Dict, Optional

LOGGER = logging.getLogger('shopify_api')


class ShopifyAPI:
    """
    Manages communication with the Shopify REST Admin API for product CRUD operations.
    """

    API_VERSION = '2024-01'
    RATE_LIMIT_DELAY = 0.5  # seconds between requests to stay under 2 req/sec

    def __init__(self, env: Dict[str, str], request_manager):
        shop_name = env.get('SHOPIFY_SHOP_NAME')
        api_key = env.get('SHOPIFY_API_KEY')
        api_password = env.get('SHOPIFY_API_PASSWORD')
        self.vendor_tag = env.get('SHOPIFY_VENDOR_TAG', 'Wimood_Sync')
        self.request_manager = request_manager

        self.base_url = (
            f"https://{api_key}:{api_password}@{shop_name}.myshopify.com"
            f"/admin/api/{self.API_VERSION}"
        )

        LOGGER.info(f"ShopifyAPI initialized for shop: {shop_name}")

    def _rate_limit(self):
        """Sleep briefly to respect Shopify's 2 req/sec rate limit."""
        time.sleep(self.RATE_LIMIT_DELAY)

    def get_all_products(self) -> List[Dict]:
        """
        Fetch all products managed by this sync (filtered by vendor tag).
        Handles pagination via the Link header.

        Returns:
            List of Shopify product dicts.
        """
        products = []
        url = f"{self.base_url}/products.json?vendor={self.vendor_tag}&limit=250"

        while url:
            self._rate_limit()
            response = self.request_manager.request('GET', url)

            if response is None:
                LOGGER.error("Failed to fetch products from Shopify.")
                return products

            data = response.json()
            products.extend(data.get('products', []))

            # Handle pagination via Link header
            url = self._get_next_page_url(response)

        LOGGER.info(f"Fetched {len(products)} products from Shopify (vendor={self.vendor_tag}).")
        return products

    def _get_next_page_url(self, response) -> Optional[str]:
        """Extract the next page URL from Shopify's Link header."""
        link_header = response.headers.get('Link', '')
        if 'rel="next"' not in link_header:
            return None

        for part in link_header.split(','):
            if 'rel="next"' in part:
                # Extract URL between < and >
                url = part.split('<')[1].split('>')[0]
                return url

        return None

    def create_product(self, product_data: Dict) -> Optional[Dict]:
        """
        Create a new product in Shopify.

        Args:
            product_data: Dict with keys: sku, title, price, stock

        Returns:
            Created Shopify product dict, or None on failure.
        """
        payload = {
            "product": {
                "title": product_data['title'],
                "vendor": self.vendor_tag,
                "status": "active",
                "variants": [
                    {
                        "sku": product_data['sku'],
                        "price": product_data['price'],
                        "inventory_management": "shopify",
                    }
                ],
            }
        }

        self._rate_limit()
        response = self.request_manager.request(
            'POST',
            f"{self.base_url}/products.json",
            json=payload,
        )

        if response is None:
            LOGGER.error(f"Failed to create product: {product_data['sku']}")
            return None

        created = response.json().get('product')
        if created:
            LOGGER.info(f"Created product in Shopify: {product_data['sku']} (ID: {created['id']})")
            self._set_inventory_level(created, int(product_data.get('stock', 0)))
        return created

    def update_product(self, shopify_product_id: int, product_data: Dict) -> Optional[Dict]:
        """
        Update an existing Shopify product's title, price, and stock.

        Args:
            shopify_product_id: The Shopify product ID.
            product_data: Dict with keys: sku, title, price, stock

        Returns:
            Updated Shopify product dict, or None on failure.
        """
        variant_id = None
        # We need to fetch the product to get variant ID for price update
        self._rate_limit()
        existing = self.request_manager.request(
            'GET', f"{self.base_url}/products/{shopify_product_id}.json"
        )
        if existing:
            existing_data = existing.json().get('product', {})
            variants = existing_data.get('variants', [])
            if variants:
                variant_id = variants[0]['id']

        # Update the product title and status
        payload = {
            "product": {
                "id": shopify_product_id,
                "title": product_data['title'],
                "status": "active",
            }
        }

        self._rate_limit()
        response = self.request_manager.request(
            'PUT',
            f"{self.base_url}/products/{shopify_product_id}.json",
            json=payload,
        )

        if response is None:
            LOGGER.error(f"Failed to update product {shopify_product_id}")
            return None

        # Update variant (price) if we have a variant ID
        if variant_id:
            variant_payload = {
                "variant": {
                    "id": variant_id,
                    "price": product_data['price'],
                }
            }
            self._rate_limit()
            self.request_manager.request(
                'PUT',
                f"{self.base_url}/variants/{variant_id}.json",
                json=variant_payload,
            )

        updated = response.json().get('product')
        if updated:
            LOGGER.info(f"Updated product in Shopify: {product_data['sku']} (ID: {shopify_product_id})")
            self._set_inventory_level(updated, int(product_data.get('stock', 0)))
        return updated

    def deactivate_product(self, shopify_product_id: int) -> bool:
        """
        Deactivate a product by setting its status to 'draft'.

        Returns:
            True if successful, False otherwise.
        """
        payload = {
            "product": {
                "id": shopify_product_id,
                "status": "draft",
            }
        }

        self._rate_limit()
        response = self.request_manager.request(
            'PUT',
            f"{self.base_url}/products/{shopify_product_id}.json",
            json=payload,
        )

        if response is None:
            LOGGER.error(f"Failed to deactivate product {shopify_product_id}")
            return False

        LOGGER.info(f"Deactivated product in Shopify (ID: {shopify_product_id})")
        return True

    def _set_inventory_level(self, shopify_product: Dict, quantity: int):
        """
        Set inventory quantity for a product's first variant.
        Uses the inventory_levels/set endpoint.
        """
        variants = shopify_product.get('variants', [])
        if not variants:
            return

        inventory_item_id = variants[0].get('inventory_item_id')
        if not inventory_item_id:
            return

        # First get the location ID
        self._rate_limit()
        locations_resp = self.request_manager.request(
            'GET', f"{self.base_url}/locations.json"
        )
        if locations_resp is None:
            LOGGER.warning("Could not fetch locations for inventory update.")
            return

        locations = locations_resp.json().get('locations', [])
        if not locations:
            LOGGER.warning("No locations found for inventory update.")
            return

        location_id = locations[0]['id']

        payload = {
            "location_id": location_id,
            "inventory_item_id": inventory_item_id,
            "available": quantity,
        }

        self._rate_limit()
        response = self.request_manager.request(
            'POST',
            f"{self.base_url}/inventory_levels/set.json",
            json=payload,
        )

        if response is None:
            LOGGER.warning(f"Failed to set inventory for item {inventory_item_id}")
