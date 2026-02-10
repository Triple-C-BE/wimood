from unittest.mock import MagicMock

import pytest

# --- Sample product data ---

@pytest.fixture
def sample_wimood_product():
    """A product dict as returned by WimoodAPI.fetch_core_products()."""
    return {
        'product_id': '12345',
        'sku': 'WM-TEST-001',
        'title': 'Test Bureaustoel Deluxe',
        'brand': 'TestBrand',
        'ean': '8712345678901',
        'price': '149.99',
        'msrp': '199.99',
        'stock': '10',
    }


@pytest.fixture
def sample_enriched_product(sample_wimood_product):
    """A product dict after enrichment with scraped data."""
    return {
        **sample_wimood_product,
        'body_html': '<p>Een comfortabele bureaustoel met verstelbare armleuningen.</p>',
        'images': [
            'https://wimoodshop.nl/images/shop/12345_1.jpg',
            'https://wimoodshop.nl/images/shop/12345_2.jpg',
        ],
        'specs': {
            'Kleur': 'Zwart',
            'Materiaal': 'Mesh',
            'Gewicht': '15 kg',
        },
    }


@pytest.fixture
def sample_shopify_product():
    """A Shopify product dict as returned by the Shopify API."""
    return {
        'id': 99999,
        'title': 'Test Bureaustoel Deluxe',
        'vendor': 'TestBrand',
        'status': 'active',
        'body_html': '',
        'images': [],
        'variants': [
            {
                'id': 88888,
                'sku': 'WM-TEST-001',
                'price': '149.99',
                'inventory_item_id': 77777,
            }
        ],
    }


@pytest.fixture
def mock_request_manager():
    """A mock RequestManager that returns configurable responses."""
    manager = MagicMock()
    manager.request = MagicMock(return_value=None)
    return manager


@pytest.fixture
def sample_env():
    """A complete ENV dict for testing."""
    return {
        'WIMOOD_API_KEY': 'test-key',
        'WIMOOD_API_URL': 'https://api.wimoodshop.nl',
        'WIMOOD_BASE_URL': 'https://wimoodshop.nl',
        'WIMOOD_CUSTOMER_ID': 'CUST001',
        'SHOPIFY_STORE_URL': 'https://test-store.myshopify.com',
        'SHOPIFY_ACCESS_TOKEN': 'shpat_test_token',
        'SHOPIFY_VENDOR_TAG': 'Wimood_Sync',
        'SYNC_INTERVAL_SECONDS': 3600,
        'MAX_SCRAPE_RETRIES': 5,
        'ENABLE_SCRAPING': True,
        'SCRAPE_DELAY_SECONDS': 0,  # No delay in tests
        'LOG_DIR': 'logs',
        'LOG_LEVEL': 'DEBUG',
        'LOG_TO_STDOUT': False,
        'TEST_MODE': False,
        'TEST_PRODUCT_LIMIT': 5,
    }


@pytest.fixture
def sample_xml_response():
    """Sample XML content as returned by the Wimood API."""
    return '''<?xml version="1.0" encoding="UTF-8"?>
<products>
    <product>
        <product_id>12345</product_id>
        <product_code>WM-TEST-001</product_code>
        <product_name>Test Bureaustoel Deluxe</product_name>
        <brand>TestBrand</brand>
        <ean>8712345678901</ean>
        <prijs>149.99</prijs>
        <msrp>199.99</msrp>
        <stock>10</stock>
    </product>
    <product>
        <product_id>12346</product_id>
        <product_code>WM-TEST-002</product_code>
        <product_name>Test Vergadertafel</product_name>
        <brand>TestBrand</brand>
        <ean>8712345678902</ean>
        <prijs>299.00</prijs>
        <msrp>399.00</msrp>
        <stock>5</stock>
    </product>
</products>'''


@pytest.fixture
def sample_product_html():
    """Sample HTML for a Wimood product page."""
    return '''
<html>
<body>
    <div class="product-images">
        <img src="/images/shop/12345_1.jpg" alt="Product image 1">
        <img src="/images/shop/12345_2.jpg" alt="Product image 2">
        <img src="/images/shop/12345_3.jpg" alt="Product image 3">
    </div>

    <div class="product-details">
        <div class="collapsible">
            <button class="collapsible-header">Omschrijving</button>
            <div class="collapsible-content">
                <p>Een comfortabele bureaustoel met verstelbare armleuningen.</p>
                <p>Geschikt voor langdurig gebruik.</p>
            </div>
        </div>

        <div class="collapsible">
            <button class="collapsible-header">Specificaties</button>
            <div class="collapsible-content">
                <table>
                    <tr><td>Kleur</td><td>Zwart</td></tr>
                    <tr><td>Materiaal</td><td>Mesh</td></tr>
                    <tr><td>Gewicht</td><td>15 kg</td></tr>
                </table>
            </div>
        </div>
    </div>
</body>
</html>'''
