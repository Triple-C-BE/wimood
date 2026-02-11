import os
import tempfile
from unittest.mock import MagicMock

from integrations.shopify_sync import _needs_update, sync_products
from utils.product_mapping import ProductMapping


class TestNeedsUpdate:

    def test_no_changes(self, sample_shopify_product, sample_wimood_product):
        assert _needs_update(sample_shopify_product, sample_wimood_product) is False

    def test_title_changed(self, sample_shopify_product, sample_wimood_product):
        sample_wimood_product['title'] = 'New Title'
        assert _needs_update(sample_shopify_product, sample_wimood_product) is True

    def test_price_changed(self, sample_shopify_product, sample_wimood_product):
        sample_wimood_product['price'] = '249.99'
        assert _needs_update(sample_shopify_product, sample_wimood_product) is True

    def test_inactive_status(self, sample_shopify_product, sample_wimood_product):
        sample_shopify_product['status'] = 'draft'
        assert _needs_update(sample_shopify_product, sample_wimood_product) is True

    def test_missing_body_html(self, sample_shopify_product, sample_wimood_product):
        sample_wimood_product['body_html'] = '<p>Description</p>'
        sample_shopify_product['body_html'] = ''
        assert _needs_update(sample_shopify_product, sample_wimood_product) is True

    def test_body_html_already_present(self, sample_shopify_product, sample_wimood_product):
        sample_wimood_product['body_html'] = '<p>Description</p>'
        sample_shopify_product['body_html'] = '<p>Existing</p>'
        assert _needs_update(sample_shopify_product, sample_wimood_product) is False

    def test_more_images_available(self, sample_shopify_product, sample_wimood_product):
        sample_wimood_product['images'] = ['img1.jpg', 'img2.jpg']
        sample_shopify_product['images'] = [{'src': 'img1.jpg'}]
        assert _needs_update(sample_shopify_product, sample_wimood_product) is True

    def test_same_image_count(self, sample_shopify_product, sample_wimood_product):
        sample_wimood_product['images'] = ['img1.jpg']
        sample_shopify_product['images'] = [{'src': 'img1.jpg'}]
        assert _needs_update(sample_shopify_product, sample_wimood_product) is False


class TestSyncProducts:

    def _make_shopify_api(self):
        api = MagicMock()
        api.get_all_products.return_value = []
        api.create_product.return_value = {'id': 1}
        api.update_product.return_value = {'id': 1}
        api.deactivate_product.return_value = True
        return api

    def test_create_new_products(self, sample_wimood_product):
        api = self._make_shopify_api()
        results = sync_products([sample_wimood_product], api)

        assert results['created'] == 1
        assert results['updated'] == 0
        api.create_product.assert_called_once()

    def test_skip_unchanged_products(self, sample_wimood_product, sample_shopify_product):
        api = self._make_shopify_api()
        api.get_all_products.return_value = [sample_shopify_product]

        results = sync_products([sample_wimood_product], api)

        assert results['skipped'] == 1
        assert results['created'] == 0
        api.create_product.assert_not_called()

    def test_update_changed_products(self, sample_wimood_product, sample_shopify_product):
        sample_wimood_product['price'] = '249.99'
        api = self._make_shopify_api()
        api.get_all_products.return_value = [sample_shopify_product]

        results = sync_products([sample_wimood_product], api)

        assert results['updated'] == 1
        api.update_product.assert_called_once()

    def test_deactivate_removed_products(self, sample_shopify_product):
        api = self._make_shopify_api()
        api.get_all_products.return_value = [sample_shopify_product]

        # Sync with empty wimood products — shopify product should be deactivated
        results = sync_products([], api)

        assert results['deactivated'] == 1
        api.deactivate_product.assert_called_once_with(99999)

    def test_skip_empty_sku(self):
        api = self._make_shopify_api()
        product = {'sku': '', 'title': 'No SKU', 'price': '10.00', 'stock': '1'}
        results = sync_products([product], api)

        assert results['skipped'] == 1
        api.create_product.assert_not_called()

    def test_enrichment_with_scraper(self, sample_wimood_product):
        api = self._make_shopify_api()

        scraper = MagicMock()
        scraper.scrape_product.return_value = {
            'images': ['img1.jpg'],
            'description': '<p>Test</p>',
            'specs': {'color': 'black'},
        }

        cache = MagicMock()
        cache.is_stale.return_value = True
        cache.get.return_value = None

        results = sync_products([sample_wimood_product], api, scraper=scraper, scrape_cache=cache)

        scraper.scrape_product.assert_called_once()
        cache.set.assert_called_once()
        cache.save.assert_called_once()
        assert results['created'] == 1

    def test_enrichment_from_cache(self, sample_wimood_product):
        api = self._make_shopify_api()

        scraper = MagicMock()
        cache = MagicMock()
        cache.is_stale.return_value = False
        cache.get.return_value = {
            'images': ['cached_img.jpg'],
            'description': '<p>Cached</p>',
            'specs': {},
        }

        results = sync_products([sample_wimood_product], api, scraper=scraper, scrape_cache=cache)

        # Should NOT have called scraper since cache is fresh
        scraper.scrape_product.assert_not_called()
        assert results['created'] == 1


