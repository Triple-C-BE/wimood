# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Wimood-to-Shopify product sync service. A Python daemon that periodically fetches product data (SKU, title, price, stock) from Wimood's XML API and syncs it to a Shopify store. Currently the Wimood API integration is implemented; Shopify sync and web scraping enrichment are scaffolded but not yet active.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the sync service (loops every SYNC_INTERVAL_SECONDS, default 3600)
python main.py
```

No test framework or linter is configured yet.

## Architecture

**Entry point:** `main.py` — runs an infinite loop: load env → init logging → init request manager → fetch Wimood products → (future: enrich via scraping, sync to Shopify) → sleep.

**`integrations/`** — External API clients.
- `wimood_api.py`: `WimoodAPI` class fetches XML product feed, parses it into dicts with keys: `sku`, `title`, `price`, `stock`. Uses `RequestManager` for HTTP with retries.

**`utils/`** — Shared utilities, all re-exported from `utils/__init__.py`.
- `env.py`: `load_env_variables()` validates and returns all config from `.env`. Supports type casting (str/int/bool). Required vars cause `SystemExit` if missing.
- `logger.py`: `init_logging_config()` sets up file + optional stdout logging. `get_logger(name)` creates per-module loggers. `get_main_logger()` returns the main logger.
- `request_manager.py`: `RequestManager` wraps `requests.Session` with retry logic (backoff, status code retries on 429/5xx), user-agent rotation from `config/user_agents.yaml` (falls back to default).
- `formatter.py`: `format_seconds_to_human_readable()` for log messages.

## Environment Variables

Configured via `.env` file (loaded by python-dotenv).

**Required:** `WIMOOD_API_KEY`, `WIMOOD_API_URL`, `WIMOOD_BASE_URL`, `WIMOOD_CUSTOMER_ID`, `SHOPIFY_SHOP_NAME`, `SHOPIFY_API_KEY`, `SHOPIFY_API_PASSWORD`

**Optional (with defaults):** `LOG_DIR` (logs), `LOG_LEVEL` (INFO), `LOG_TO_STDOUT` (true), `SYNC_INTERVAL_SECONDS` (3600), `MAX_SCRAPE_RETRIES` (5), `SHOPIFY_VENDOR_TAG` (Wimood_Sync)

## Dependencies

Python 3.13. Packages: `python-dotenv`, `requests`, `PyYAML`.