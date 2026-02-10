import json
import logging
import os
import tempfile
import time

LOGGER = logging.getLogger('scrape_cache')

CACHE_DIR = 'data'
CACHE_FILE = os.path.join(CACHE_DIR, 'scrape_cache.json')


class ScrapeCache:
    """
    JSON-file-based cache for scraped product data.
    Avoids re-scraping unchanged products every sync cycle.
    """

    def __init__(self, cache_file=CACHE_FILE):
        self.cache_file = cache_file
        self._cache = {}
        self.load()

    def load(self):
        """Load cache from disk."""
        if not os.path.exists(self.cache_file):
            self._cache = {}
            return

        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                self._cache = json.load(f)
            LOGGER.info(f"Loaded scrape cache with {len(self._cache)} entries.")
        except (json.JSONDecodeError, IOError) as e:
            LOGGER.warning(f"Failed to load scrape cache, starting fresh: {e}")
            self._cache = {}

    def save(self):
        """Save cache to disk using atomic write (temp file + rename)."""
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)

        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=os.path.dirname(self.cache_file),
                suffix='.tmp'
            )
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(self._cache, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.cache_file)
            LOGGER.debug(f"Saved scrape cache with {len(self._cache)} entries.")
        except IOError as e:
            LOGGER.error(f"Failed to save scrape cache: {e}")

    def get(self, sku):
        """
        Get cached scrape data for a SKU.

        Returns:
            dict with 'data' and 'timestamp', or None if not cached.
        """
        entry = self._cache.get(sku)
        if entry is None:
            return None
        return entry.get('data')

    def set(self, sku, data):
        """Store scrape data for a SKU with current timestamp."""
        self._cache[sku] = {
            'data': data,
            'timestamp': time.time(),
        }

    def is_stale(self, sku, max_age_days=7):
        """
        Check if a cached entry is stale (older than max_age_days).

        Returns:
            True if entry is missing or older than max_age_days.
        """
        entry = self._cache.get(sku)
        if entry is None:
            return True

        timestamp = entry.get('timestamp', 0)
        age_seconds = time.time() - timestamp
        max_age_seconds = max_age_days * 86400

        return age_seconds > max_age_seconds

    def __len__(self):
        return len(self._cache)
