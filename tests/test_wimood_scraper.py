from unittest.mock import MagicMock, patch

from integrations.wimood_scraper import WimoodScraper


class TestWimoodScraper:

    def _make_scraper(self, sample_env, mock_request_manager):
        # Override delay to 0 for tests
        sample_env['SCRAPE_DELAY_SECONDS'] = 0
        return WimoodScraper(sample_env, mock_request_manager)

    def test_init(self, sample_env, mock_request_manager):
        scraper = self._make_scraper(sample_env, mock_request_manager)
        assert scraper.base_url == 'https://wimoodshop.nl'
        assert scraper.delay == 0

    def test_build_product_url(self, sample_env, mock_request_manager, sample_wimood_product):
        scraper = self._make_scraper(sample_env, mock_request_manager)
        url = scraper.build_product_url(sample_wimood_product)
        assert url == 'https://wimoodshop.nl/nl/products/12345/test-bureaustoel-deluxe'

    def test_build_product_url_no_id(self, sample_env, mock_request_manager):
        scraper = self._make_scraper(sample_env, mock_request_manager)
        url = scraper.build_product_url({'title': 'No ID Product'})
        assert url is None

    def test_slugify(self):
        assert WimoodScraper._slugify('Test Bureaustoel Deluxe') == 'test-bureaustoel-deluxe'
        assert WimoodScraper._slugify('  Spaced  Out  ') == 'spaced-out'
        assert WimoodScraper._slugify('Special (chars) & stuff!') == 'special-chars-stuff'

    @patch('integrations.wimood_scraper.time.sleep')
    def test_scrape_product_success(self, mock_sleep, sample_env, mock_request_manager,
                                     sample_wimood_product, sample_product_html):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = sample_product_html.encode('utf-8')
        mock_request_manager.request.return_value = mock_response

        scraper = self._make_scraper(sample_env, mock_request_manager)
        result = scraper.scrape_product(sample_wimood_product)

        assert result is not None
        assert 'images' in result
        assert 'description' in result
        assert 'specs' in result

    @patch('integrations.wimood_scraper.time.sleep')
    def test_extract_images(self, mock_sleep, sample_env, mock_request_manager,
                            sample_wimood_product, sample_product_html):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = sample_product_html.encode('utf-8')
        mock_request_manager.request.return_value = mock_response

        scraper = self._make_scraper(sample_env, mock_request_manager)
        result = scraper.scrape_product(sample_wimood_product)

        assert len(result['images']) == 3
        assert result['images'][0].startswith('https://wimoodshop.nl')
        assert '12345_1' in result['images'][0]

    @patch('integrations.wimood_scraper.time.sleep')
    def test_extract_description(self, mock_sleep, sample_env, mock_request_manager,
                                  sample_wimood_product, sample_product_html):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = sample_product_html.encode('utf-8')
        mock_request_manager.request.return_value = mock_response

        scraper = self._make_scraper(sample_env, mock_request_manager)
        result = scraper.scrape_product(sample_wimood_product)

        assert 'bureaustoel' in result['description'].lower()

    @patch('integrations.wimood_scraper.time.sleep')
    def test_extract_specs(self, mock_sleep, sample_env, mock_request_manager,
                           sample_wimood_product, sample_product_html):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = sample_product_html.encode('utf-8')
        mock_request_manager.request.return_value = mock_response

        scraper = self._make_scraper(sample_env, mock_request_manager)
        result = scraper.scrape_product(sample_wimood_product)

        assert result['specs'].get('Kleur') == 'Zwart'
        assert result['specs'].get('Materiaal') == 'Mesh'
        assert result['specs'].get('Gewicht') == '15 kg'

    @patch('integrations.wimood_scraper.time.sleep')
    def test_scrape_product_failure(self, mock_sleep, sample_env, mock_request_manager, sample_wimood_product):
        mock_request_manager.request.return_value = None

        scraper = self._make_scraper(sample_env, mock_request_manager)
        result = scraper.scrape_product(sample_wimood_product)
        assert result is None

    @patch('integrations.wimood_scraper.time.sleep')
    def test_scrape_product_non_200(self, mock_sleep, sample_env, mock_request_manager, sample_wimood_product):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_request_manager.request.return_value = mock_response

        scraper = self._make_scraper(sample_env, mock_request_manager)
        result = scraper.scrape_product(sample_wimood_product)
        assert result is None

    def test_check_connection_success(self, sample_env, mock_request_manager):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_request_manager.request.return_value = mock_response

        scraper = self._make_scraper(sample_env, mock_request_manager)
        assert scraper.check_connection() is True

    def test_check_connection_failure(self, sample_env, mock_request_manager):
        mock_request_manager.request.return_value = None

        scraper = self._make_scraper(sample_env, mock_request_manager)
        assert scraper.check_connection() is False

    def test_images_limited_to_10(self, sample_env, mock_request_manager):
        from bs4 import BeautifulSoup
        # Create HTML with 15 Flickity slider images
        slides = ''.join(
            f'<div class="product-slider__slide" data-flickity-bg-lazyload="/images/shop/12345_{i}"></div>'
            for i in range(15)
        )
        html = f'<html><body><div class="product-slider">{slides}</div></body></html>'

        scraper = self._make_scraper(sample_env, mock_request_manager)
        soup = BeautifulSoup(html, 'lxml')
        images = scraper._extract_images(soup)
        assert len(images) == 10
