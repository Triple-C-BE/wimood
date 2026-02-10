import base64
import logging
import os
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

LOGGER = logging.getLogger('image_downloader')

IMAGES_DIR = 'data/images'


class ImageDownloader:
    """Downloads and manages product images for Shopify upload."""

    def __init__(self, request_manager, images_dir=IMAGES_DIR):
        self.request_manager = request_manager
        self.images_dir = images_dir
        os.makedirs(images_dir, exist_ok=True)
        LOGGER.info(f"ImageDownloader initialized (dir={images_dir})")

    def download_images(self, sku: str, image_urls: List[str], max_images: int = 10) -> List[str]:
        """
        Download images for a product SKU.

        Returns:
            List of local file paths to downloaded images.
        """
        if not image_urls:
            return []

        sku_dir = os.path.join(self.images_dir, sku)
        os.makedirs(sku_dir, exist_ok=True)

        downloaded = []
        for idx, url in enumerate(image_urls[:max_images], 1):
            filename = self._get_filename_from_url(url, idx)
            filepath = os.path.join(sku_dir, filename)

            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                LOGGER.debug(f"Image already exists: {filepath}")
                downloaded.append(filepath)
                continue

            if self._download_image(url, filepath):
                downloaded.append(filepath)
            else:
                LOGGER.warning(f"Failed to download image {idx} for SKU {sku}: {url}")

        LOGGER.info(f"Images for SKU {sku}: {len(downloaded)} ready ({len(downloaded)} local)")
        return downloaded

    def _download_image(self, url: str, filepath: str) -> bool:
        try:
            response = self.request_manager.request('GET', url, timeout=30)
            if response is None or response.status_code != 200:
                return False

            content_type = response.headers.get('Content-Type', '')
            if content_type and not content_type.startswith('image/'):
                LOGGER.warning(f"Not an image: {url} (Content-Type: {content_type})")
                return False

            with open(filepath, 'wb') as f:
                f.write(response.content)

            LOGGER.debug(f"Downloaded: {filepath} ({len(response.content)} bytes)")
            return True
        except Exception as e:
            LOGGER.error(f"Exception downloading {url}: {e}")
            return False

    def _get_filename_from_url(self, url: str, index: int) -> str:
        parsed = urlparse(url)
        path = Path(parsed.path)
        if path.suffix and path.name:
            return path.name
        return f"image_{index}.jpg"

    def get_local_images(self, sku: str) -> List[str]:
        """Get list of locally cached images for a SKU."""
        sku_dir = os.path.join(self.images_dir, sku)
        if not os.path.exists(sku_dir):
            return []
        return sorted(
            os.path.join(sku_dir, f)
            for f in os.listdir(sku_dir)
            if os.path.isfile(os.path.join(sku_dir, f))
        )

    @staticmethod
    def encode_image_base64(filepath: str) -> Optional[str]:
        """Read an image file and encode it as base64."""
        try:
            with open(filepath, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            LOGGER.error(f"Failed to encode image {filepath}: {e}")
            return None
