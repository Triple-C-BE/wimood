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
    2. Submit unsubmitted orders to Wimood for dropshipping
    3. Poll Wimood for status updates on submitted orders
    4. When Wimood ships -> create fulfillment in Shopify

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
        'fulfilled': 0,
        'cancelled': 0,
        'poll_checked': 0,
        'errors': 0,
    }

    # --- Step 1: Fetch & store new unfulfilled Shopify orders ---
    LOGGER.info("Fetching unfulfilled orders from Shopify...")
    shopify_orders = shopify_api.get_unfulfilled_orders()

    existing_ids = {o['shopify_order_id'] for o in order_store.get_all_orders()}

    for order in shopify_orders:
        order_id = order.get('id')
        order_number = str(order.get('order_number', order.get('name', '')))
        fulfillment_status = order.get('fulfillment_status') or 'unfulfilled'
        created_at = order.get('created_at', '')

        order_data = {
            'shopify_order_id': order_id,
            'order_number': order_number,
            'fulfillment_status': fulfillment_status,
            'created_at': created_at,
        }

        if order_id not in existing_ids:
            results['new_orders'] += 1
            LOGGER.info(f"New order: #{order_number} (ID={order_id})")

        order_store.upsert_order(order_data)

    # --- Step 2: Submit unsubmitted orders to Wimood ---
    if wimood_api and product_mapping:
        _submit_orders_to_wimood(shopify_api, order_store, wimood_api, product_mapping, results)
    else:
        LOGGER.debug("Dropship submission skipped (wimood_api or product_mapping not provided)")

    # --- Step 3: Poll Wimood for status updates & fulfill in Shopify ---
    if wimood_api:
        _poll_wimood_orders(shopify_api, order_store, wimood_api, results)
    else:
        LOGGER.debug("Wimood polling skipped (wimood_api not provided)")

    LOGGER.info(
        f"Order sync complete — New: {results['new_orders']}, Submitted: {results['submitted']}, "
        f"Fulfilled: {results['fulfilled']}, Cancelled: {results['cancelled']}, "
        f"Polled: {results['poll_checked']}, Errors: {results['errors']}"
    )

    return results


def _submit_orders_to_wimood(shopify_api, order_store, wimood_api, product_mapping, results):
    """Submit unsubmitted orders to Wimood for dropshipping."""
    unsubmitted = order_store.get_unsubmitted_orders()
    if not unsubmitted:
        LOGGER.info("No unsubmitted orders to send to Wimood.")
        return

    LOGGER.info(f"Processing {len(unsubmitted)} unsubmitted order(s) for Wimood dropship...")

    for stored_order in unsubmitted:
        order_id = stored_order['shopify_order_id']
        order_number = stored_order['order_number']

        try:
            # Fetch full order from Shopify to get line_items and shipping address
            shopify_order = shopify_api.get_order(order_id)
            if shopify_order is None:
                LOGGER.warning(f"Order #{order_number} (ID={order_id}) not found in Shopify, skipping")
                results['errors'] += 1
                continue

            # Match line item SKUs to Wimood product IDs
            wimood_items = []
            for line_item in shopify_order.get('line_items', []):
                sku = line_item.get('sku', '').strip()
                if not sku:
                    continue

                mapping = product_mapping.get_by_sku(sku)
                if mapping is None:
                    LOGGER.debug(f"  SKU {sku} not in product mapping, skipping (non-Wimood product)")
                    continue

                wimood_items.append({
                    'product_id': mapping['wimood_product_id'],
                    'quantity': line_item.get('quantity', 1),
                })

            if not wimood_items:
                LOGGER.info(f"Order #{order_number} has no Wimood products, skipping dropship submission")
                # Mark as submitted with wimood_order_id=0 so we don't keep re-checking
                order_store.mark_submitted(order_id, 0)
                continue

            # Map shipping address
            shipping_address = shopify_order.get('shipping_address')
            if not shipping_address:
                LOGGER.warning(f"Order #{order_number} has no shipping address, skipping")
                results['errors'] += 1
                continue

            customer_address = map_shopify_address_to_wimood(shipping_address)

            # Submit to Wimood
            wimood_order_data = {
                'reference': order_number,
                'customer_address': customer_address,
                'items': wimood_items,
            }

            wimood_order_id = wimood_api.create_order(wimood_order_data)

            if wimood_order_id is not None:
                order_store.mark_submitted(order_id, wimood_order_id)
                results['submitted'] += 1
                LOGGER.info(f"Order #{order_number} submitted to Wimood (Wimood ID: {wimood_order_id})")
            else:
                LOGGER.error(f"Failed to submit order #{order_number} to Wimood")
                results['errors'] += 1

        except Exception as e:
            LOGGER.error(f"Error processing order #{order_number} for dropship: {e}")
            results['errors'] += 1


