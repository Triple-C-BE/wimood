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
