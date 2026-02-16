# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Wimood-to-Shopify product sync service.
A Python daemon that periodically fetches product data (SKU, title, price, stock) from Wimood's XML API, optionally enriches it by scraping product pages (images, descriptions, specs), and syncs it to a Shopify store. Also supports polling Shopify orders for fulfillment status tracking.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the sync service (loops every PRODUCT_SYNC_INTERVAL_SECONDS, default 3600)
python main.py

# Run tests
pytest tests/ -v

# Lint
ruff check .
```

## Architecture

**Entry point:** `main.py` — initializes managers and runs pre-flight checks once at startup, then runs a dual-timer loop: product sync (fetch Wimood → enrich → sync to Shopify) and optional order sync (poll Shopify orders for fulfillment updates). Each sync has its own interval.

**`integrations/`** — External API clients.
- `wimood_api.py`: `WimoodAPI` class fetches XML product feed, parses it into dicts with keys: `product_id`, `sku`, `title`, `brand`, `ean`, `price`, `msrp`, `stock`.
- `wimood_scraper.py`: `WimoodScraper` class scrapes wimoodshop.nl product pages. Extracts images (from gallery), description (from "Omschrijving" section), and specs (from "Specificaties" table). Rate-limited with configurable delay.
- `shopify_api.py`: `ShopifyAPI` class handles CRUD operations. Creates/updates products with enriched data (body_html, images, metafields for brand/ean/msrp/specs). Caches location_id for inventory updates.
- `shopify_sync.py`: `sync_products()` orchestrates the sync — fetches Shopify products first, cleans stale mappings, then enriches new products via scraping, then create/update/deactivate products. Compares title, price, cost, status, body_html, and image count to detect changes.
- `order_sync.py`: `sync_orders()` orchestrates order polling — fetches unfulfilled orders from Shopify, stores them in SQLite, polls for fulfillment status updates and tracking info.

**`utils/`** — Shared utilities, all re-exported from `utils/__init__.py`.
- `env.py`: `load_env_variables()` validates and returns all config from `.env`. Supports type casting (str/int/bool). Required vars cause `SystemExit` if missing.
- `logger.py`: `init_logging_config()` sets up file + optional stdout logging. `get_logger(name)` creates per-module loggers. `get_main_logger()` returns the main logger.
- `request_manager.py`: `RequestManager` wraps `requests.Session` with retry logic (backoff, status code retries on 429/5xx), user-agent rotation from `config/user_agents.yaml`.
- `scrape_cache.py`: `ScrapeCache` class provides JSON-file-based caching (`data/scrape_cache.json`) for scraped product data. Supports staleness checking (default 7 days). Uses atomic writes.
- `formatter.py`: `format_seconds_to_human_readable()` for log messages.
- `order_store.py`: `OrderStore` class provides SQLite-based storage (`data/order_store.db`) for Shopify orders. Tracks fulfillment status and tracking information.
- `monitor.py`: `MonitorServer` class runs a lightweight HTTP server in a daemon thread. Serves JSON sync status at `GET /` or `/status`. Thread-safe state updates via `set_running()`, `update_status()`, and `update_order_status()`.

**`tests/`** — Unit tests using pytest + pytest-mock.

## Environment Variables

Configured via `.env` file (loaded by python-dotenv). See `.env.example` for full reference.

**Required:** `WIMOOD_API_KEY`, `WIMOOD_API_URL`, `WIMOOD_BASE_URL`, `WIMOOD_CUSTOMER_ID`, `SHOPIFY_STORE_URL`, `SHOPIFY_ACCESS_TOKEN`

**Optional (with defaults):** `LOG_DIR` (logs), `LOG_LEVEL` (INFO), `LOG_TO_STDOUT` (true), `PRODUCT_SYNC_INTERVAL_SECONDS` (3600), `MAX_SCRAPE_RETRIES` (5), `SHOPIFY_VENDOR_TAG` (Wimood_Sync), `SCRAPE_DELAY_SECONDS` (2), `ENABLE_MONITORING` (false), `MONITOR_PORT` (8080), `TEST_MODE` (false), `TEST_PRODUCT_LIMIT` (5)

## Dependencies

Python 3.13. Packages: `python-dotenv`, `requests`, `PyYAML`, `beautifulsoup4`, `lxml`. Dev: `pytest`, `pytest-mock`, `ruff`.