class TestQuickSync:
    """Tests for the quick sync path (new_only mode with product_mapping)."""

    def _make_shopify_api(self):
        api = MagicMock()
        api.get_all_products.return_value = []
        api.get_products_by_ids.return_value = []
        api.create_product.return_value = {'id': 1}
        api.update_product.return_value = {'id': 1}
        api.deactivate_product.return_value = True
        api.set_cost_for_product.return_value = True
        return api

    def _make_mapping(self):
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        mapping = ProductMapping(path)
        self._temp_paths = getattr(self, '_temp_paths', [])
        self._temp_paths.append(path)
        return mapping

    def test_quick_sync_skips_unchanged(self, sample_wimood_product):
        api = self._make_shopify_api()
        mapping = self._make_mapping()

        # Pre-populate the cache so product appears unchanged
        mapping.set_synced_product(
            'WM-TEST-001', 'Test Bureaustoel Deluxe', '199.99', '149.99', '10',
            'TestBrand', '8712345678901', True
        )

        results = sync_products([sample_wimood_product], api, product_mapping=mapping,
                                scrape_mode="new_only")

        assert results['skipped'] == 1
        assert results['created'] == 0
        # Should not have called Shopify at all
        api.get_all_products.assert_not_called()
        api.get_products_by_ids.assert_not_called()

    def test_quick_sync_detects_price_change(self, sample_wimood_product, sample_shopify_product):
        api = self._make_shopify_api()
        mapping = self._make_mapping()

        # Cache has old price
        mapping.set_synced_product(
            'WM-TEST-001', 'Test Bureaustoel Deluxe', '179.99', '149.99', '10',
            'TestBrand', '8712345678901', True
        )
        mapping.set_mapping('12345', 99999, 'WM-TEST-001')

        # Shopify returns the product when fetched by ID
        sample_shopify_product['variants'][0]['price'] = '179.99'
        api.get_products_by_ids.return_value = [sample_shopify_product]

        results = sync_products([sample_wimood_product], api, product_mapping=mapping,
                                scrape_mode="new_only")

        assert results['updated'] == 1
        api.get_products_by_ids.assert_called_once()
        api.get_all_products.assert_not_called()

    def test_quick_sync_creates_new_product(self, sample_wimood_product):
        api = self._make_shopify_api()
        mapping = self._make_mapping()

        # No cache entry — product is new
        results = sync_products([sample_wimood_product], api, product_mapping=mapping,
                                scrape_mode="new_only")

        assert results['created'] == 1
        # Should have updated the sync cache
        cached = mapping.get_synced_product('WM-TEST-001')
        assert cached is not None
        assert cached['title'] == 'Test Bureaustoel Deluxe'
        assert cached['cost_synced'] == 1

    def test_quick_sync_cost_backfill(self, sample_wimood_product, sample_shopify_product):
        api = self._make_shopify_api()
        mapping = self._make_mapping()

        # Cache has current data but cost not synced
        mapping.set_synced_product(
            'WM-TEST-001', 'Test Bureaustoel Deluxe', '199.99', '149.99', '10',
            'TestBrand', '8712345678901', False
        )
        mapping.set_mapping('12345', 99999, 'WM-TEST-001')
        api.get_products_by_ids.return_value = [sample_shopify_product]

        results = sync_products([sample_wimood_product], api, product_mapping=mapping,
                                scrape_mode="new_only")

        assert results['skipped'] == 1
        api.set_cost_for_product.assert_called_once()
        assert mapping.is_cost_synced('WM-TEST-001') is True


class TestFullSyncWithCache:
    """Tests for the full sync path with cache population."""

    def _make_shopify_api(self):
        api = MagicMock()
        api.get_all_products.return_value = []
        api.create_product.return_value = {'id': 1}
        api.update_product.return_value = {'id': 1}
        api.deactivate_product.return_value = True
        api.set_cost_for_product.return_value = True
        return api

    def _make_mapping(self):
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        mapping = ProductMapping(path)
        return mapping

    def test_full_sync_populates_cache(self, sample_wimood_product):
        api = self._make_shopify_api()
        mapping = self._make_mapping()

        results = sync_products([sample_wimood_product], api, product_mapping=mapping,
                                scrape_mode="full")

        assert results['created'] == 1
        cached = mapping.get_synced_product('WM-TEST-001')
        assert cached is not None
        assert cached['cost_synced'] == 1

    def test_full_sync_cost_backfill_skipped_products(self, sample_wimood_product, sample_shopify_product):
        api = self._make_shopify_api()
        mapping = self._make_mapping()
        api.get_all_products.return_value = [sample_shopify_product]

        # No cache entry yet — cost_synced should be False initially
        results = sync_products([sample_wimood_product], api, product_mapping=mapping,
                                scrape_mode="full")

        # Product is unchanged so it's skipped, but cost should be backfilled
        assert results['skipped'] == 1
        api.set_cost_for_product.assert_called_once()
        cached = mapping.get_synced_product('WM-TEST-001')
        assert cached is not None
        assert cached['cost_synced'] == 1
