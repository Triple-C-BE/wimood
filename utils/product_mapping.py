import logging
import os
import sqlite3
from typing import Dict, List, Optional

LOGGER = logging.getLogger('product_mapping')

MAPPING_DIR = 'data'
MAPPING_FILE = os.path.join(MAPPING_DIR, 'product_mapping.db')


class ProductMapping:
    """
    SQLite-based mapping between Wimood product_id and Shopify product ID.
    Provides persistent storage for product synchronization.
    """

    def __init__(self, db_file=MAPPING_FILE):
        self.db_file = db_file
        self._ensure_database()

    def _ensure_database(self):
        os.makedirs(os.path.dirname(self.db_file), exist_ok=True)
        with sqlite3.connect(self.db_file) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS product_mapping (
                    wimood_product_id TEXT PRIMARY KEY,
                    shopify_product_id INTEGER NOT NULL,
                    sku TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_sku ON product_mapping(sku)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_shopify_id ON product_mapping(shopify_product_id)')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS cost_sync_status (
                    sku TEXT PRIMARY KEY,
                    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        LOGGER.info(f"Product mapping database initialized at {self.db_file}")

    def get_shopify_id(self, wimood_product_id: str) -> Optional[int]:
        """Get Shopify product ID for a given Wimood product_id."""
        with sqlite3.connect(self.db_file) as conn:
            row = conn.execute(
                'SELECT shopify_product_id FROM product_mapping WHERE wimood_product_id = ?',
                (wimood_product_id,)
            ).fetchone()
        return row[0] if row else None

    def set_mapping(self, wimood_product_id: str, shopify_product_id: int, sku: str):
        """Store or update a product mapping."""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute('''
                INSERT INTO product_mapping (wimood_product_id, shopify_product_id, sku, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(wimood_product_id) DO UPDATE SET
                    shopify_product_id = excluded.shopify_product_id,
                    sku = excluded.sku,
                    updated_at = CURRENT_TIMESTAMP
            ''', (wimood_product_id, shopify_product_id, sku))
        LOGGER.debug(f"Mapped Wimood product {wimood_product_id} -> Shopify {shopify_product_id} (SKU={sku})")

    def get_by_sku(self, sku: str) -> Optional[Dict]:
        """Find mapping by SKU."""
        with sqlite3.connect(self.db_file) as conn:
            row = conn.execute(
                'SELECT wimood_product_id, shopify_product_id FROM product_mapping WHERE sku = ?',
                (sku,)
            ).fetchone()
        if row:
            return {'wimood_product_id': row[0], 'shopify_product_id': row[1]}
        return None

    def get_all_shopify_ids(self) -> List[int]:
        """Get all Shopify product IDs managed by this sync."""
        with sqlite3.connect(self.db_file) as conn:
            rows = conn.execute('SELECT shopify_product_id FROM product_mapping').fetchall()
        return [row[0] for row in rows]

    def get_all_mappings(self) -> List[Dict]:
        """Get all mappings as a list of dicts."""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                'SELECT wimood_product_id, shopify_product_id, sku FROM product_mapping'
            ).fetchall()
        return [dict(row) for row in rows]

    def remove(self, wimood_product_id: str) -> bool:
        """Remove a product mapping. Returns True if a row was deleted."""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.execute(
                'DELETE FROM product_mapping WHERE wimood_product_id = ?',
                (wimood_product_id,)
            )
        deleted = cursor.rowcount > 0
        if deleted:
            LOGGER.debug(f"Removed mapping for Wimood product {wimood_product_id}")
        return deleted

    def is_cost_synced(self, sku: str) -> bool:
        """Check if cost has been synced for a product."""
        with sqlite3.connect(self.db_file) as conn:
            row = conn.execute(
                'SELECT 1 FROM cost_sync_status WHERE sku = ?', (sku,)
            ).fetchone()
        return row is not None

    def mark_cost_synced(self, sku: str):
        """Mark a product's cost as synced."""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute(
                'INSERT OR REPLACE INTO cost_sync_status (sku, synced_at) VALUES (?, CURRENT_TIMESTAMP)',
                (sku,)
            )

    def __bool__(self):
        """ProductMapping is always truthy when instantiated."""
        return True

    def __len__(self):
        with sqlite3.connect(self.db_file) as conn:
            row = conn.execute('SELECT COUNT(*) FROM product_mapping').fetchone()
        return row[0]
