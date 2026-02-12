import logging
import os
import sqlite3
from typing import Dict, List, Optional

LOGGER = logging.getLogger('order_store')

DATA_DIR = 'data'
DB_FILE = os.path.join(DATA_DIR, 'wimood_sync.db')


class OrderStore:
    """
    SQLite-based storage for Shopify orders.
    Tracks order fulfillment status, Wimood dropship submission, and tracking information.
    """

    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self._ensure_database()

    def _ensure_database(self):
        os.makedirs(os.path.dirname(self.db_file), exist_ok=True)
        with sqlite3.connect(self.db_file) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    shopify_order_id INTEGER PRIMARY KEY,
                    order_number TEXT NOT NULL,
                    fulfillment_status TEXT NOT NULL DEFAULT 'unfulfilled',
                    created_at TEXT NOT NULL,
                    tracking_number TEXT DEFAULT '',
                    tracking_url TEXT DEFAULT '',
                    wimood_order_id INTEGER DEFAULT NULL,
                    wimood_status TEXT DEFAULT '',
                    dropship_submitted INTEGER DEFAULT 0,
                    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_fulfillment_status ON orders(fulfillment_status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_dropship ON orders(dropship_submitted)')

            # Migrate existing databases: add new columns if missing
            self._migrate(conn)

        LOGGER.debug(f"Orders table ready in {self.db_file}")

    def _migrate(self, conn):
        """Add columns that may be missing from older schema versions."""
        cursor = conn.execute("PRAGMA table_info(orders)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        migrations = [
            ('wimood_order_id', 'INTEGER DEFAULT NULL'),
            ('wimood_status', "TEXT DEFAULT ''"),
            ('dropship_submitted', 'INTEGER DEFAULT 0'),
        ]

        for col_name, col_def in migrations:
            if col_name not in existing_columns:
                conn.execute(f'ALTER TABLE orders ADD COLUMN {col_name} {col_def}')
                LOGGER.info(f"Migrated: added column '{col_name}' to orders table")

    def upsert_order(self, order: Dict):
        """Insert or update an order."""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute('''
                INSERT INTO orders (shopify_order_id, order_number, fulfillment_status, created_at,
                                    tracking_number, tracking_url, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(shopify_order_id) DO UPDATE SET
                    fulfillment_status = excluded.fulfillment_status,
                    tracking_number = excluded.tracking_number,
                    tracking_url = excluded.tracking_url,
                    updated_at = CURRENT_TIMESTAMP
            ''', (
                order['shopify_order_id'],
                order['order_number'],
                order.get('fulfillment_status', 'unfulfilled'),
                order['created_at'],
                order.get('tracking_number', ''),
                order.get('tracking_url', ''),
            ))
        LOGGER.debug(f"Upserted order {order['shopify_order_id']} (#{order['order_number']})")

    def get_order(self, shopify_order_id: int) -> Optional[Dict]:
        """Get a single order by Shopify order ID."""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                'SELECT * FROM orders WHERE shopify_order_id = ?',
                (shopify_order_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_unfulfilled_orders(self) -> List[Dict]:
        """Get all orders that are not yet fulfilled."""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM orders WHERE fulfillment_status != 'fulfilled' ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_unsubmitted_orders(self) -> List[Dict]:
        """Get orders not yet submitted to Wimood for dropshipping."""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM orders WHERE dropship_submitted = 0 "
                "AND fulfillment_status != 'fulfilled' ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_submitted_unfulfilled(self) -> List[Dict]:
        """Get orders submitted to Wimood but not yet fulfilled in Shopify."""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM orders WHERE dropship_submitted = 1 "
                "AND fulfillment_status != 'fulfilled' ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_submitted(self, shopify_order_id: int, wimood_order_id: int):
        """Mark an order as submitted to Wimood."""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute('''
                UPDATE orders SET
                    dropship_submitted = 1,
                    wimood_order_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE shopify_order_id = ?
            ''', (wimood_order_id, shopify_order_id))
        LOGGER.info(f"Order {shopify_order_id} marked as submitted (Wimood ID: {wimood_order_id})")

    def update_wimood_status(self, shopify_order_id: int, wimood_status: str,
                             tracking_number: str = '', tracking_url: str = ''):
        """Update Wimood order status and tracking info."""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute('''
                UPDATE orders SET
                    wimood_status = ?,
                    tracking_number = ?,
                    tracking_url = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE shopify_order_id = ?
            ''', (wimood_status, tracking_number, tracking_url, shopify_order_id))
        LOGGER.debug(f"Updated Wimood status for order {shopify_order_id}: {wimood_status}")

    def update_fulfillment(self, shopify_order_id: int, fulfillment_status: str,
                           tracking_number: str = '', tracking_url: str = ''):
        """Update fulfillment status and tracking info for an order."""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute('''
                UPDATE orders SET
                    fulfillment_status = ?,
                    tracking_number = ?,
                    tracking_url = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE shopify_order_id = ?
            ''', (fulfillment_status, tracking_number, tracking_url, shopify_order_id))
        LOGGER.debug(f"Updated order {shopify_order_id} fulfillment: {fulfillment_status}")

    def get_all_orders(self) -> List[Dict]:
        """Get all orders."""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute('SELECT * FROM orders ORDER BY created_at DESC').fetchall()
        return [dict(row) for row in rows]

    def __len__(self):
        with sqlite3.connect(self.db_file) as conn:
            row = conn.execute('SELECT COUNT(*) FROM orders').fetchone()
        return row[0]
