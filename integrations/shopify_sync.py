import logging
from typing import Dict, List

LOGGER = logging.getLogger('shopify_sync')


def sync_products(wimood_products: List[Dict], shopify_api, test_mode: bool = False,
                   scraper=None, scrape_cache=None, product_mapping=None,
                   scrape_mode: str = "new_only") -> Dict[str, int]:
    """
    Orchestrates the full product sync from Wimood to Shopify.

    Args:
        wimood_products: List of product dicts from Wimood API
        shopify_api: ShopifyAPI instance
        test_mode: If True, log verbose per-product output at INFO level
        scraper: Optional WimoodScraper instance for enrichment
        scrape_cache: Optional ScrapeCache instance
        product_mapping: Optional ProductMapping instance
        scrape_mode: "new_only" = only scrape products not in mapping (default),
                     "full" = scrape all products (respects cache staleness)

    Returns:
        Dict with counts: created, updated, deactivated, skipped, errors
    """
    results = {'created': 0, 'updated': 0, 'deactivated': 0, 'skipped': 0, 'errors': 0}

    # 0. Enrich products via scraping (if enabled)
    if scraper:
        enrich_stats = {'scraped': 0, 'cached': 0, 'skipped': 0, 'failed': 0}
        LOGGER.info(f"Enriching products via web scraping (mode={scrape_mode})...")

        for product in wimood_products:
            sku = product.get('sku', '')
            if not sku:
                continue

            # In "new_only" mode, skip products that already exist in the mapping
            if scrape_mode == "new_only" and product_mapping:
                wimood_id = product.get('product_id', '')
                if wimood_id and product_mapping.get_shopify_id(wimood_id):
                    enrich_stats['skipped'] += 1
                    continue

            # Check cache first
            if scrape_cache and not scrape_cache.is_stale(sku):
                cached_data = scrape_cache.get(sku)
                if cached_data:
                    product.update({
                        'body_html': cached_data.get('description', ''),
                        'images': cached_data.get('images', []),
                        'local_images': cached_data.get('local_images', []),
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
                    'local_images': scraped.get('local_images', []),
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
            f"Cached: {enrich_stats['cached']}, Skipped: {enrich_stats['skipped']}, "
            f"Failed: {enrich_stats['failed']}"
        )

    # 1. Fetch all existing Shopify products managed by this sync
    LOGGER.info("Fetching existing Shopify products...")
    shopify_products = shopify_api.get_all_products()

    # 2. Build SKU -> Shopify product lookup and ID -> product lookup
    shopify_sku_map = {}
    shopify_id_map = {}
    for product in shopify_products:
        shopify_id_map[product['id']] = product
        for variant in product.get('variants', []):
            sku = variant.get('sku', '')
            if sku:
                shopify_sku_map[sku] = product
                break  # Use first variant's SKU

    LOGGER.info(f"Found {len(shopify_sku_map)} existing products in Shopify by SKU.")

    # 3. Build set of Wimood SKUs for deactivation check
    wimood_skus = set()

    # 4. Process each Wimood product
    LOGGER.info("--------------------------------------------------------------------")
    LOGGER.info("Processing products...")
    total = len(wimood_products)
    for idx, product_data in enumerate(wimood_products, 1):
        sku = product_data.get('sku', '')
        title = product_data.get('title', '')
        price = product_data.get('price', '0.00')
        stock = product_data.get('stock', '0')
        has_images = len(product_data.get('local_images', product_data.get('images', [])))
        has_desc = bool(product_data.get('body_html', ''))

        LOGGER.info(
            f"[{idx}/{total}] SKU={sku} | {title} | "
            f"Price={price} | Stock={stock} | "
            f"Images={has_images} | Desc={'yes' if has_desc else 'no'}"
        )

        if not sku:
            LOGGER.warning("  -> SKIP (empty SKU)")
            results['skipped'] += 1
            continue

        wimood_skus.add(sku)

        # Find existing product: try mapping first, then SKU
        existing = None
        wimood_product_id = product_data.get('product_id', '')

        if product_mapping and wimood_product_id:
            shopify_id = product_mapping.get_shopify_id(wimood_product_id)
            if shopify_id:
                existing = shopify_id_map.get(shopify_id)

        if not existing and sku in shopify_sku_map:
            existing = shopify_sku_map[sku]

        if existing:
            # Product exists — check if update is needed
            if _needs_update(existing, product_data):
                changes = _describe_changes(existing, product_data)
                LOGGER.info(f"  -> UPDATE ({changes})")
                result = shopify_api.update_product(existing['id'], product_data, existing_shopify_product=existing)
                if result:
                    results['updated'] += 1
                    # Update mapping if not already set
                    if product_mapping and wimood_product_id:
                        product_mapping.set_mapping(wimood_product_id, existing['id'], sku)
                else:
                    results['errors'] += 1
            else:
                LOGGER.info("  -> SKIP (no changes)")
                results['skipped'] += 1
                # Ensure mapping exists for skipped products too
                if product_mapping and wimood_product_id:
                    product_mapping.set_mapping(wimood_product_id, existing['id'], sku)

                # Backfill cost for skipped products if not yet synced
                if product_mapping and not product_mapping.is_cost_synced(sku):
                    cost = product_data.get('wholesale_price', '')
                    if shopify_api.set_cost_for_product(existing, cost):
                        product_mapping.mark_cost_synced(sku)
        else:
            # New product — create it
            LOGGER.info("  -> CREATE")
            result = shopify_api.create_product(product_data)
            if result:
                results['created'] += 1
                if product_mapping:
                    product_mapping.mark_cost_synced(sku)
            else:
                results['errors'] += 1

    # 5. Deactivate products no longer in Wimood feed
    for sku, shopify_product in shopify_sku_map.items():
        if sku not in wimood_skus:
            # Only deactivate active products
            if shopify_product.get('status') == 'active':
                LOGGER.info(f"DEACTIVATE SKU={sku} (Shopify ID={shopify_product['id']}) — removed from Wimood feed")
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


def _normalize_price(value) -> str:
    """Normalize a price to 2 decimal places for consistent comparison."""
    try:
        return f"{float(value):.2f}"
    except (ValueError, TypeError):
        return "0.00"


def _describe_changes(shopify_product: Dict, wimood_product: Dict) -> str:
    """Build a human-readable summary of what changed between Shopify and Wimood data."""
    changes = []

    shopify_title = shopify_product.get('title', '')
    wimood_title = wimood_product.get('title', '')
    if shopify_title != wimood_title:
        changes.append("title changed")

    variants = shopify_product.get('variants', [])
    if variants:
        shopify_price = _normalize_price(variants[0].get('price', '0.00'))
        wimood_price = _normalize_price(wimood_product.get('price', '0.00'))
        if shopify_price != wimood_price:
            changes.append(f"price changed: {shopify_price} -> {wimood_price}")

    if shopify_product.get('status') != 'active':
        changes.append(f"status: {shopify_product.get('status')} -> active")

    shopify_body = shopify_product.get('body_html', '') or ''
    wimood_body = wimood_product.get('body_html', '')
    if wimood_body and not shopify_body.strip():
        changes.append("adding description")

    wimood_images = wimood_product.get('local_images', wimood_product.get('images', []))
    shopify_images = shopify_product.get('images', [])
    if wimood_images and len(shopify_images) < len(wimood_images):
        changes.append(f"images: {len(shopify_images)} -> {len(wimood_images)}")

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

    # Check price on first variant (normalize to 2 decimal places)
    variants = shopify_product.get('variants', [])
    if variants:
        shopify_price = _normalize_price(variants[0].get('price', '0.00'))
        wimood_price = _normalize_price(wimood_product.get('price', '0.00'))
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
    wimood_images = wimood_product.get('local_images', wimood_product.get('images', []))
    shopify_images = shopify_product.get('images', [])
    if wimood_images and len(shopify_images) < len(wimood_images):
        LOGGER.debug(f"[{sku}] Shopify has {len(shopify_images)} images, enriched data has {len(wimood_images)}")
        return True

    LOGGER.debug(f"[{sku}] No differences detected")
    return False
