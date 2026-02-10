import logging
from typing import Dict, List

LOGGER = logging.getLogger('shopify_sync')


def sync_products(wimood_products: List[Dict], shopify_api, test_mode: bool = False,
                   scraper=None, scrape_cache=None) -> Dict[str, int]:
    """
    Orchestrates the full product sync from Wimood to Shopify.

    1. Optionally enriches products via web scraping
    2. Fetches all Shopify products managed by this sync (filtered by vendor tag)
    3. Builds a SKU->product map for Shopify products
    4. Creates new products, updates existing ones, deactivates removed ones

    Args:
        wimood_products: List of product dicts from Wimood API
        shopify_api: ShopifyAPI instance
        test_mode: If True, log verbose per-product output at INFO level
        scraper: Optional WimoodScraper instance for enrichment
        scrape_cache: Optional ScrapeCache instance

    Returns:
        Dict with counts: created, updated, deactivated, skipped, errors
    """
    results = {'created': 0, 'updated': 0, 'deactivated': 0, 'skipped': 0, 'errors': 0}

    # 0. Enrich products via scraping (if enabled)
    if scraper:
        enrich_stats = {'scraped': 0, 'cached': 0, 'failed': 0}
        LOGGER.info("Enriching products via web scraping...")

        for product in wimood_products:
            sku = product.get('sku', '')
            if not sku:
                continue

            # Check cache first
            if scrape_cache and not scrape_cache.is_stale(sku):
                cached_data = scrape_cache.get(sku)
                if cached_data:
                    product.update({
                        'body_html': cached_data.get('description', ''),
                        'images': cached_data.get('images', []),
                        'specs': cached_data.get('specs', {}),
                    })
                    enrich_stats['cached'] += 1
                    continue

            # Scrape the product page
            scraped = scraper.scrape_product(product)
            if scraped:
                product.update({
                    'body_html': scraped.get('description', ''),
                    'images': scraped.get('images', []),
                    'specs': scraped.get('specs', {}),
                })
                if scrape_cache:
                    scrape_cache.set(sku, scraped)
                enrich_stats['scraped'] += 1
            else:
                enrich_stats['failed'] += 1

        if scrape_cache:
            scrape_cache.save()

        LOGGER.info(
            f"Enrichment complete — Scraped: {enrich_stats['scraped']}, "
            f"Cached: {enrich_stats['cached']}, Failed: {enrich_stats['failed']}"
        )

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
    total = len(wimood_products)
    for idx, product_data in enumerate(wimood_products, 1):
        sku = product_data.get('sku', '')
        title = product_data.get('title', '')
        price = product_data.get('price', '0.00')
        stock = product_data.get('stock', '0')

        if test_mode:
            LOGGER.info(f"[{idx}/{total}] SKU={sku} | Title={title} | Price={price} | Stock={stock}")

        LOGGER.debug(f"Processing product: SKU={sku}, title={title}, price={price}, stock={stock}")

        if not sku:
            LOGGER.warning(f"Skipping product with empty SKU: {title or 'unknown'}")
            results['skipped'] += 1
            continue

        wimood_skus.add(sku)

        if sku in shopify_sku_map:
            # Product exists — check if update is needed
            existing = shopify_sku_map[sku]
            if _needs_update(existing, product_data):
                # Build a descriptive change summary for test mode
                if test_mode:
                    changes = _describe_changes(existing, product_data)
                    LOGGER.info(f"  -> UPDATE ({changes})")

                LOGGER.debug(f"Action: UPDATE for SKU={sku} (Shopify ID: {existing['id']})")
                result = shopify_api.update_product(existing['id'], product_data)
                if result:
                    results['updated'] += 1
                else:
                    results['errors'] += 1
            else:
                if test_mode:
                    LOGGER.info("  -> SKIP (no changes)")
                LOGGER.debug(f"Action: SKIP for SKU={sku} (no changes detected)")
                results['skipped'] += 1
        else:
            # New product — create it
            if test_mode:
                LOGGER.info("  -> CREATE")
            LOGGER.debug(f"Action: CREATE for SKU={sku}")
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


def _describe_changes(shopify_product: Dict, wimood_product: Dict) -> str:
    """Build a human-readable summary of what changed between Shopify and Wimood data."""
    changes = []

    shopify_title = shopify_product.get('title', '')
    wimood_title = wimood_product.get('title', '')
    if shopify_title != wimood_title:
        changes.append("title changed")

    variants = shopify_product.get('variants', [])
    if variants:
        shopify_price = str(variants[0].get('price', '0.00'))
        wimood_price = str(wimood_product.get('price', '0.00'))
        if shopify_price != wimood_price:
            changes.append(f"price changed: {shopify_price} -> {wimood_price}")

    if shopify_product.get('status') != 'active':
        changes.append(f"status: {shopify_product.get('status')} -> active")

    return ', '.join(changes) if changes else 'unknown change'


def _needs_update(shopify_product: Dict, wimood_product: Dict) -> bool:
    """
    Compare Shopify product with Wimood data to determine if an update is needed.
    Checks title, price, and stock status.
    """
    sku = wimood_product.get('sku', '?')

    # Check title
    shopify_title = shopify_product.get('title', '')
    wimood_title = wimood_product.get('title', '')
    if shopify_title != wimood_title:
        LOGGER.debug(f"[{sku}] Title differs: Shopify='{shopify_title}' vs Wimood='{wimood_title}'")
        return True

    # Check price on first variant
    variants = shopify_product.get('variants', [])
    if variants:
        shopify_price = str(variants[0].get('price', '0.00'))
        wimood_price = str(wimood_product.get('price', '0.00'))
        if shopify_price != wimood_price:
            LOGGER.debug(f"[{sku}] Price differs: Shopify='{shopify_price}' vs Wimood='{wimood_price}'")
            return True

    # Check if product is not active (should be reactivated)
    if shopify_product.get('status') != 'active':
        LOGGER.debug(f"[{sku}] Status is '{shopify_product.get('status')}', needs reactivation")
        return True

    # Check if enriched description is available but Shopify product has none
    wimood_body = wimood_product.get('body_html', '')
    shopify_body = shopify_product.get('body_html', '') or ''
    if wimood_body and not shopify_body.strip():
        LOGGER.debug(f"[{sku}] Shopify product missing description, enriched data available")
        return True

    # Check if enriched images are available but Shopify product has fewer
    wimood_images = wimood_product.get('images', [])
    shopify_images = shopify_product.get('images', [])
    if wimood_images and len(shopify_images) < len(wimood_images):
        LOGGER.debug(f"[{sku}] Shopify has {len(shopify_images)} images, enriched data has {len(wimood_images)}")
        return True

    LOGGER.debug(f"[{sku}] No differences detected")
    return False
