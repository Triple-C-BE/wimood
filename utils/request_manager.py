import logging
import random
from pathlib import Path
from typing import Dict, List, Optional

import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger('request_manager')


def load_user_agents(path: str = "config/user_agents.yaml") -> List[str]:
    """Loads a list of user agents from a YAML file."""
    try:
        # Assuming the config directory is relative to the project root
        with open(Path(path), "r") as f:
            data = yaml.safe_load(f)
        return data.get("user_agents", [])
    except Exception:
        # Return a safe default on failure
        return ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"]

USER_AGENTS = load_user_agents()


class RequestManager:
    """
    Manages HTTP requests with retries, backoff, and user-agent rotation.
    Proxies/Sockets have been removed per project requirement.
    """

    def __init__(self, max_retries: int = 3, backoff_factor: float = 0.5):
        """
        Initializes the RequestManager with a requests.Session.
        """
        self.session = requests.Session()
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        self._configure_retries()

    def _configure_retries(self):
        """Sets up the HTTPAdapter with retry logic for the session."""

        # Configure the Retry object
        # status_forcelist: Which HTTP status codes to retry on (e.g., server errors)
        # allowed_methods: Which request methods to retry
        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=self.backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE"]
        )

        # Attach the retry strategy to the Session via an adapter
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _get_random_headers(self) -> Dict[str, str]:
        """Generates random headers with a rotated User-Agent."""
        return {
            "User-Agent": random.choice(USER_AGENTS) if USER_AGENTS else "Mozilla/5.0",
            "Connection": "keep-alive",
        }

    def request(
            self,
            method: str,
            url: str,
            timeout: int = 30,  # Increased timeout for robustness
            **kwargs
    ) -> Optional[requests.Response]:
        """
        Wrapper around requests.Session.request.

        Args:
            method: The HTTP method (e.g., 'GET', 'POST').
            url: The URL to request.
            timeout: Request timeout in seconds.
            **kwargs: Additional arguments for requests.request.

        Returns:
            The requests.Response object on success, or None if all retries fail.
        """

        # Merge auto-rotated headers with any custom headers passed in kwargs
        default_headers = self._get_random_headers()

        # Give kwargs['headers'] priority, then remove from kwargs to avoid duplication
        if 'headers' in kwargs:
            headers = {**default_headers, **kwargs.pop('headers')}
        else:
            headers = default_headers

        try:
            response = self.session.request(
                method=method,
                url=url,
                headers=headers,
                timeout=timeout,
                **kwargs
            )

            # The HTTPAdapter handles 5xx and 429 status codes internally via retries.
            # We explicitly check for other permanent failure codes here.
            response.raise_for_status()

            return response

        except requests.exceptions.HTTPError as e:
            # Log the status code and response body for non-2xx responses
            resp = e.response
            if resp is not None:
                LOGGER.error(
                    f"HTTP {resp.status_code} for {method} {url} — "
                    f"Body: {resp.text[:500]}"
                )
            else:
                LOGGER.error(f"HTTP error for {method} {url}: {e}")
            return None

        except requests.exceptions.RequestException as e:
            LOGGER.error(f"Request failed after all retries for {method} {url}: {e}")
            return None


def init_request_manager(env_config: dict) -> RequestManager:
    """Creates a RequestManager instance based on the loaded ENV configuration."""

    # Use the validated ENV variables
    max_retries = env_config.get('MAX_SCRAPE_RETRIES', 5)  # Use your new ENV key

    # You might want a separate BACKOFF_FACTOR in ENV, or use a sensible default
    backoff_factor = 0.5

    return RequestManager(
        max_retries=max_retries,
        backoff_factor=backoff_factor
    )
