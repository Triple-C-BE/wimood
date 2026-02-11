import json
from unittest.mock import MagicMock

from integrations.shopify_api import ShopifyAPI


class TestShopifyAPI:

    def _make_api(self, sample_env, mock_request_manager):
        return ShopifyAPI(sample_env, mock_request_manager)

    def test_init(self, sample_env, mock_request_manager):
        api = self._make_api(sample_env, mock_request_manager)
        assert 'test-store.myshopify.com' in api.base_url
        assert api.vendor_tag == 'Wimood_Sync'
        assert api._location_id is None

    def test_create_product_basic_payload(self, sample_env, mock_request_manager, sample_wimood_product):
        created_product = {'id': 123, 'variants': [{'id': 456, 'inventory_item_id': 789}]}
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {'product': created_product}
        mock_response.text = json.dumps({'product': created_product})
        mock_response.headers = {}

        # Calls: create product, locations, inventory set, cost set
        locations_resp = MagicMock()
        locations_resp.json.return_value = {'locations': [{'id': 111}]}
        locations_resp.headers = {}
        locations_resp.status_code = 200

        inv_resp = MagicMock()
        inv_resp.status_code = 200
        inv_resp.headers = {}

        cost_resp = MagicMock()
        cost_resp.status_code = 200
        cost_resp.headers = {}

        mock_request_manager.request.side_effect = [mock_response, locations_resp, inv_resp, cost_resp]

        api = self._make_api(sample_env, mock_request_manager)
        result = api.create_product(sample_wimood_product)

        assert result is not None
        assert result['id'] == 123

        # Verify the create call payload
        create_call = mock_request_manager.request.call_args_list[0]
        payload = create_call.kwargs.get('json') or create_call[1].get('json')
        product_payload = payload['product']
        assert product_payload['title'] == 'Test Bureaustoel Deluxe'
        assert product_payload['vendor'] == 'TestBrand'
        assert 'product_type' not in product_payload
        assert 'tags' not in product_payload
        assert product_payload['variants'][0]['sku'] == 'WM-TEST-001'
        assert product_payload['variants'][0]['barcode'] == '8712345678901'

    def test_create_product_with_enriched_data(self, sample_env, mock_request_manager, sample_enriched_product):
        created_product = {'id': 123, 'variants': [{'id': 456, 'inventory_item_id': 789}]}
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {'product': created_product}
        mock_response.text = json.dumps({'product': created_product})
        mock_response.headers = {}

        locations_resp = MagicMock()
        locations_resp.json.return_value = {'locations': [{'id': 111}]}
        locations_resp.headers = {}

        inv_resp = MagicMock()
        inv_resp.status_code = 200
        inv_resp.headers = {}

        cost_resp = MagicMock()
        cost_resp.status_code = 200
        cost_resp.headers = {}

        mock_request_manager.request.side_effect = [mock_response, locations_resp, inv_resp, cost_resp]

        api = self._make_api(sample_env, mock_request_manager)
        result = api.create_product(sample_enriched_product)

        assert result is not None

        create_call = mock_request_manager.request.call_args_list[0]
        payload = create_call.kwargs.get('json') or create_call[1].get('json')
        product_payload = payload['product']
        assert 'body_html' in product_payload
        assert 'bureaustoel' in product_payload['body_html']
        # local_images is empty in fixture, so no images in payload
        assert 'images' not in product_payload

    def test_create_product_failure(self, sample_env, mock_request_manager, sample_wimood_product):
        mock_request_manager.request.return_value = None

        api = self._make_api(sample_env, mock_request_manager)
        result = api.create_product(sample_wimood_product)
        assert result is None

    def test_update_product_with_enriched_data(self, sample_env, mock_request_manager,
                                               sample_enriched_product, sample_shopify_product):
        # PUT update (single call now — no separate GET or variant PUT)
        update_resp = MagicMock()
        update_resp.status_code = 200
        update_resp.json.return_value = {
            'product': {'id': 99999, 'variants': [{'id': 88888, 'inventory_item_id': 77777}]}
        }
        update_resp.text = '{}'
        update_resp.headers = {}

        # GET locations + POST inventory + PUT cost
        locations_resp = MagicMock()
        locations_resp.json.return_value = {'locations': [{'id': 111}]}
        locations_resp.headers = {}

        inv_resp = MagicMock()
        inv_resp.status_code = 200
        inv_resp.headers = {}

        cost_resp = MagicMock()
        cost_resp.status_code = 200
        cost_resp.headers = {}

        mock_request_manager.request.side_effect = [update_resp, locations_resp, inv_resp, cost_resp]

        api = self._make_api(sample_env, mock_request_manager)
        result = api.update_product(99999, sample_enriched_product,
                                    existing_shopify_product=sample_shopify_product)

        assert result is not None

        # The update call is the first one (no more GET fetch)
        update_call = mock_request_manager.request.call_args_list[0]
        payload = update_call.kwargs.get('json') or update_call[1].get('json')
        product_payload = payload['product']
        assert product_payload['vendor'] == 'TestBrand'
        assert 'body_html' in product_payload
        # Variant price is included inline
        assert product_payload['variants'][0]['price'] == '199.99'
        # local_images is empty in fixture, so no images in payload
        assert 'images' not in product_payload

    def test_location_id_cached(self, sample_env, mock_request_manager):
        api = self._make_api(sample_env, mock_request_manager)

        locations_resp = MagicMock()
        locations_resp.json.return_value = {'locations': [{'id': 111}]}
        locations_resp.headers = {}
        mock_request_manager.request.return_value = locations_resp

        loc1 = api._get_location_id()
        loc2 = api._get_location_id()

        assert loc1 == 111
        assert loc2 == 111
        # Should only call the API once
        assert mock_request_manager.request.call_count == 1

    def test_get_all_products_pagination(self, sample_env, mock_request_manager):
        page1_resp = MagicMock()
        page1_resp.status_code = 200
        page1_resp.json.return_value = {'products': [{'id': 1}, {'id': 2}]}
        page1_resp.headers = {'Link': '<https://test.myshopify.com/page2>; rel="next"'}

        page2_resp = MagicMock()
        page2_resp.status_code = 200
        page2_resp.json.return_value = {'products': [{'id': 3}]}
        page2_resp.headers = {}

        mock_request_manager.request.side_effect = [page1_resp, page2_resp]

        api = self._make_api(sample_env, mock_request_manager)
        products = api.get_all_products()

        assert len(products) == 3
        assert products[0]['id'] == 1
        assert products[2]['id'] == 3

    def test_check_connection_success(self, sample_env, mock_request_manager):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'shop': {'id': 1, 'name': 'Test Store'}}
        mock_resp.headers = {}
        mock_request_manager.request.return_value = mock_resp

        api = self._make_api(sample_env, mock_request_manager)
        assert api.check_connection() is True

    def test_check_connection_failure(self, sample_env, mock_request_manager):
        mock_request_manager.request.return_value = None

        api = self._make_api(sample_env, mock_request_manager)
        assert api.check_connection() is False

    def test_set_inventory_item_cost_error_response(self, sample_env, mock_request_manager):
        """Test that _set_inventory_item_cost detects errors in the response body."""
        error_resp = MagicMock()
        error_resp.status_code = 200
        error_resp.json.return_value = {'errors': 'Cost must be a number'}
        error_resp.headers = {}

        mock_request_manager.request.return_value = error_resp

        api = self._make_api(sample_env, mock_request_manager)
        result = api._set_inventory_item_cost(12345, '10.00')
        assert result is False

    def test_set_inventory_item_cost_success(self, sample_env, mock_request_manager):
        """Test that _set_inventory_item_cost returns True on success."""
        success_resp = MagicMock()
        success_resp.status_code = 200
        success_resp.json.return_value = {'inventory_item': {'id': 12345, 'cost': '10.00'}}
        success_resp.headers = {}

        mock_request_manager.request.return_value = success_resp

        api = self._make_api(sample_env, mock_request_manager)
        result = api._set_inventory_item_cost(12345, '10.00')
        assert result is True

    def test_build_metafields(self, sample_env, mock_request_manager, sample_enriched_product):
        api = self._make_api(sample_env, mock_request_manager)
        metafields = api._build_metafields(sample_enriched_product)

        keys = [m['key'] for m in metafields]
        assert 'brand' in keys
        assert 'ean' in keys
        assert 'wholesale_price' in keys
        assert 'specs' in keys

        specs_field = next(m for m in metafields if m['key'] == 'specs')
        assert specs_field['type'] == 'json'
        assert 'Kleur' in specs_field['value']
