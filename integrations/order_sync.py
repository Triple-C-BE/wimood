import logging
import re
from typing import Dict

LOGGER = logging.getLogger('order_sync')


def map_shopify_address_to_wimood(shipping_address: Dict) -> Dict:
    """
    Map a Shopify shipping address to Wimood customer_address format.

    Shopify provides address1 (street + house number) and address2 (optional addition).
    Wimood expects separate street and housenumber fields.
    """
    address1 = shipping_address.get('address1', '') or ''
    address2 = shipping_address.get('address2', '') or ''

    # Try to split address1 into street name and house number
    # Common Dutch format: "Streetname 123" or "Streetname 123a"
    street = address1
    housenumber = address2

    match = re.match(r'^(.+?)\s+(\d+\S*)$', address1)
    if match:
        street = match.group(1)
        housenumber = match.group(2)
        if address2:
            housenumber = f"{housenumber} {address2}"

    return {
        "company": shipping_address.get('company', '') or '',
        "contact_person": f"{shipping_address.get('first_name', '')} {shipping_address.get('last_name', '')}".strip(),
        "street": street,
        "housenumber": housenumber,
        "postcode": shipping_address.get('zip', '') or '',
        "city": shipping_address.get('city', '') or '',
        "country": shipping_address.get('country_code', '') or '',
    }


def sync_orders(shopify_api, order_store, wimood_api=None, product_mapping=None) -> Dict[str, int]:
    """
    Orchestrates the full dropship order sync flow:

    1. Fetch unfulfilled orders from Shopify -> store new ones in DB
    2. Process all active orders: submit to Wimood if needed, poll for status updates

    Args:
        shopify_api: ShopifyAPI instance
        order_store: OrderStore instance
        wimood_api: WimoodAPI instance (required for dropship submission/polling)
        product_mapping: ProductMapping instance (required for SKU -> product_id lookup)

    Returns:
        Dict with counts: new_orders, submitted, fulfilled, poll_checked, errors
    """
    results = {
        'new_orders': 0,
        'submitted': 0,
        'in_progress': 0,
        'fulfilled': 0,
        'delivered': 0,
        'cancelled': 0,
        'poll_checked': 0,
        'errors': 0,
    }

    # --- Step 1: Fetch & store new unfulfilled Shopify orders (silently) ---
    LOGGER.info("Fetching unfulfilled orders from Shopify...")
    shopify_orders = shopify_api.get_unfulfilled_orders()

    existing_ids = {o['shopify_order_id'] for o in order_store.get_all_orders()}

    for order in shopify_orders:
        order_id = order.get('id')
        order_number = str(order.get('order_number', order.get('name', '')))
        fulfillment_status = order.get('fulfillment_status') or 'unfulfilled'
        created_at = order.get('created_at', '')

        if order_id not in existing_ids:
            results['new_orders'] += 1

        order_store.upsert_order({
            'shopify_order_id': order_id,
            'order_number': order_number,
            'fulfillment_status': fulfillment_status,
            'created_at': created_at,
        })

    # --- Step 2: Process all active orders in a single pass ---
    active_orders = order_store.get_active_orders()

    if not active_orders:
        LOGGER.info("No active orders to process.")
    else:
        LOGGER.info(f"Processing {len(active_orders)} order(s)...")

        for idx, stored_order in enumerate(active_orders, 1):
            order_id = stored_order['shopify_order_id']
            order_number = stored_order['order_number']
            local_status = stored_order['fulfillment_status']
            is_submitted = stored_order['dropship_submitted']
            wimood_order_id = stored_order.get('wimood_order_id') or 0
            wimood_status = stored_order.get('wimood_status', '')
            is_new = order_id not in existing_ids

            # Build the order header line
            parts = [f"Order #{order_number}", f"ID={order_id}", f"Status={local_status}"]
            if wimood_order_id > 0:
                parts.append(f"Wimood={wimood_order_id}")
                if wimood_status:
                    parts.append(f"WimoodStatus={wimood_status}")

            LOGGER.info(f"[{idx}/{len(active_orders)}] {' | '.join(parts)}")

            # --- Action: New order ---
            if is_new:
                LOGGER.info(f"  -> NEW")

            # --- Action: Needs submission to Wimood ---
            if not is_submitted and wimood_api and product_mapping:
                _submit_order(shopify_api, order_store, wimood_api, product_mapping, stored_order, results)
                continue

            # --- Action: Needs polling from Wimood ---
            if is_submitted and wimood_order_id > 0 and wimood_api:
                _poll_order(shopify_api, order_store, wimood_api, stored_order, results)
                continue

            if not is_new:
                LOGGER.info(f"  -> SKIP (no action needed)")

    LOGGER.info(
        f"Order sync complete — New: {results['new_orders']}, Submitted: {results['submitted']}, "
        f"In Progress: {results['in_progress']}, Fulfilled: {results['fulfilled']}, "
        f"Delivered: {results['delivered']}, Cancelled: {results['cancelled']}, "
        f"Polled: {results['poll_checked']}, Errors: {results['errors']}"
    )

    return results


