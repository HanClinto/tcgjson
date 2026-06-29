"""TCGplayer catalog client.

The endpoints mirror the catalog-specific code proven in the sibling
`ccg_card_id` project, with listing/photo APIs intentionally left out of this
package's core path.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests


CATALOG_API_BASE = "https://mpapi.tcgplayer.com"
SEARCH_API_BASE = "https://mp-search-api.tcgplayer.com"
INFINITE_API_BASE = "https://infinite-api.tcgplayer.com"


class TCGplayerError(RuntimeError):
    """Raised when TCGplayer returns an unexpected response."""


@dataclass(frozen=True, slots=True)
class RequestStats:
    requests: int
    retries: int
    errors: int


class TCGplayerClient:
    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        timeout: int = 30,
        max_retries: int = 5,
        retry_backoff_seconds: float = 1.5,
        rate_limit_delay: float = 0.0,
        user_agent: str = "tcgjson/0.1 (+https://github.com/HanClinto/tcgjson)",
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.rate_limit_delay = rate_limit_delay
        self.requests = 0
        self.retries = 0
        self.errors = 0
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "application/json"})

    def stats(self) -> RequestStats:
        return RequestStats(self.requests, self.retries, self.errors)

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                if self.rate_limit_delay:
                    time.sleep(self.rate_limit_delay)
                self.requests += 1
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
                if response.status_code >= 500:
                    raise requests.HTTPError(
                        f"{response.status_code} Server Error for url: {response.url}",
                        response=response,
                    )
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type:
                    raise TCGplayerError(f"Expected JSON from {url}, got {content_type}")
                return response.json()
            except (requests.RequestException, TCGplayerError) as exc:
                last_error = exc
                response = getattr(exc, "response", None)
                status_code = getattr(response, "status_code", None)
                retryable = status_code is None or status_code >= 500 or isinstance(
                    exc, (requests.ConnectionError, requests.Timeout)
                )
                if not retryable or attempt >= self.max_retries:
                    self.errors += 1
                    raise
                self.retries += 1
                time.sleep(self.retry_backoff_seconds * attempt)
        if last_error is not None:
            raise last_error
        raise TCGplayerError(f"Request failed without an error object: {method} {url}")

    @staticmethod
    def _unwrap_results(payload: Any) -> Any:
        if isinstance(payload, dict) and "results" in payload:
            errors = payload.get("errors") or []
            if errors:
                raise TCGplayerError(f"TCGplayer returned errors: {errors}")
            return payload["results"]
        return payload

    def get_product_lines(self) -> list[dict[str, Any]]:
        payload = self._request("GET", f"{SEARCH_API_BASE}/v1/search/productLines")
        if not isinstance(payload, list):
            raise TCGplayerError("Unexpected product lines payload")
        return payload

    def get_set_names(self, product_line_id: int | str, *, active: bool = True) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            f"{CATALOG_API_BASE}/v2/Catalog/SetNames",
            params={"categoryId": product_line_id, "active": str(active).lower()},
        )
        return list(self._unwrap_results(payload))

    def get_priceguide_set_cards(
        self,
        set_id: int | str,
        *,
        rows: int = 5000,
        product_type_id: int = 1,
    ) -> dict[str, Any]:
        payload = self._request(
            "GET",
            f"{INFINITE_API_BASE}/priceguide/set/{set_id}/cards/",
            params={"rows": rows, "productTypeID": product_type_id},
        )
        if not isinstance(payload, dict):
            raise TCGplayerError("Unexpected price guide payload")
        return payload

    def get_product_details(self, product_id: int | str) -> dict[str, Any]:
        payload = self._request("GET", f"{SEARCH_API_BASE}/v2/product/{product_id}/details")
        if not isinstance(payload, dict):
            raise TCGplayerError("Unexpected product details payload")
        return payload

    @staticmethod
    def product_image_url(product_id: int | str, *, size: str = "1000x1000") -> str:
        return f"https://tcgplayer-cdn.tcgplayer.com/product/{product_id}_in_{size}.jpg"
