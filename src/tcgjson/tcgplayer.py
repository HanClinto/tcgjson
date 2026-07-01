"""TCGplayer catalog client.

The endpoints mirror the catalog-specific code proven in the sibling
`ccg_card_id` project, with listing/photo APIs intentionally left out of this
package's core path.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .atomic import atomic_write_json


CATALOG_API_BASE = "https://mpapi.tcgplayer.com"
SEARCH_API_BASE = "https://mp-search-api.tcgplayer.com"
INFINITE_API_BASE = "https://infinite-api.tcgplayer.com"
NAVIGATION_API_BASE = "https://marketplace-navigation.tcgplayer.com"
TCGPLAYER_SINGLES_PRODUCT_TYPE_ID = 1
SEARCH_PAGE_SIZE_LIMIT = 50


class TCGplayerError(RuntimeError):
    """Raised when TCGplayer returns an unexpected response."""


@dataclass(frozen=True, slots=True)
class RequestStats:
    requests: int
    retries: int
    errors: int
    cache_hits: int = 0


class TCGplayerClient:
    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        timeout: int = 30,
        max_retries: int = 5,
        retry_backoff_seconds: float = 1.5,
        rate_limit_delay: float = 0.0,
        request_cache_dir: Path | None = None,
        request_cache_ttl_seconds: int = 24 * 60 * 60,
        user_agent: str = "tcgjson/0.1 (+https://github.com/HanClinto/tcgjson)",
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.rate_limit_delay = rate_limit_delay
        self.request_cache_dir = request_cache_dir
        self.request_cache_ttl_seconds = request_cache_ttl_seconds
        self.requests = 0
        self.retries = 0
        self.errors = 0
        self.cache_hits = 0
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "application/json"})

    def stats(self) -> RequestStats:
        return RequestStats(self.requests, self.retries, self.errors, self.cache_hits)

    def _request_cache_path(self, method: str, url: str, kwargs: dict[str, Any]) -> Path | None:
        if self.request_cache_dir is None or self.request_cache_ttl_seconds <= 0:
            return None
        cache_key = json.dumps(
            {
                "method": method.upper(),
                "url": url,
                "params": kwargs.get("params") or {},
                "json": kwargs.get("json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
        return self.request_cache_dir / f"{digest}.json"

    def _load_request_cache(self, path: Path | None) -> Any | None:
        if path is None or not path.exists():
            return None
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        expires_at = cached.get("expiresAt", "")
        if expires_at <= dt.datetime.now(dt.timezone.utc).isoformat():
            return None
        self.cache_hits += 1
        return cached.get("payload")

    def _write_request_cache(self, path: Path | None, payload: Any) -> None:
        if path is None:
            return
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=self.request_cache_ttl_seconds)
        atomic_write_json(
            path,
            {
                "object": "tcgjson_request_cache_entry",
                "version": 1,
                "expiresAt": expires_at.isoformat(),
                "payload": payload,
            },
        )

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        cache_path = self._request_cache_path(method, url, kwargs)
        cached_payload = self._load_request_cache(cache_path)
        if cached_payload is not None:
            return cached_payload
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
                payload = response.json()
                self._write_request_cache(cache_path, payload)
                return payload
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

    def get_popular_games(self) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            f"{NAVIGATION_API_BASE}/marketplace-navigation-search-feature.json",
        )
        categories = payload.get("categories") if isinstance(payload, dict) else None
        if not isinstance(categories, list):
            raise TCGplayerError("Navigation payload missing categories")
        return categories

    def get_latest_sets(self, product_line_id: int | str) -> list[dict[str, Any]]:
        payload = self._request("GET", f"{SEARCH_API_BASE}/v1/product/latestsets/{product_line_id}")
        if not isinstance(payload, list):
            raise TCGplayerError("Unexpected latest sets payload")
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
        product_type_id: int = TCGPLAYER_SINGLES_PRODUCT_TYPE_ID,
    ) -> dict[str, Any]:
        payload = self._request(
            "GET",
            f"{INFINITE_API_BASE}/priceguide/set/{set_id}/cards/",
            params={"rows": rows, "productTypeID": product_type_id},
        )
        if not isinstance(payload, dict):
            raise TCGplayerError("Unexpected price guide payload")
        return payload

    def search_products(
        self,
        *,
        product_line_name: str,
        set_name: str | None = None,
        offset: int = 0,
        size: int = SEARCH_PAGE_SIZE_LIMIT,
        algorithm: str = "sales_exp_fields_synonym",
        range_filters: dict[str, Any] | None = None,
        sort: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        term_filters: dict[str, list[str]] = {
            "productLineName": [product_line_name],
            "productTypeName": ["Cards"],
        }
        if set_name:
            term_filters["setName"] = [set_name]
        payload = {
            "algorithm": algorithm,
            "from": offset,
            "size": size,
            "filters": {
                "term": term_filters,
                "range": range_filters or {},
                "match": {},
            },
            "context": {"cart": {}, "shippingCountry": "US", "userProfile": {}},
            "settings": {"useFuzzySearch": False, "didYouMean": {}},
            "sort": sort or {},
        }
        raw = self._request("POST", f"{SEARCH_API_BASE}/v1/search/request", json=payload)
        results = self._unwrap_results(raw)
        if not results:
            return {"results": [], "totalResults": 0}
        if len(results) != 1:
            raise TCGplayerError(f"Expected one search result envelope, got {len(results)}")
        return results[0]

    def iter_search_products(
        self,
        *,
        product_line_name: str,
        set_name: str | None = None,
        page_size: int = SEARCH_PAGE_SIZE_LIMIT,
        algorithm: str = "sales_exp_fields_synonym",
        range_filters: dict[str, Any] | None = None,
        sort: dict[str, str] | None = None,
    ):
        offset = 0
        total_results: int | None = None
        while True:
            page = self.search_products(
                product_line_name=product_line_name,
                set_name=set_name,
                offset=offset,
                size=page_size,
                algorithm=algorithm,
                range_filters=range_filters,
                sort=sort,
            )
            products = list(page.get("results") or [])
            if total_results is None:
                total_results = int(page.get("totalResults") or 0)
            if not products:
                break
            yield from products
            offset += len(products)
            if offset >= total_results:
                break

    def get_product_details(self, product_id: int | str) -> dict[str, Any]:
        payload = self._request("GET", f"{SEARCH_API_BASE}/v2/product/{product_id}/details")
        if not isinstance(payload, dict):
            raise TCGplayerError("Unexpected product details payload")
        return payload

    @staticmethod
    def product_image_url(product_id: int | str, *, size: str = "1000x1000", image_number: int | None = None) -> str:
        image_suffix = f"_{image_number}" if image_number is not None else ""
        return f"https://tcgplayer-cdn.tcgplayer.com/product/{product_id}{image_suffix}_in_{size}.jpg"

    @classmethod
    def product_image_urls(cls, product_id: int | str, image_count: int, *, size: str = "1000x1000") -> list[str]:
        if image_count <= 1:
            return [cls.product_image_url(product_id, size=size)]
        return [cls.product_image_url(product_id, size=size), *[
            cls.product_image_url(product_id, size=size, image_number=index) for index in range(1, image_count)
        ]]
