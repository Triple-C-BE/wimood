import os
from unittest.mock import patch

import pytest

from utils.env import get_env_var, load_env_variables


class TestGetEnvVar:

    def test_string_default(self):
        with patch.dict(os.environ, {}, clear=False):
            result = get_env_var('NONEXISTENT_VAR', default='fallback')
            assert result == 'fallback'

    def test_int_casting(self):
        with patch.dict(os.environ, {'TEST_INT': '42'}):
            result = get_env_var('TEST_INT', var_type=int)
            assert result == 42
            assert isinstance(result, int)

    def test_bool_casting_true(self):
        for val in ['true', 'True', '1', 'yes', 'on']:
            with patch.dict(os.environ, {'TEST_BOOL': val}):
                result = get_env_var('TEST_BOOL', var_type=bool)
                assert result is True

    def test_bool_casting_false(self):
        for val in ['false', 'False', '0', 'no', 'off']:
            with patch.dict(os.environ, {'TEST_BOOL': val}):
                result = get_env_var('TEST_BOOL', var_type=bool)
                assert result is False

    def test_required_missing(self):
        with patch.dict(os.environ, {}, clear=False):
            with pytest.raises(ValueError, match="required"):
                get_env_var('MISSING_REQUIRED', required=True)

    def test_required_present(self):
        with patch.dict(os.environ, {'PRESENT': 'value'}):
            result = get_env_var('PRESENT', required=True)
            assert result == 'value'

    def test_none_default_not_required(self):
        with patch.dict(os.environ, {}, clear=False):
            result = get_env_var('NONEXISTENT')
            assert result is None

    def test_invalid_int_casting(self):
        with patch.dict(os.environ, {'BAD_INT': 'not_a_number'}):
            with pytest.raises(ValueError):
                get_env_var('BAD_INT', var_type=int)


class TestLoadEnvVariables:

    @patch.dict(os.environ, {
        'WIMOOD_API_KEY': 'key123',
        'WIMOOD_API_URL': 'https://api.test.nl',
        'WIMOOD_BASE_URL': 'https://test.nl',
        'WIMOOD_CUSTOMER_ID': 'CUST001',
        'SHOPIFY_STORE_URL': 'https://store.myshopify.com',
        'SHOPIFY_ACCESS_TOKEN': 'shpat_test',
    })
    def test_loads_required_vars(self):
        env = load_env_variables()
        assert env['WIMOOD_API_KEY'] == 'key123'
        assert env['SHOPIFY_STORE_URL'] == 'https://store.myshopify.com'

    @patch('utils.env.load_dotenv')
    @patch.dict(os.environ, {
        'WIMOOD_API_KEY': 'key123',
        'WIMOOD_API_URL': 'https://api.test.nl',
        'WIMOOD_BASE_URL': 'https://test.nl',
        'WIMOOD_CUSTOMER_ID': 'CUST001',
        'SHOPIFY_STORE_URL': 'https://store.myshopify.com',
        'SHOPIFY_ACCESS_TOKEN': 'shpat_test',
    }, clear=True)
    def test_optional_defaults(self, mock_dotenv):
        env = load_env_variables()
        assert env['LOG_DIR'] == 'logs'
        assert env['LOG_LEVEL'] == 'INFO'
        assert env['SYNC_INTERVAL_SECONDS'] == 3600
        assert env['TEST_MODE'] is False
        assert env['SCRAPE_DELAY_SECONDS'] == 2

    @patch('utils.env.load_dotenv')
    @patch.dict(os.environ, {
        'WIMOOD_API_KEY': 'key123',
        'WIMOOD_API_URL': 'https://api.test.nl',
        'WIMOOD_BASE_URL': 'https://test.nl',
        'WIMOOD_CUSTOMER_ID': 'CUST001',
        'SHOPIFY_STORE_URL': 'https://store.myshopify.com',
        'SHOPIFY_ACCESS_TOKEN': 'shpat_test',
        'SCRAPE_DELAY_SECONDS': '5',
    }, clear=True)
    def test_scraping_vars(self, mock_dotenv):
        env = load_env_variables()
        assert env['SCRAPE_DELAY_SECONDS'] == 5

    @patch('utils.env.load_dotenv')
    @patch.dict(os.environ, {}, clear=True)
    def test_missing_required_exits(self, mock_dotenv):
        with pytest.raises(SystemExit):
            load_env_variables()
