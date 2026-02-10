import json
import logging
import time
from typing import Dict, List, Optional

from utils.image_downloader import ImageDownloader

LOGGER = logging.getLogger('shopify_api')


class ShopifyAPI:
    """
    Manages communication with the Shopify REST Admin API for product CRUD operations.
    """

    API_VERSION = '2023-04'
    RATE_LIMIT_DELAY = 0.5  # seconds between requests to stay under 2 req/sec

    def __init__(self, env: Dict[str, str], request_manager, product_mapping=None):
        store_url = env.get('SHOPIFY_STORE_URL').rstrip('/')
        access_token = env.get('SHOPIFY_ACCESS_TOKEN')
        self.vendor_tag = env.get('SHOPIFY_VENDOR_TAG', 'Wimood_Sync')
        self.request_manager = request_manager
        self.product_mapping = product_mapping

        self.base_url = f"{store_url}/admin/api/{self.API_VERSION}"
        self.auth_headers = {
            'X-Shopify-Access-Token': access_token,
            'Content-Type': 'application/json',
        }

        self._location_id = None  # Cached on first use

        LOGGER.info(f"ShopifyAPI initialized for store: {store_url}")

    def check_connection(self) -> bool:
        """
        Pre-flight check: verify Shopify credentials by calling GET /shop.json.

        Returns:
            True if credentials are valid, False otherwise.
        """
        LOGGER.info("Running Shopify API pre-flight check...")
        url = f"{self.base_url}/shop.json"
        response = self._request('GET', url)

        if response is None:
            LOGGER.error(
                "Pre-flight FAILED: Could not reach Shopify API. "
                "Check SHOPIFY_STORE_URL and SHOPIFY_ACCESS_TOKEN."
            )
            return False

        data = response.json()
        shop = data.get('shop')
        if not shop:
            LOGGER.error(f"Pre-flight FAILED: Shopify response missing 'shop' data. Body: {response.text[:500]}")
            return False

        LOGGER.info(f"Pre-flight OK: Connected to Shopify shop '{shop.get('name', '?')}' (ID: {shop.get('id', '?')}).")
        return True

    def _request(self, method, url, **kwargs):
        """Make an authenticated request to the Shopify API."""
        # Merge auth headers with any additional headers in kwargs
        headers = {**self.auth_headers, **kwargs.pop('headers', {})}
        return self.request_manager.request(method, url, headers=headers, **kwargs)

    def _rate_limit(self):
        """Sleep briefly to respect Shopify's 2 req/sec rate limit."""
        time.sleep(self.RATE_LIMIT_DELAY)

    def _log_rate_limit(self, response):
        """Log Shopify rate limit header if present."""
        rate_limit = response.headers.get('X-Shopify-Shop-Api-Call-Limit')
        if rate_limit:
            LOGGER.debug(f"Rate limit: {rate_limit}")

    def get_all_products(self) -> List[Dict]:
        """
        Fetch all products managed by this sync.
        Uses product mapping (by IDs) if available, otherwise falls back to vendor tag filtering.

        Returns:
            List of Shopify product dicts.
        """
        if self.product_mapping and len(self.product_mapping) > 0:
            return self._get_products_by_mapping()
        return self._get_products_by_vendor_tag()

    def _get_products_by_mapping(self) -> List[Dict]:
        """Fetch products by their mapped Shopify IDs."""
        shopify_ids = self.product_mapping.get_all_shopify_ids()
        if not shopify_ids:
            LOGGER.info("No mapped products found.")
            return []

        LOGGER.info(f"Fetching {len(shopify_ids)} products by mapping...")
        products = []
        batch_size = 250
        for i in range(0, len(shopify_ids), batch_size):
            batch = shopify_ids[i:i + batch_size]
            ids_param = ','.join(str(pid) for pid in batch)
            url = f"{self.base_url}/products.json?ids={ids_param}&limit=250"

            self._rate_limit()
            response = self._request('GET', url)
            if response:
                self._log_rate_limit(response)
                data = response.json()
                products.extend(data.get('products', []))

        LOGGER.info(f"Fetched {len(products)} mapped products from Shopify.")
        return products

    def _get_products_by_vendor_tag(self) -> List[Dict]:
        """Fallback: fetch products by vendor tag."""
        products = []
        url = f"{self.base_url}/products.json?vendor={self.vendor_tag}&limit=250"

        while url:
            self._rate_limit()
            response = self._request('GET', url)

            if response is None:
                LOGGER.error("Failed to fetch products from Shopify.")
                return products

            self._log_rate_limit(response)
            data = response.json()
            products.extend(data.get('products', []))
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
                Optional enriched keys: body_html, images, ean, msrp, specs, brand

        Returns:
            Created Shopify product dict, or None on failure.
        """
        brand = product_data.get('brand', '').strip()

        variant = {
            "sku": product_data['sku'],
            "price": product_data['price'],
            "inventory_management": "shopify",
        }

        # Add barcode (EAN) if available
        ean = product_data.get('ean', '').strip()
        if ean:
            variant["barcode"] = ean

        product_payload = {
            "title": product_data['title'],
            "vendor": brand,
            "status": "active",
            "variants": [variant],
        }

        # Add enriched description
        body_html = product_data.get('body_html', '')
        if body_html:
            product_payload["body_html"] = body_html
            LOGGER.info(f"  Including description ({len(body_html)} chars)")

        # Add images from local files (base64 upload)
        image_payloads = self._build_image_payloads(product_data)
        if image_payloads:
            product_payload["images"] = image_payloads
            LOGGER.info(f"  Including {len(image_payloads)} images (base64 upload)")

        # Add metafields for structured data
        metafields = self._build_metafields(product_data)
        if metafields:
            product_payload["metafields"] = metafields

        payload = {"product": product_payload}

        self._rate_limit()
        create_url = f"{self.base_url}/products.json"
        LOGGER.debug(f"POST {create_url}")
        response = self._request(
            'POST',
            create_url,
            json=payload,
        )

        if response is None:
            LOGGER.error(f"Failed to create product: {product_data['sku']}")
            return None

        self._log_rate_limit(response)

        data = response.json()
        if 'errors' in data:
            LOGGER.error(f"Shopify error creating product {product_data['sku']}: {data['errors']}")
            return None

        created = data.get('product')
        if created:
            created_images = created.get('images', [])
            LOGGER.info(
                f"  Created in Shopify: ID={created['id']}, "
                f"images={len(created_images)}, "
                f"status={created.get('status')}"
            )
            if self.product_mapping and product_data.get('product_id'):
                self.product_mapping.set_mapping(
                    product_data['product_id'], created['id'], product_data['sku']
                )
            self._set_inventory_level(created, int(product_data.get('stock', 0)))
        return created

    def update_product(self, shopify_product_id: int, product_data: Dict,
                       existing_shopify_product: Dict = None) -> Optional[Dict]:
        """
        Update an existing Shopify product's title, price, and stock.

        Args:
            shopify_product_id: The Shopify product ID.
            product_data: Dict with keys: sku, title, price, stock
            existing_shopify_product: Optional existing Shopify product dict (avoids extra GET)

        Returns:
            Updated Shopify product dict, or None on failure.
        """
        # Get variant ID from existing product data (no extra API call needed)
        variant_id = None
        if existing_shopify_product:
            variants = existing_shopify_product.get('variants', [])
            if variants:
                variant_id = variants[0]['id']

        # Update the product title, status, vendor, and variant price in one call
        brand = product_data.get('brand', '').strip()
        product_payload = {
            "id": shopify_product_id,
            "title": product_data['title'],
            "vendor": brand,
            "status": "active",
        }

        # Include variant update inline (avoids separate variant PUT)
        if variant_id:
            product_payload["variants"] = [{
                "id": variant_id,
                "price": product_data['price'],
            }]

        # Add enriched description if available
        body_html = product_data.get('body_html', '')
        if body_html:
            product_payload["body_html"] = body_html
            LOGGER.info(f"  Including description ({len(body_html)} chars)")

        # Add images from local files (base64 upload)
        image_payloads = self._build_image_payloads(product_data)
        if image_payloads:
            product_payload["images"] = image_payloads
            LOGGER.info(f"  Including {len(image_payloads)} images (base64 upload)")

        payload = {"product": product_payload}

        self._rate_limit()
        update_url = f"{self.base_url}/products/{shopify_product_id}.json"
        response = self._request(
            'PUT',
            update_url,
            json=payload,
        )

        if response is None:
            LOGGER.error(f"Failed to update product {shopify_product_id}")
            return None

        self._log_rate_limit(response)

        data = response.json()
        if 'errors' in data:
            LOGGER.error(f"Shopify error updating product {product_data['sku']} (ID: {shopify_product_id}): {data['errors']}")
            return None

        updated = data.get('product')
        if updated:
            updated_images = updated.get('images', [])
            LOGGER.info(
                f"  Updated in Shopify: ID={shopify_product_id}, "
                f"images={len(updated_images)}, "
                f"status={updated.get('status')}"
            )
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
        deactivate_url = f"{self.base_url}/products/{shopify_product_id}.json"
        LOGGER.debug(f"PUT {deactivate_url}")
        LOGGER.debug(f"Payload: {payload}")
        response = self._request(
            'PUT',
            deactivate_url,
            json=payload,
        )

        if response is None:
            LOGGER.error(f"Failed to deactivate product {shopify_product_id}")
            return False

        LOGGER.debug(f"Response status: {response.status_code}")
        self._log_rate_limit(response)
        LOGGER.info(f"Deactivated product in Shopify (ID: {shopify_product_id})")
        return True

    def _get_location_id(self) -> Optional[int]:
        """Fetch and cache the primary location ID."""
        if self._location_id is not None:
            return self._location_id

        self._rate_limit()
        locations_resp = self._request(
            'GET', f"{self.base_url}/locations.json"
        )
        if locations_resp is None:
            LOGGER.warning("Could not fetch locations.")
            return None

        locations = locations_resp.json().get('locations', [])
        if not locations:
            LOGGER.warning("No locations found.")
            return None

        self._location_id = locations[0]['id']
        LOGGER.debug(f"Cached location_id={self._location_id}")
        return self._location_id

    def _build_metafields(self, product_data: Dict) -> List[Dict]:
        """Build metafields array from product data."""
        metafields = []

        brand = product_data.get('brand', '').strip()
        if brand:
            metafields.append({
                "namespace": "wimood",
                "key": "brand",
                "value": brand,
                "type": "single_line_text_field",
            })

        ean = product_data.get('ean', '').strip()
        if ean:
            metafields.append({
                "namespace": "wimood",
                "key": "ean",
                "value": ean,
                "type": "single_line_text_field",
            })

        msrp = product_data.get('msrp', '').strip() if isinstance(product_data.get('msrp'), str) else str(product_data.get('msrp', ''))
        if msrp and msrp != '0.00':
            metafields.append({
                "namespace": "wimood",
                "key": "msrp",
                "value": msrp,
                "type": "single_line_text_field",
            })

        specs = product_data.get('specs', {})
        if specs:
            metafields.append({
                "namespace": "wimood",
                "key": "specs",
                "value": json.dumps(specs, ensure_ascii=False),
                "type": "json",
            })

        return metafields

    def _build_image_payloads(self, product_data: Dict) -> List[Dict]:
        """Build image payloads from local files using base64 encoding."""
        local_images = product_data.get('local_images', [])
        if not local_images:
            return []

        payloads = []
        for filepath in local_images[:10]:
            base64_data = ImageDownloader.encode_image_base64(filepath)
            if base64_data:
                payloads.append({"attachment": base64_data})
            else:
                LOGGER.warning(f"Failed to encode image: {filepath}")
        return payloads

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

        location_id = self._get_location_id()
        if not location_id:
            LOGGER.warning("No location_id available for inventory update.")
            return

        LOGGER.debug(f"Setting inventory: location_id={location_id}, inventory_item_id={inventory_item_id}, quantity={quantity}")

        payload = {
            "location_id": location_id,
            "inventory_item_id": inventory_item_id,
            "available": quantity,
        }

        self._rate_limit()
        inv_url = f"{self.base_url}/inventory_levels/set.json"
        LOGGER.debug(f"POST {inv_url}")
        LOGGER.debug(f"Payload: {payload}")
        response = self._request(
            'POST',
            inv_url,
            json=payload,
        )

        if response is None:
            LOGGER.warning(f"Failed to set inventory for item {inventory_item_id}")
        elif response:
            LOGGER.debug(f"Inventory set response status: {response.status_code}")
            self._log_rate_limit(response)
