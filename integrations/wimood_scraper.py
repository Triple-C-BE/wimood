import logging
import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

LOGGER = logging.getLogger('wimood_scraper')


class WimoodScraper:
    """
    Scrapes product detail pages from wimoodshop.nl to extract
    images, descriptions, and specification tables.
    """

    def __init__(self, env, request_manager, image_downloader=None):
        self.base_url = env.get('WIMOOD_BASE_URL', '').rstrip('/')
        self.delay = env.get('SCRAPE_DELAY_SECONDS', 2)
        self.max_retries = env.get('MAX_SCRAPE_RETRIES', 5)
        self.request_manager = request_manager
        self.image_downloader = image_downloader

        LOGGER.info(f"WimoodScraper initialized (base_url={self.base_url}, delay={self.delay}s)")

    def build_product_url(self, product):
        """
        Construct a product page URL from product data.
        Pattern: {base_url}/nl/products/{product_id}/{title_slug}
        """
        product_id = product.get('product_id', '')
        title = product.get('title', '')

        if not product_id:
            return None

        title_slug = self._slugify(title)
        return f"{self.base_url}/nl/products/{product_id}/{title_slug}"

    def scrape_product(self, product):
        """
        Scrape a single product page for enrichment data.

        Args:
            product: dict with at least 'product_id' and 'title'

        Returns:
            dict with 'images', 'description', 'specs' keys, or None on failure.
        """
        url = self.build_product_url(product)
        if not url:
            LOGGER.warning(f"Cannot build URL for product SKU={product.get('sku', '?')} — missing product_id")
            return None

        sku = product.get('sku', '?')
        LOGGER.debug(f"Scraping product {sku}: {url}")

        time.sleep(self.delay)

        response = self.request_manager.request('GET', url)
        if response is None:
            LOGGER.warning(f"Failed to fetch product page for {sku}: {url}")
            return None

        if response.status_code != 200:
            LOGGER.warning(f"Non-200 status ({response.status_code}) for {sku}: {url}")
            return None

        soup = BeautifulSoup(response.content, 'lxml')

        images = self._extract_images(soup)
        description = self._extract_description(soup)
        specs = self._extract_specs(soup)

        # Download images locally if downloader is available
        local_images = []
        if self.image_downloader and images:
            local_images = self.image_downloader.download_images(sku, images)

        LOGGER.info(
            f"Scraped {sku}: {len(images)} image URLs, "
            f"{len(local_images)} downloaded, "
            f"description={'yes' if description else 'no'}, "
            f"{len(specs)} specs"
        )

        return {
            'images': images,
            'local_images': local_images,
            'description': description,
            'specs': specs,
        }

    def check_connection(self):
        """
        Pre-flight check: verify we can reach the Wimood website.

        Returns:
            True if reachable, False otherwise.
        """
        LOGGER.info("Running Wimood site pre-flight check...")
        test_url = f"{self.base_url}/nl/products"
        response = self.request_manager.request('GET', test_url)

        if response is None:
            LOGGER.error("Pre-flight FAILED: Cannot reach Wimood website.")
            return False

        LOGGER.info("Pre-flight OK: Wimood website is reachable.")
        return True

    def _extract_images(self, soup):
        """
        Extract product image URLs from the product page gallery.

        Returns:
            List of absolute image URLs.
        """
        images = []

        # Primary: Flickity slider divs with data-flickity-bg-lazyload attribute
        slides = soup.find_all('div', attrs={'data-flickity-bg-lazyload': True})
        for slide in slides:
            src = slide.get('data-flickity-bg-lazyload', '')
            if src:
                abs_url = urljoin(self.base_url, src)
                if abs_url not in images:
                    images.append(abs_url)

        # Fallback: img tags in gallery containers
        if not images:
            gallery = soup.find('div', class_=re.compile(r'product.*image|gallery|slider', re.I))
            if gallery:
                img_tags = gallery.find_all('img', src=True)
            else:
                img_tags = soup.find_all('img', src=re.compile(r'/images/shop/'))

            for img in img_tags:
                src = img.get('src', '')
                if not src:
                    continue
                abs_url = urljoin(self.base_url, src)
                if abs_url not in images:
                    images.append(abs_url)

        return images[:10]  # Shopify max 10 images

    def _extract_description(self, soup):
        """
        Extract the product description from the "Omschrijving" section.

        Returns:
            HTML string of the description, or empty string.
        """
        # Find the "Omschrijving" heading/button/tab
        desc_header = soup.find(string=re.compile(r'Omschrijving', re.I))
        if not desc_header:
            return ''

        # Navigate to the parent container and find the content section
        parent = desc_header.find_parent()
        if parent is None:
            return ''

        # Try the sibling or next collapsible content div
        content = parent.find_next_sibling()
        if content is None:
            # Try parent's sibling
            grandparent = parent.find_parent()
            if grandparent:
                content = grandparent.find_next_sibling()

        if content is None:
            return ''

        # Get the inner HTML, strip excessive whitespace
        description = content.decode_contents().strip()
        return description

    def _extract_specs(self, soup):
        """
        Extract specifications from the "Specificaties" section.
        Parses field-name/field-value pairs into a dict.

        Returns:
            Dict of spec_name -> spec_value.
        """
        specs = {}

        spec_header = soup.find(string=re.compile(r'Specificaties', re.I))
        if not spec_header:
            return specs

        parent = spec_header.find_parent()
        if parent is None:
            return specs

        # Find the specs table/container
        content = parent.find_next_sibling()
        if content is None:
            grandparent = parent.find_parent()
            if grandparent:
                content = grandparent.find_next_sibling()

        if content is None:
            return specs

        # Try to find field-name/field-value pairs
        rows = content.find_all(class_=re.compile(r'field-name|spec-name|label', re.I))
        if rows:
            for row in rows:
                name = row.get_text(strip=True)
                value_el = row.find_next_sibling(class_=re.compile(r'field-value|spec-value|value', re.I))
                if value_el:
                    specs[name] = value_el.get_text(strip=True)
        else:
            # Fallback: try table rows
            table = content.find('table')
            if table:
                for tr in table.find_all('tr'):
                    cells = tr.find_all(['td', 'th'])
                    if len(cells) >= 2:
                        specs[cells[0].get_text(strip=True)] = cells[1].get_text(strip=True)

        return specs

    @staticmethod
    def _slugify(text):
        """Convert a title to a URL-safe slug."""
        text = text.lower().strip()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[\s_]+', '-', text)
        text = re.sub(r'-+', '-', text)
        return text.strip('-')