def _submit_order(shopify_api, order_store, wimood_api, product_mapping, stored_order, results):
    """Submit a single order to Wimood for dropshipping."""
    order_id = stored_order['shopify_order_id']
    order_number = stored_order['order_number']

    try:
        shopify_order = shopify_api.get_order(order_id)
        if shopify_order is None:
            LOGGER.info(f"  -> SKIP (not found in Shopify)")
            results['errors'] += 1
            return

        # Match line item SKUs to Wimood product IDs
        wimood_items = []
        for line_item in shopify_order.get('line_items', []):
            sku = line_item.get('sku', '').strip()
            if not sku:
                continue

            mapping = product_mapping.get_by_sku(sku)
            if mapping is None:
                LOGGER.debug(f"  SKU {sku} not in product mapping (non-Wimood product)")
                continue

            wimood_items.append({
                'product_id': mapping['wimood_product_id'],
                'quantity': line_item.get('quantity', 1),
            })

        if not wimood_items:
            LOGGER.info(f"  -> SKIP (no Wimood products)")
            order_store.mark_submitted(order_id, 0)
            return

        shipping_address = shopify_order.get('shipping_address')
        if not shipping_address:
            LOGGER.info(f"  -> SKIP (no shipping address)")
            results['errors'] += 1
            return

        customer_address = map_shopify_address_to_wimood(shipping_address)

        wimood_order_data = {
            'reference': order_number,
            'customer_address': customer_address,
            'items': wimood_items,
        }

        wimood_order_id = wimood_api.create_order(wimood_order_data)

        if wimood_order_id is not None:
            order_store.mark_submitted(order_id, wimood_order_id)
            results['submitted'] += 1
            LOGGER.info(f"  -> SUBMITTED (Wimood ID: {wimood_order_id})")
        else:
            LOGGER.error(f"  -> ERROR (failed to submit to Wimood)")
            results['errors'] += 1

    except Exception as e:
        LOGGER.error(f"  -> ERROR ({e})")
        results['errors'] += 1


def _poll_order(shopify_api, order_store, wimood_api, stored_order, results):
    """Poll Wimood for a single order's status and act on changes."""
    order_id = stored_order['shopify_order_id']
    order_number = stored_order['order_number']
    wimood_order_id = stored_order['wimood_order_id']
    local_status = stored_order['fulfillment_status']

    try:
        status_data = wimood_api.get_order_status(wimood_order_id)
        results['poll_checked'] += 1

        if status_data is None:
            LOGGER.info(f"  -> ERROR (could not get Wimood status)")
            results['errors'] += 1
            return

        wimood_status = status_data.get('status', '')
        track_and_trace = status_data.get('track_and_trace', {}) or {}
        tracking_code = track_and_trace.get('code', '') or ''
        tracking_url = track_and_trace.get('url', '') or ''

        old_status = stored_order.get('wimood_status', '')
        order_store.update_wimood_status(order_id, wimood_status, tracking_code, tracking_url)

        # Cancelled -> cancel in Shopify
        if wimood_status == 'cancelled':
            success = shopify_api.cancel_order(order_id)
            if success:
                order_store.update_fulfillment(order_id, 'cancelled')
                results['cancelled'] += 1
                LOGGER.info(f"  -> CANCELLED in Shopify")
            else:
                LOGGER.error(f"  -> ERROR (failed to cancel in Shopify)")
                results['errors'] += 1
            return

        # Pending -> mark in_progress in Shopify (only once)
        if wimood_status == 'pending' and local_status != 'in_progress':
            success = shopify_api.mark_fulfillment_in_progress(order_id)
            if success:
                order_store.update_fulfillment(order_id, 'in_progress')
                results['in_progress'] += 1
                LOGGER.info(f"  -> IN_PROGRESS (Wimood: {old_status or '(none)'} -> {wimood_status})")
            else:
                LOGGER.error(f"  -> ERROR (failed to mark in_progress in Shopify)")
                results['errors'] += 1
            return

        # Shipped -> create fulfillment with tracking (only once)
        if wimood_status == 'shipped' and local_status != 'fulfilled':
            success = shopify_api.create_fulfillment(order_id, tracking_code, tracking_url)
            if success:
                order_store.update_fulfillment(order_id, 'fulfilled', tracking_code, tracking_url)
                results['fulfilled'] += 1
                LOGGER.info(f"  -> FULFILLED (tracking: {tracking_code or 'none'})")
            else:
                LOGGER.error(f"  -> ERROR (failed to create fulfillment in Shopify)")
                results['errors'] += 1
            return

        # Delivered -> mark as delivered in Shopify and locally (stops polling)
        if wimood_status == 'delivered' and local_status != 'delivered':
            success = shopify_api.mark_order_delivered(order_id)
            if success:
                order_store.update_fulfillment(order_id, 'delivered')
                results['delivered'] += 1
                LOGGER.info(f"  -> DELIVERED in Shopify (stop polling)")
            else:
                LOGGER.error(f"  -> ERROR (failed to mark delivered in Shopify)")
                results['errors'] += 1
            return

        # No action needed
        if wimood_status != old_status:
            LOGGER.info(f"  -> SKIP (Wimood: {old_status or '(none)'} -> {wimood_status})")
        else:
            LOGGER.info(f"  -> SKIP (no changes)")

    except Exception as e:
        LOGGER.error(f"  -> ERROR ({e})")
        results['errors'] += 1
