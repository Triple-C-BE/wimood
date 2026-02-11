from unittest.mock import MagicMock

from integrations.shopify_sync import _needs_update, sync_products


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
        api.set_cost_for_product.return_value = True
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
