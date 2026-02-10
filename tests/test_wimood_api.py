from unittest.mock import MagicMock

from integrations.wimood_api import WimoodAPI


class TestWimoodAPI:

    def test_init(self, sample_env, mock_request_manager):
        api = WimoodAPI(sample_env, mock_request_manager)
        assert api.api_url == 'https://api.wimoodshop.nl'
        assert api.api_key == 'test-key'
        assert api.customer_id == 'CUST001'
        assert 'api_key=test-key' in api.full_url
        assert 'klantnummer=CUST001' in api.full_url

    def test_fetch_core_products_parses_xml(self, sample_env, mock_request_manager, sample_xml_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = sample_xml_response.encode('utf-8')
        mock_response.text = sample_xml_response
        mock_request_manager.request.return_value = mock_response

        api = WimoodAPI(sample_env, mock_request_manager)
        products = api.fetch_core_products()

        assert products is not None
        assert len(products) == 2

        p1 = products[0]
        assert p1['product_id'] == '12345'
        assert p1['sku'] == 'WM-TEST-001'
        assert p1['title'] == 'Test Bureaustoel Deluxe'
        assert p1['brand'] == 'TestBrand'
        assert p1['ean'] == '8712345678901'
        assert p1['price'] == '149.99'
        assert p1['msrp'] == '199.99'
        assert p1['stock'] == '10'

        p2 = products[1]
        assert p2['sku'] == 'WM-TEST-002'

    def test_fetch_core_products_returns_none_on_failure(self, sample_env, mock_request_manager):
        mock_request_manager.request.return_value = None

        api = WimoodAPI(sample_env, mock_request_manager)
        result = api.fetch_core_products()
        assert result is None

    def test_fetch_core_products_invalid_api_key(self, sample_env, mock_request_manager):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = 'Invalid API Key'
        mock_response.content = b'Invalid API Key'
        mock_request_manager.request.return_value = mock_response

        api = WimoodAPI(sample_env, mock_request_manager)
        result = api.fetch_core_products()
        assert result is None

    def test_fetch_core_products_invalid_xml(self, sample_env, mock_request_manager):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '<not valid xml'
        mock_response.content = b'<not valid xml'
        mock_request_manager.request.return_value = mock_response

        api = WimoodAPI(sample_env, mock_request_manager)
        result = api.fetch_core_products()
        assert result is None

    def test_check_connection_success(self, sample_env, mock_request_manager, sample_xml_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = sample_xml_response.encode('utf-8')
        mock_response.text = sample_xml_response
        mock_request_manager.request.return_value = mock_response

        api = WimoodAPI(sample_env, mock_request_manager)
        assert api.check_connection() is True

    def test_check_connection_failure(self, sample_env, mock_request_manager):
        mock_request_manager.request.return_value = None

        api = WimoodAPI(sample_env, mock_request_manager)
        assert api.check_connection() is False

    def test_empty_xml_returns_empty_list(self, sample_env, mock_request_manager):
        xml = '<?xml version="1.0"?><products></products>'
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = xml
        mock_response.content = xml.encode('utf-8')
        mock_request_manager.request.return_value = mock_response

        api = WimoodAPI(sample_env, mock_request_manager)
        result = api.fetch_core_products()
        assert result == []
