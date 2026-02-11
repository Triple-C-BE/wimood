import os
import tempfile

import pytest

from utils.product_mapping import ProductMapping


class TestProductMapping:

    @pytest.fixture
    def temp_db(self):
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.remove(path)

    def test_init_creates_database(self, temp_db):
        mapping = ProductMapping(temp_db)
        assert os.path.exists(temp_db)
        assert len(mapping) == 0

    def test_set_and_get_mapping(self, temp_db):
        mapping = ProductMapping(temp_db)
        mapping.set_mapping('WIM123', 999, 'SKU-001')
        assert mapping.get_shopify_id('WIM123') == 999

    def test_get_nonexistent_returns_none(self, temp_db):
        mapping = ProductMapping(temp_db)
        assert mapping.get_shopify_id('NONEXISTENT') is None

    def test_get_by_sku(self, temp_db):
        mapping = ProductMapping(temp_db)
        mapping.set_mapping('WIM123', 999, 'SKU-001')
        result = mapping.get_by_sku('SKU-001')
        assert result is not None
        assert result['wimood_product_id'] == 'WIM123'
        assert result['shopify_product_id'] == 999

    def test_get_by_sku_nonexistent(self, temp_db):
        mapping = ProductMapping(temp_db)
        assert mapping.get_by_sku('NONEXISTENT') is None

    def test_update_existing_mapping(self, temp_db):
        mapping = ProductMapping(temp_db)
        mapping.set_mapping('WIM123', 999, 'SKU-001')
        assert len(mapping) == 1

        mapping.set_mapping('WIM123', 1000, 'SKU-001')
        assert len(mapping) == 1
        assert mapping.get_shopify_id('WIM123') == 1000

    def test_remove_mapping(self, temp_db):
        mapping = ProductMapping(temp_db)
        mapping.set_mapping('WIM123', 999, 'SKU-001')
        assert mapping.remove('WIM123') is True
        assert len(mapping) == 0
        assert mapping.get_shopify_id('WIM123') is None

    def test_remove_nonexistent(self, temp_db):
        mapping = ProductMapping(temp_db)
        assert mapping.remove('NONEXISTENT') is False

    def test_get_all_shopify_ids(self, temp_db):
        mapping = ProductMapping(temp_db)
        mapping.set_mapping('WIM1', 100, 'SKU-1')
        mapping.set_mapping('WIM2', 200, 'SKU-2')
        mapping.set_mapping('WIM3', 300, 'SKU-3')
        ids = mapping.get_all_shopify_ids()
        assert set(ids) == {100, 200, 300}

    def test_get_all_mappings(self, temp_db):
        mapping = ProductMapping(temp_db)
        mapping.set_mapping('WIM1', 100, 'SKU-1')
        mapping.set_mapping('WIM2', 200, 'SKU-2')
        all_mappings = mapping.get_all_mappings()
        assert len(all_mappings) == 2
        skus = {m['sku'] for m in all_mappings}
        assert skus == {'SKU-1', 'SKU-2'}

    def test_always_truthy(self, temp_db):
        mapping = ProductMapping(temp_db)
        assert len(mapping) == 0
        assert bool(mapping) is True  # Must be truthy even when empty

    def test_len(self, temp_db):
        mapping = ProductMapping(temp_db)
        assert len(mapping) == 0
        mapping.set_mapping('WIM1', 100, 'SKU-1')
        assert len(mapping) == 1
        mapping.set_mapping('WIM2', 200, 'SKU-2')
        assert len(mapping) == 2


class TestSyncedProducts:

    @pytest.fixture
    def temp_db(self):
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.remove(path)

    def test_get_synced_product_not_found(self, temp_db):
        mapping = ProductMapping(temp_db)
        assert mapping.get_synced_product('NONEXISTENT') is None

    def test_set_and_get_synced_product(self, temp_db):
        mapping = ProductMapping(temp_db)
        mapping.set_synced_product('SKU-1', 'Title', '19.99', '10.00', '5', 'Brand', '123', False)
        result = mapping.get_synced_product('SKU-1')
        assert result is not None
        assert result['sku'] == 'SKU-1'
        assert result['title'] == 'Title'
        assert result['price'] == '19.99'
        assert result['wholesale_price'] == '10.00'
        assert result['stock'] == '5'
        assert result['brand'] == 'Brand'
        assert result['ean'] == '123'
        assert result['cost_synced'] == 0

    def test_upsert_synced_product(self, temp_db):
        mapping = ProductMapping(temp_db)
        mapping.set_synced_product('SKU-1', 'Title', '19.99', '10.00', '5', 'Brand', '123', False)
        mapping.set_synced_product('SKU-1', 'New Title', '29.99', '15.00', '10', 'Brand', '123', True)
        result = mapping.get_synced_product('SKU-1')
        assert result['title'] == 'New Title'
        assert result['price'] == '29.99'
        assert result['cost_synced'] == 1

    def test_has_product_changed_new_product(self, temp_db):
        mapping = ProductMapping(temp_db)
        assert mapping.has_product_changed('SKU-1', {'title': 'T', 'price': '1', 'stock': '1'}) is True

    def test_has_product_changed_no_change(self, temp_db):
        mapping = ProductMapping(temp_db)
        mapping.set_synced_product('SKU-1', 'Title', '19.99', '10.00', '5', 'Brand', '123', True)
        assert mapping.has_product_changed('SKU-1', {'title': 'Title', 'price': '19.99', 'stock': '5'}) is False

    def test_has_product_changed_title_changed(self, temp_db):
        mapping = ProductMapping(temp_db)
        mapping.set_synced_product('SKU-1', 'Title', '19.99', '10.00', '5', 'Brand', '123', True)
        assert mapping.has_product_changed('SKU-1', {'title': 'New Title', 'price': '19.99', 'stock': '5'}) is True

    def test_has_product_changed_price_changed(self, temp_db):
        mapping = ProductMapping(temp_db)
        mapping.set_synced_product('SKU-1', 'Title', '19.99', '10.00', '5', 'Brand', '123', True)
        assert mapping.has_product_changed('SKU-1', {'title': 'Title', 'price': '29.99', 'stock': '5'}) is True

    def test_has_product_changed_stock_changed(self, temp_db):
        mapping = ProductMapping(temp_db)
        mapping.set_synced_product('SKU-1', 'Title', '19.99', '10.00', '5', 'Brand', '123', True)
        assert mapping.has_product_changed('SKU-1', {'title': 'Title', 'price': '19.99', 'stock': '10'}) is True

    def test_is_cost_synced_false(self, temp_db):
        mapping = ProductMapping(temp_db)
        mapping.set_synced_product('SKU-1', 'Title', '19.99', '10.00', '5', 'Brand', '123', False)
        assert mapping.is_cost_synced('SKU-1') is False

    def test_is_cost_synced_true(self, temp_db):
        mapping = ProductMapping(temp_db)
        mapping.set_synced_product('SKU-1', 'Title', '19.99', '10.00', '5', 'Brand', '123', True)
        assert mapping.is_cost_synced('SKU-1') is True

    def test_is_cost_synced_nonexistent(self, temp_db):
        mapping = ProductMapping(temp_db)
        assert mapping.is_cost_synced('NONEXISTENT') is False

    def test_mark_cost_synced(self, temp_db):
        mapping = ProductMapping(temp_db)
        mapping.set_synced_product('SKU-1', 'Title', '19.99', '10.00', '5', 'Brand', '123', False)
        assert mapping.is_cost_synced('SKU-1') is False
        mapping.mark_cost_synced('SKU-1')
        assert mapping.is_cost_synced('SKU-1') is True