def _poll_wimood_orders(shopify_api, order_store, wimood_api, results):
    """Poll Wimood for order status updates and create Shopify fulfillments when shipped."""
    submitted = order_store.get_submitted_unfulfilled()

    # Filter out orders that were marked submitted but have no real Wimood order (wimood_order_id=0)
    trackable = [o for o in submitted if o.get('wimood_order_id') and o['wimood_order_id'] > 0]

    if not trackable:
        LOGGER.info("No submitted orders to poll for status updates.")
        return

    LOGGER.info(f"Polling {len(trackable)} submitted order(s) for Wimood status updates...")

    for stored_order in trackable:
        order_id = stored_order['shopify_order_id']
        order_number = stored_order['order_number']
        wimood_order_id = stored_order['wimood_order_id']

        try:
            status_data = wimood_api.get_order_status(wimood_order_id)
            results['poll_checked'] += 1

            if status_data is None:
                LOGGER.warning(f"Could not get status for Wimood order {wimood_order_id}")
                results['errors'] += 1
                continue

            wimood_status = status_data.get('status', '')
            track_and_trace = status_data.get('track_and_trace', {}) or {}
            tracking_code = track_and_trace.get('code', '') or ''
            tracking_url = track_and_trace.get('url', '') or ''

            # Update Wimood status in our store
            old_status = stored_order.get('wimood_status', '')
            if wimood_status != old_status:
                LOGGER.info(f"Order #{order_number} Wimood status: {old_status or '(none)'} -> {wimood_status}")

            order_store.update_wimood_status(order_id, wimood_status, tracking_code, tracking_url)

            # If Wimood cancelled the order -> cancel in Shopify too
            if wimood_status == 'cancelled':
                LOGGER.info(f"Order #{order_number} cancelled by Wimood — cancelling in Shopify")

                success = shopify_api.cancel_order(order_id)
                if success:
                    order_store.update_fulfillment(order_id, 'cancelled')
                    results['cancelled'] += 1
                    LOGGER.info(f"Order #{order_number} cancelled in Shopify")
                else:
                    LOGGER.error(f"Failed to cancel order #{order_number} in Shopify")
                    results['errors'] += 1
                continue

            # If we have tracking info, the order is shipped -> create Shopify fulfillment
            if tracking_code:
                LOGGER.info(f"Order #{order_number} has tracking: {tracking_code} — creating Shopify fulfillment")

                success = shopify_api.create_fulfillment(order_id, tracking_code, tracking_url)
                if success:
                    order_store.update_fulfillment(order_id, 'fulfilled', tracking_code, tracking_url)
                    results['fulfilled'] += 1
                    LOGGER.info(f"Order #{order_number} fulfilled in Shopify")
                else:
                    LOGGER.error(f"Failed to create Shopify fulfillment for order #{order_number}")
                    results['errors'] += 1

        except Exception as e:
            LOGGER.error(f"Error polling Wimood order {wimood_order_id} (Shopify #{order_number}): {e}")
            results['errors'] += 1
