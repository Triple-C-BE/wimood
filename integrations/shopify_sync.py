import logging
from typing import List, Dict

LOGGER = logging.getLogger('shopify_sync')


def sync_products(wimood_products: List[Dict], shopify_api) -> Dict[str, int]:
    """
    Orchestrates the full product sync from Wimood to Shopify.

    1. Fetches all Shopify products managed by this sync (filtered by vendor tag)
    2. Builds a SKU->product map for Shopify products
    3. Creates new products, updates existing ones, deactivates removed ones

    Args:
        wimood_products: List of product dicts from Wimood API
            (keys: sku, title, price, stock)
        shopify_api: ShopifyAPI instance

    Returns:
        Dict with counts: created, updated, deactivated, skipped, errors
    """
    results = {'created': 0, 'updated': 0, 'deactivated': 0, 'skipped': 0, 'errors': 0}

    # 1. Fetch all existing Shopify products managed by this sync
    LOGGER.info("Fetching existing Shopify products...")
    shopify_products = shopify_api.get_all_products()

    # 2. Build SKU -> Shopify product lookup
    shopify_sku_map = {}
    for product in shopify_products:
        for variant in product.get('variants', []):
            sku = variant.get('sku', '')
            if sku:
                shopify_sku_map[sku] = product
                break  # Use first variant's SKU

    LOGGER.info(f"Found {len(shopify_sku_map)} existing products in Shopify by SKU.")

    # 3. Build set of Wimood SKUs for deactivation check
    wimood_skus = set()

    # 4. Process each Wimood product
    for product_data in wimood_products:
        sku = product_data.get('sku', '')
        if not sku:
            LOGGER.warning(f"Skipping product with empty SKU: {product_data.get('title', 'unknown')}")
            results['skipped'] += 1
            continue

        wimood_skus.add(sku)

        if sku in shopify_sku_map:
            # Product exists — check if update is needed
            existing = shopify_sku_map[sku]
            if _needs_update(existing, product_data):
                result = shopify_api.update_product(existing['id'], product_data)
                if result:
                    results['updated'] += 1
                else:
                    results['errors'] += 1
            else:
                results['skipped'] += 1
        else:
            # New product — create it
            result = shopify_api.create_product(product_data)
            if result:
                results['created'] += 1
            else:
                results['errors'] += 1

    # 5. Deactivate products no longer in Wimood feed
    for sku, shopify_product in shopify_sku_map.items():
        if sku not in wimood_skus:
            # Only deactivate active products
            if shopify_product.get('status') == 'active':
                success = shopify_api.deactivate_product(shopify_product['id'])
                if success:
                    results['deactivated'] += 1
                else:
                    results['errors'] += 1

    LOGGER.info(
        f"Sync complete — Created: {results['created']}, Updated: {results['updated']}, "
        f"Deactivated: {results['deactivated']}, Skipped: {results['skipped']}, "
        f"Errors: {results['errors']}"
    )

    return results


def _needs_update(shopify_product: Dict, wimood_product: Dict) -> bool:
    """
    Compare Shopify product with Wimood data to determine if an update is needed.
    Checks title, price, and stock status.
    """
    # Check title
    if shopify_product.get('title', '') != wimood_product.get('title', ''):
        return True

    # Check price on first variant
    variants = shopify_product.get('variants', [])
    if variants:
        shopify_price = str(variants[0].get('price', '0.00'))
        wimood_price = str(wimood_product.get('price', '0.00'))
        if shopify_price != wimood_price:
            return True

    # Check if product is not active (should be reactivated)
    if shopify_product.get('status') != 'active':
        return True

    return False
