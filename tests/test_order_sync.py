from integrations.order_sync import map_shopify_address_to_wimood, sync_orders


class TestAddressMapping:
    """Tests for Shopify -> Wimood address mapping."""

    def test_basic_dutch_address(self):
        address = {
            'first_name': 'Jan',
            'last_name': 'de Vries',
            'company': 'Acme BV',
            'address1': 'Keizersgracht 123',
            'address2': '',
            'city': 'Amsterdam',
            'zip': '1015 CJ',
            'country_code': 'NL',
        }
        result = map_shopify_address_to_wimood(address)
        assert result['contact'] == 'Jan de Vries'
        assert result['company'] == 'Acme BV'
        assert result['street'] == 'Keizersgracht'
        assert result['housenumber'] == '123'
        assert result['postcode'] == '1015 CJ'
        assert result['city'] == 'Amsterdam'
        assert result['country'] == 'NL'

    def test_house_number_with_suffix(self):
        address = {
            'first_name': 'Piet',
            'last_name': 'Bakker',
            'address1': 'Herengracht 456b',
            'address2': '',
            'city': 'Amsterdam',
            'zip': '1017 CA',
            'country_code': 'NL',
        }
        result = map_shopify_address_to_wimood(address)
        assert result['street'] == 'Herengracht'
        assert result['housenumber'] == '456b'

    def test_address2_as_addition(self):
        address = {
            'first_name': 'Maria',
            'last_name': 'Jansen',
            'address1': 'Damstraat 10',
            'address2': '3e etage',
            'city': 'Rotterdam',
            'zip': '3011 BH',
            'country_code': 'NL',
        }
        result = map_shopify_address_to_wimood(address)
        assert result['street'] == 'Damstraat'
        assert result['housenumber'] == '10 3e etage'

    def test_no_house_number_in_address1(self):
        address = {
            'first_name': 'Test',
            'last_name': 'User',
            'address1': 'Some Street Without Number',
            'address2': '42',
            'city': 'Utrecht',
            'zip': '3500 AA',
            'country_code': 'NL',
        }
        result = map_shopify_address_to_wimood(address)
        # When no number found in address1, use address1 as street and address2 as housenumber
        assert result['street'] == 'Some Street Without Number'
        assert result['housenumber'] == '42'

    def test_empty_company(self):
        address = {
            'first_name': 'Test',
            'last_name': 'User',
            'company': None,
            'address1': 'Teststraat 1',
            'address2': '',
            'city': 'Den Haag',
            'zip': '2500 AA',
            'country_code': 'NL',
        }
        result = map_shopify_address_to_wimood(address)
        assert result['company'] == ''

    def test_multi_word_street(self):
        address = {
            'first_name': 'A',
            'last_name': 'B',
            'address1': 'Jan van Galenstraat 88',
            'address2': '',
            'city': 'Amsterdam',
            'zip': '1000 AA',
            'country_code': 'NL',
        }
        result = map_shopify_address_to_wimood(address)
        assert result['street'] == 'Jan van Galenstraat'
        assert result['housenumber'] == '88'


class TestSyncOrdersFetchStore:
    """Tests for the order fetch & store step of sync_orders."""

    def test_new_orders_are_stored(self, mocker):
        mock_shopify = mocker.MagicMock()
        mock_shopify.get_unfulfilled_orders.return_value = [
            {
                'id': 1001,
                'order_number': '1001',
                'fulfillment_status': None,
                'created_at': '2025-01-01T00:00:00Z',
                'fulfillments': [],
            },
        ]

        mock_store = mocker.MagicMock()
        mock_store.get_all_orders.return_value = []
        mock_store.get_unsubmitted_orders.return_value = []
        mock_store.get_submitted_unfulfilled.return_value = []

        results = sync_orders(mock_shopify, mock_store)

        assert results['new_orders'] == 1
        mock_store.upsert_order.assert_called_once()
        call_args = mock_store.upsert_order.call_args[0][0]
        assert call_args['shopify_order_id'] == 1001

    def test_existing_orders_not_counted_as_new(self, mocker):
        mock_shopify = mocker.MagicMock()
        mock_shopify.get_unfulfilled_orders.return_value = [
            {
                'id': 1001,
                'order_number': '1001',
                'fulfillment_status': None,
                'created_at': '2025-01-01T00:00:00Z',
                'fulfillments': [],
            },
        ]

        mock_store = mocker.MagicMock()
        mock_store.get_all_orders.return_value = [{'shopify_order_id': 1001}]
        mock_store.get_unsubmitted_orders.return_value = []
        mock_store.get_submitted_unfulfilled.return_value = []

        results = sync_orders(mock_shopify, mock_store)

        assert results['new_orders'] == 0


