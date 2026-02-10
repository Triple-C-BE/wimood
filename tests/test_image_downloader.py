import base64
import os
import tempfile
from unittest.mock import MagicMock

import pytest

from utils.image_downloader import ImageDownloader


class TestImageDownloader:

    @pytest.fixture
    def temp_images_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def mock_request_manager(self):
        return MagicMock()

    def test_init(self, mock_request_manager, temp_images_dir):
        downloader = ImageDownloader(mock_request_manager, temp_images_dir)
        assert downloader.images_dir == temp_images_dir
        assert os.path.exists(temp_images_dir)

    def test_download_images_success(self, mock_request_manager, temp_images_dir):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'fake-image-data'
        mock_response.headers = {'Content-Type': 'image/jpeg'}
        mock_request_manager.request.return_value = mock_response

        downloader = ImageDownloader(mock_request_manager, temp_images_dir)
        urls = [
            'https://example.com/image1.jpg',
            'https://example.com/image2.jpg',
        ]
        downloaded = downloader.download_images('SKU-001', urls)

        assert len(downloaded) == 2
        assert all(os.path.exists(path) for path in downloaded)
        assert mock_request_manager.request.call_count == 2

    def test_download_images_skip_existing(self, mock_request_manager, temp_images_dir):
        downloader = ImageDownloader(mock_request_manager, temp_images_dir)

        sku_dir = os.path.join(temp_images_dir, 'SKU-001')
        os.makedirs(sku_dir)
        existing_file = os.path.join(sku_dir, 'image1.jpg')
        with open(existing_file, 'wb') as f:
            f.write(b'existing-data')

        urls = ['https://example.com/image1.jpg']
        downloaded = downloader.download_images('SKU-001', urls)

        assert len(downloaded) == 1
        assert downloaded[0] == existing_file
        assert mock_request_manager.request.call_count == 0

    def test_download_images_handles_failure(self, mock_request_manager, temp_images_dir):
        mock_request_manager.request.return_value = None

        downloader = ImageDownloader(mock_request_manager, temp_images_dir)
        urls = ['https://example.com/image1.jpg']
        downloaded = downloader.download_images('SKU-001', urls)

        assert len(downloaded) == 0

    def test_download_images_max_limit(self, mock_request_manager, temp_images_dir):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'fake-image-data'
        mock_response.headers = {'Content-Type': 'image/jpeg'}
        mock_request_manager.request.return_value = mock_response

        downloader = ImageDownloader(mock_request_manager, temp_images_dir)
        urls = [f'https://example.com/image{i}.jpg' for i in range(15)]
        downloaded = downloader.download_images('SKU-001', urls, max_images=3)

        assert len(downloaded) == 3

    def test_get_local_images(self, mock_request_manager, temp_images_dir):
        downloader = ImageDownloader(mock_request_manager, temp_images_dir)

        sku_dir = os.path.join(temp_images_dir, 'SKU-001')
        os.makedirs(sku_dir)
        for name in ['img1.jpg', 'img2.jpg']:
            with open(os.path.join(sku_dir, name), 'wb') as f:
                f.write(b'data')

        images = downloader.get_local_images('SKU-001')
        assert len(images) == 2

    def test_get_local_images_nonexistent_sku(self, mock_request_manager, temp_images_dir):
        downloader = ImageDownloader(mock_request_manager, temp_images_dir)
        assert downloader.get_local_images('NONEXISTENT') == []

    def test_encode_image_base64(self, temp_images_dir):
        filepath = os.path.join(temp_images_dir, 'test.jpg')
        test_data = b'test-image-data'
        with open(filepath, 'wb') as f:
            f.write(test_data)

        encoded = ImageDownloader.encode_image_base64(filepath)
        assert encoded is not None
        assert base64.b64decode(encoded) == test_data

    def test_encode_image_base64_missing_file(self):
        result = ImageDownloader.encode_image_base64('/nonexistent/file.jpg')
        assert result is None
