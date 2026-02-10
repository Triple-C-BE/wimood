import os
import time

import pytest

from utils.scrape_cache import ScrapeCache


class TestScrapeCache:

    @pytest.fixture
    def cache_file(self, tmp_path):
        return str(tmp_path / 'test_cache.json')

    def test_empty_cache(self, cache_file):
        cache = ScrapeCache(cache_file)
        assert len(cache) == 0
        assert cache.get('NONEXISTENT') is None

    def test_set_and_get(self, cache_file):
        cache = ScrapeCache(cache_file)
        data = {'images': ['img1.jpg'], 'description': 'test', 'specs': {'color': 'red'}}
        cache.set('SKU-001', data)

        result = cache.get('SKU-001')
        assert result == data
        assert len(cache) == 1

    def test_save_and_load(self, cache_file):
        cache = ScrapeCache(cache_file)
        data = {'images': ['img1.jpg'], 'description': 'test', 'specs': {}}
        cache.set('SKU-001', data)
        cache.save()

        # Load in a new instance
        cache2 = ScrapeCache(cache_file)
        assert cache2.get('SKU-001') == data

    def test_is_stale_missing_entry(self, cache_file):
        cache = ScrapeCache(cache_file)
        assert cache.is_stale('NONEXISTENT') is True

    def test_is_stale_fresh_entry(self, cache_file):
        cache = ScrapeCache(cache_file)
        cache.set('SKU-001', {'images': []})
        assert cache.is_stale('SKU-001', max_age_days=7) is False

    def test_is_stale_old_entry(self, cache_file):
        cache = ScrapeCache(cache_file)
        cache._cache['SKU-001'] = {
            'data': {'images': []},
            'timestamp': time.time() - (8 * 86400),  # 8 days old
        }
        assert cache.is_stale('SKU-001', max_age_days=7) is True

    def test_save_creates_directory(self, tmp_path):
        cache_file = str(tmp_path / 'subdir' / 'cache.json')
        cache = ScrapeCache(cache_file)
        cache.set('SKU-001', {'images': []})
        cache.save()
        assert os.path.exists(cache_file)

    def test_load_invalid_json(self, cache_file):
        # Write invalid JSON to file
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        with open(cache_file, 'w') as f:
            f.write('not valid json{{{')

        cache = ScrapeCache(cache_file)
        assert len(cache) == 0

    def test_overwrite_existing_entry(self, cache_file):
        cache = ScrapeCache(cache_file)
        cache.set('SKU-001', {'images': ['old.jpg']})
        cache.set('SKU-001', {'images': ['new.jpg']})
        assert cache.get('SKU-001') == {'images': ['new.jpg']}
        assert len(cache) == 1