class TestSyncOrdersDropship:
    """Tests for the Wimood dropship submission step."""

    def test_submit_order_to_wimood(self, mocker):
        mock_shopify = mocker.MagicMock()
        mock_shopify.get_unfulfilled_orders.return_value = []

        mock_store = mocker.MagicMock()
        mock_store.get_all_orders.return_value = []
        mock_store.get_unsubmitted_orders.return_value = [
            {
                'shopify_order_id': 2001,
                'order_number': '2001',
                'fulfillment_status': 'unfulfilled',
            },
        ]
        mock_store.get_submitted_unfulfilled.return_value = []

        mock_shopify.get_order.return_value = {
            'id': 2001,
            'line_items': [
                {'sku': 'WM-001', 'quantity': 2},
                {'sku': 'NON-WIMOOD', 'quantity': 1},
            ],
            'shipping_address': {
                'first_name': 'Jan',
                'last_name': 'Jansen',
                'company': '',
                'address1': 'Teststraat 10',
                'address2': '',
                'city': 'Amsterdam',
                'zip': '1000 AA',
                'country_code': 'NL',
            },
        }

        mock_wimood = mocker.MagicMock()
        mock_wimood.create_order.return_value = 99001

        mock_mapping = mocker.MagicMock()
        mock_mapping.get_by_sku.side_effect = lambda sku: (
            {'wimood_product_id': 'P123', 'shopify_product_id': 5001} if sku == 'WM-001' else None
        )

        results = sync_orders(mock_shopify, mock_store,
                              wimood_api=mock_wimood, product_mapping=mock_mapping)

        assert results['submitted'] == 1
        mock_wimood.create_order.assert_called_once()
        order_data = mock_wimood.create_order.call_args[0][0]
        assert order_data['reference'] == '2001'
        assert len(order_data['items']) == 1
        assert order_data['items'][0]['product_id'] == 'P123'
        assert order_data['items'][0]['quantity'] == 2
        mock_store.mark_submitted.assert_called_once_with(2001, 99001)

    def test_skip_order_with_no_wimood_products(self, mocker):
        mock_shopify = mocker.MagicMock()
        mock_shopify.get_unfulfilled_orders.return_value = []

        mock_store = mocker.MagicMock()
        mock_store.get_all_orders.return_value = []
        mock_store.get_unsubmitted_orders.return_value = [
            {
                'shopify_order_id': 2002,
                'order_number': '2002',
                'fulfillment_status': 'unfulfilled',
            },
        ]
        mock_store.get_submitted_unfulfilled.return_value = []

        mock_shopify.get_order.return_value = {
            'id': 2002,
            'line_items': [
                {'sku': 'NON-WIMOOD', 'quantity': 1},
            ],
            'shipping_address': {
                'first_name': 'Test',
                'last_name': 'User',
                'address1': 'Street 1',
                'address2': '',
                'city': 'City',
                'zip': '1234',
                'country_code': 'NL',
            },
        }

        mock_wimood = mocker.MagicMock()
        mock_mapping = mocker.MagicMock()
        mock_mapping.get_by_sku.return_value = None

        results = sync_orders(mock_shopify, mock_store,
                              wimood_api=mock_wimood, product_mapping=mock_mapping)

        assert results['submitted'] == 0
        mock_wimood.create_order.assert_not_called()
        # Should still mark as submitted to avoid re-checking
        mock_store.mark_submitted.assert_called_once_with(2002, 0)

    def test_skip_order_with_no_shipping_address(self, mocker):
        mock_shopify = mocker.MagicMock()
        mock_shopify.get_unfulfilled_orders.return_value = []

        mock_store = mocker.MagicMock()
        mock_store.get_all_orders.return_value = []
        mock_store.get_unsubmitted_orders.return_value = [
            {
                'shopify_order_id': 2003,
                'order_number': '2003',
                'fulfillment_status': 'unfulfilled',
            },
        ]
        mock_store.get_submitted_unfulfilled.return_value = []

        mock_shopify.get_order.return_value = {
            'id': 2003,
            'line_items': [{'sku': 'WM-001', 'quantity': 1}],
            'shipping_address': None,
        }

        mock_wimood = mocker.MagicMock()
        mock_mapping = mocker.MagicMock()
        mock_mapping.get_by_sku.return_value = {'wimood_product_id': 'P1', 'shopify_product_id': 1}

        results = sync_orders(mock_shopify, mock_store,
                              wimood_api=mock_wimood, product_mapping=mock_mapping)

        assert results['errors'] == 1
        mock_wimood.create_order.assert_not_called()


class TestSyncOrdersPolling:
    """Tests for the Wimood order status polling step."""

    def test_fulfill_when_tracking_available(self, mocker):
        mock_shopify = mocker.MagicMock()
        mock_shopify.get_unfulfilled_orders.return_value = []
        mock_shopify.create_fulfillment.return_value = True

        mock_store = mocker.MagicMock()
        mock_store.get_all_orders.return_value = []
        mock_store.get_unsubmitted_orders.return_value = []
        mock_store.get_submitted_unfulfilled.return_value = [
            {
                'shopify_order_id': 3001,
                'order_number': '3001',
                'wimood_order_id': 88001,
                'wimood_status': 'received',
                'fulfillment_status': 'unfulfilled',
            },
        ]

        mock_wimood = mocker.MagicMock()
        mock_wimood.get_order_status.return_value = {
            'status': 'shipped',
            'track_and_trace': {
                'code': '3STEST12345',
                'url': 'https://tracking.example.com/3STEST12345',
            },
        }

        results = sync_orders(mock_shopify, mock_store, wimood_api=mock_wimood)

        assert results['fulfilled'] == 1
        assert results['poll_checked'] == 1
        mock_shopify.create_fulfillment.assert_called_once_with(
            3001, '3STEST12345', 'https://tracking.example.com/3STEST12345'
        )
        mock_store.update_fulfillment.assert_called_once_with(
            3001, 'fulfilled', '3STEST12345', 'https://tracking.example.com/3STEST12345'
        )

    def test_no_fulfill_without_tracking(self, mocker):
        mock_shopify = mocker.MagicMock()
        mock_shopify.get_unfulfilled_orders.return_value = []

        mock_store = mocker.MagicMock()
        mock_store.get_all_orders.return_value = []
        mock_store.get_unsubmitted_orders.return_value = []
        mock_store.get_submitted_unfulfilled.return_value = [
            {
                'shopify_order_id': 3002,
                'order_number': '3002',
                'wimood_order_id': 88002,
                'wimood_status': 'received',
                'fulfillment_status': 'unfulfilled',
            },
        ]

        mock_wimood = mocker.MagicMock()
        mock_wimood.get_order_status.return_value = {
            'status': 'processing',
            'track_and_trace': {},
        }

        results = sync_orders(mock_shopify, mock_store, wimood_api=mock_wimood)

        assert results['fulfilled'] == 0
        assert results['poll_checked'] == 1
        mock_shopify.create_fulfillment.assert_not_called()

    def test_skip_orders_with_zero_wimood_id(self, mocker):
        """Orders marked submitted with wimood_order_id=0 (no Wimood products) should not be polled."""
        mock_shopify = mocker.MagicMock()
        mock_shopify.get_unfulfilled_orders.return_value = []

        mock_store = mocker.MagicMock()
        mock_store.get_all_orders.return_value = []
        mock_store.get_unsubmitted_orders.return_value = []
        mock_store.get_submitted_unfulfilled.return_value = [
            {
                'shopify_order_id': 3003,
                'order_number': '3003',
                'wimood_order_id': 0,
                'wimood_status': '',
                'fulfillment_status': 'unfulfilled',
            },
        ]

        mock_wimood = mocker.MagicMock()

        results = sync_orders(mock_shopify, mock_store, wimood_api=mock_wimood)

        assert results['poll_checked'] == 0
        mock_wimood.get_order_status.assert_not_called()
