"""Build bulk catalog files and manifests."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import mimetypes
import time
from pathlib import Path
from typing import Any, Iterable, TypeVar

import requests

from .atomic import atomic_write_json, atomic_write_text
from .config import normalize_key, product_line_for_id, product_line_for_name
from .games import default_enabled_product_line_ids
from .normalize import (
    apply_product_details,
    apply_search_product_metadata,
    compact_product,
    group_priceguide_products,
    normalize_search_products,
)
from .schema import product_schema_markdown, product_schema_profile
from .search_cache import SearchProductCache
from .tcgplayer import RequestStats, TCGplayerClient, TCGplayerError


T = TypeVar("T")
SET_CHECKPOINT_VERSION = 2


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _utc_timestamp_iso(timestamp: float) -> str:
    return (
        dt.datetime.fromtimestamp(timestamp, dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _refresh_recent_after(days: int) -> dt.date | None:
    if days <= 0:
        return None
    return dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=days)


def _search_row_release_date(row: dict[str, Any]) -> dt.date | None:
    custom_attributes = row.get("customAttributes") if isinstance(row.get("customAttributes"), dict) else {}
    value = custom_attributes.get("releaseDate") or row.get("releaseDate") or ""
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _stats_delta(before: RequestStats, after: RequestStats) -> dict[str, int]:
    return {
        "requests": after.requests - before.requests,
        "retries": after.retries - before.retries,
        "errors": after.errors - before.errors,
        "cacheHits": after.cache_hits - before.cache_hits,
    }


def _stats_dict(stats: RequestStats) -> dict[str, int]:
    return {"requests": stats.requests, "retries": stats.retries, "errors": stats.errors, "cacheHits": stats.cache_hits}


def _progress(iterable: Iterable[T], *, enabled: bool, **kwargs: Any) -> Iterable[T]:
    if not enabled:
        return iterable
    try:
        from tqdm import tqdm
    except ImportError:
        return iterable
    return tqdm(iterable, **kwargs)


ProductLineRequest = int | str


def _coerce_product_line_id(value: ProductLineRequest) -> int | None:
    if isinstance(value, int):
        return value
    return int(value) if value.isdecimal() else None


def _resolve_product_line(client: TCGplayerClient, requested_product_line: ProductLineRequest) -> dict[str, Any]:
    requested_id = _coerce_product_line_id(requested_product_line)
    if requested_id is not None:
        for row in client.get_product_lines():
            if int(row["productLineId"]) == requested_id:
                return row
        raise TCGplayerError(f"Unknown TCGplayer product line ID: {requested_id}")

    requested_name = str(requested_product_line)
    requested = product_line_for_name(requested_name)
    wanted = {normalize_key(requested.name), normalize_key(requested.slug)}
    wanted.update(normalize_key(alias) for alias in requested.aliases)
    for row in client.get_product_lines():
        candidates = [row.get("productLineName", ""), row.get("productLineUrlName", "")]
        if any(
            key == normalize_key(candidate)
            or key in normalize_key(candidate)
            or normalize_key(candidate) in key
            for key in wanted
            for candidate in candidates
        ):
            return row
    raise TCGplayerError(f"Unknown TCGplayer product line: {requested_name}")


def _load_cached_catalog(cache_dir: Path | None, slug: str) -> dict[str, Any] | None:
    if cache_dir is None:
        return None
    path = cache_dir / f"{slug}.full.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _set_checkpoint_path(checkpoint_dir: Path, slug: str, source: str, set_id: int) -> Path:
    return checkpoint_dir / slug / source / f"{set_id}.json"


def _load_set_checkpoint(
    checkpoint_dir: Path | None,
    *,
    slug: str,
    product_line_id: int,
    set_id: int,
    with_skus: bool,
    priceguide_rows: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    if checkpoint_dir is None:
        return None
    paths = [
        _set_checkpoint_path(checkpoint_dir, slug, "priceguide", set_id),
        _set_checkpoint_path(checkpoint_dir, slug, "search", set_id),
        checkpoint_dir / slug / f"{set_id}.json",
    ]
    path = next((candidate for candidate in paths if candidate.exists()), None)
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    source = payload.get("source") or payload.get("set", {}).get("source")
    if (
        payload.get("object") != "tcgjson_set_checkpoint"
        or int(payload.get("version") or 0) != SET_CHECKPOINT_VERSION
        or int(payload.get("productLineId") or 0) != product_line_id
        or int(payload.get("tcgplayerSetId") or 0) != set_id
        or bool(payload.get("withSkus")) != with_skus
        or int(payload.get("priceguideRows") or 0) != priceguide_rows
        or source not in (None, "priceguide", "search")
    ):
        return None
    set_summary = payload.get("set")
    products = payload.get("products")
    if not isinstance(set_summary, dict) or not isinstance(products, list):
        return None
    return set_summary, [_migrate_cached_product(product, product_line_id) for product in products]


def _write_set_checkpoint(
    checkpoint_dir: Path | None,
    *,
    slug: str,
    product_line_id: int,
    set_summary: dict[str, Any],
    products: list[dict[str, Any]],
    with_skus: bool,
    priceguide_rows: int,
) -> None:
    if checkpoint_dir is None:
        return
    set_id = int(set_summary["tcgplayerSetId"])
    source = set_summary.get("source", "unknown")
    atomic_write_json(
        _set_checkpoint_path(checkpoint_dir, slug, source, set_id),
        {
            "object": "tcgjson_set_checkpoint",
            "version": SET_CHECKPOINT_VERSION,
            "generatedAt": _utc_now_iso(),
            "source": source,
            "productLineId": product_line_id,
            "slug": slug,
            "tcgplayerSetId": set_id,
            "withSkus": with_skus,
            "priceguideRows": priceguide_rows,
            "set": set_summary,
            "products": products,
        },
    )


def _product_detail_cache_path(detail_cache_dir: Path, product_id: int | str) -> Path:
    product_id_text = str(product_id)
    leaf_bucket = product_id_text[-3:]
    parent_bucket = product_id_text[-6:-3] or "0"
    return detail_cache_dir / parent_bucket / leaf_bucket / f"{product_id_text}.json"


def _load_product_detail_cache(detail_cache_dir: Path | None, product_id: int | str) -> dict[str, Any] | None:
    if detail_cache_dir is None:
        return None
    path = _product_detail_cache_path(detail_cache_dir, product_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        payload.get("object") != "tcgjson_product_detail_cache_entry"
        or int(payload.get("tcgplayerProductId") or 0) != int(product_id)
        or not isinstance(payload.get("details"), dict)
    ):
        return None
    return payload["details"]


def _write_product_detail_cache(detail_cache_dir: Path | None, product_id: int | str, details: dict[str, Any]) -> None:
    if detail_cache_dir is None:
        return
    atomic_write_json(
        _product_detail_cache_path(detail_cache_dir, product_id),
        {
            "object": "tcgjson_product_detail_cache_entry",
            "version": 1,
            "generatedAt": _utc_now_iso(),
            "tcgplayerProductId": int(product_id),
            "details": details,
        },
    )


def _recent_set_ids(set_rows: list[dict[str, Any]], refresh_recent_sets: int) -> set[int]:
    if refresh_recent_sets <= 0:
        return set()
    sorted_rows = sorted(
        set_rows,
        key=lambda row: (row.get("releaseDate") or "", int(row.get("setNameId") or 0)),
    )
    return {int(row["setNameId"]) for row in sorted_rows[-refresh_recent_sets:]}


def _cached_products_have_skus(products: list[dict[str, Any]]) -> bool:
    return all("skus" in product for product in products)


def _migrate_cached_product(product: dict[str, Any], product_line_id: int) -> dict[str, Any]:
    migrated = dict(product)
    old_product_line = migrated.pop("productLine", {})
    if "productLineId" not in migrated:
        old_product_line_id = old_product_line.get("id") if isinstance(old_product_line, dict) else None
        migrated["productLineId"] = int(old_product_line_id or product_line_id)
    else:
        migrated.pop("productLine", None)

    old_set = migrated.pop("set", {})
    if "setId" not in migrated:
        old_set_id = old_set.get("id") if isinstance(old_set, dict) else None
        migrated["setId"] = int(old_set_id or 0)
    else:
        migrated.pop("set", None)

    if "imageUrls" not in migrated:
        image_url = migrated.get("imageUrl", "")
        migrated["imageUrls"] = [image_url] if image_url else []
    migrated.pop("imageUrl", None)
    return migrated


def _fetch_set_products(
    client: TCGplayerClient,
    *,
    product_line_name: str,
    product_line_id: int,
    product_line_url_name: str,
    set_row: dict[str, Any],
    priceguide_rows: int,
    with_skus: bool,
    progress: bool,
    detail_cache_dir: Path | None,
    search_cache: SearchProductCache | None,
    search_cache_refresh_recent_days: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    priceguide = client.get_priceguide_set_cards(set_row["setNameId"], rows=priceguide_rows)
    rows = list(priceguide.get("result") or [])
    source = "priceguide"
    search_metadata_product_count = 0
    search_metadata_error_count = 0
    search_metadata_cache_hit = False
    search_metadata_cache_write_count = 0

    def search_rows_for_set() -> list[dict[str, Any]]:
        nonlocal search_metadata_cache_hit, search_metadata_cache_write_count
        refresh_after = _refresh_recent_after(search_cache_refresh_recent_days)
        if search_cache is not None:
            cached_rows = search_cache.get_set_rows(
                product_line_id=product_line_id,
                set_id=int(set_row["setNameId"]),
                set_name=set_row.get("name", ""),
                refresh_recent_after=refresh_after,
            )
            if cached_rows is not None:
                search_metadata_cache_hit = True
                return cached_rows
        fetched_rows = list(
            client.iter_search_products(
                product_line_name=product_line_name,
                set_name=set_row.get("name", ""),
            )
        )
        if search_cache is not None:
            search_metadata_cache_write_count += search_cache.upsert_search_rows(
                fetched_rows,
                product_line_id=product_line_id,
                product_line_name=product_line_name,
            )
        return fetched_rows

    if rows:
        set_products = group_priceguide_products(
            rows,
            product_line_name=product_line_name,
            product_line_id=product_line_id,
            product_line_url_name=product_line_url_name,
            set_row=set_row,
        )
        if not with_skus:
            products_by_id = {product["tcgplayerProductId"]: product for product in set_products}
            try:
                for search_row in search_rows_for_set():
                    product_id = int(search_row.get("productId") or 0)
                    product = products_by_id.get(product_id)
                    if product is None:
                        continue
                    had_metadata = "metadata" in product
                    apply_search_product_metadata(product, search_row)
                    if "metadata" in product and not had_metadata:
                        search_metadata_product_count += 1
            except (requests.RequestException, TCGplayerError):
                search_metadata_error_count += 1
    else:
        search_rows = search_rows_for_set()
        set_products = normalize_search_products(
            search_rows,
            product_line_name=product_line_name,
            product_line_id=product_line_id,
            product_line_url_name=product_line_url_name,
            set_row=set_row,
        )
        search_metadata_product_count = sum(1 for product in set_products if "metadata" in product)
        source = "search"
    detail_error_count = 0
    detail_cache_hit_count = 0
    detail_fetch_count = 0
    if with_skus:
        detail_iterator = _progress(
            set_products,
            enabled=progress,
            desc=f"{set_row.get('name', set_row['setNameId'])} details",
            unit="product",
            leave=False,
            position=2,
        )
        for product in detail_iterator:
            product_id = product["tcgplayerProductId"]
            try:
                details = _load_product_detail_cache(detail_cache_dir, product_id)
                if details is None:
                    details = client.get_product_details(product_id)
                    _write_product_detail_cache(detail_cache_dir, product_id, details)
                    detail_fetch_count += 1
                else:
                    detail_cache_hit_count += 1
            except (requests.RequestException, TCGplayerError):
                detail_error_count += 1
                continue
            apply_product_details(product, details)
    return (
        {
            "tcgplayerSetId": int(set_row["setNameId"]),
            "name": set_row.get("name", ""),
            "urlName": set_row.get("urlName", ""),
            "abbreviation": set_row.get("abbreviation", ""),
            "releaseDate": set_row.get("releaseDate", ""),
            "isSupplemental": bool(set_row.get("isSupplemental")),
            "productCount": len(set_products),
            "priceGuideRowCount": len(rows),
            "detailErrorCount": detail_error_count,
            "detailCacheHitCount": detail_cache_hit_count,
            "detailFetchCount": detail_fetch_count,
            "searchMetadataProductCount": search_metadata_product_count,
            "searchMetadataErrorCount": search_metadata_error_count,
            "searchMetadataCacheHit": search_metadata_cache_hit,
            "searchMetadataCacheWriteCount": search_metadata_cache_write_count,
            "source": source,
        },
        set_products,
    )


def fetch_product_line(
    client: TCGplayerClient,
    product_line_name: ProductLineRequest,
    *,
    max_sets: int | None = None,
    priceguide_rows: int = 5000,
    with_skus: bool = False,
    cache_dir: Path | None = None,
    refresh_recent_sets: int = 0,
    progress: bool = False,
    checkpoint_dir: Path | None = None,
    detail_cache_dir: Path | None = None,
    search_cache: SearchProductCache | None = None,
    search_cache_refresh_recent_days: int = 45,
) -> dict[str, Any]:
    started = time.perf_counter()
    product_line = _resolve_product_line(client, product_line_name)
    product_line_id = int(product_line["productLineId"])
    resolved = product_line_for_id(product_line_id, product_line.get("productLineName", ""))
    product_line_url_name = product_line.get("productLineUrlName", "")
    set_rows = client.get_set_names(product_line_id)
    if max_sets is not None:
        set_rows = set_rows[:max_sets]

    exported_at = _utc_now_iso()
    cached_catalog = _load_cached_catalog(cache_dir, resolved.slug)
    cached_sets = {
        int(set_payload["tcgplayerSetId"]): set_payload
        for set_payload in (cached_catalog or {}).get("sets", [])
    }
    cached_products: dict[int, list[dict[str, Any]]] = {}
    for product in (cached_catalog or {}).get("products", []):
        migrated_product = _migrate_cached_product(product, product_line_id)
        set_id = int(migrated_product.get("setId") or 0)
        cached_products.setdefault(set_id, []).append(migrated_product)
    refresh_ids = _recent_set_ids(set_rows, refresh_recent_sets)
    sets = []
    products = []
    reused_sets = 0
    reused_checkpoint_sets = 0
    fetched_sets = 0
    recent_search_cache_rows = 0
    recent_search_cache_changed_rows = 0
    if search_cache is not None:
        recent_search_cache_rows, recent_search_cache_changed_rows = _refresh_recent_search_cache(
            client,
            search_cache,
            product_line_name=product_line.get("productLineName", resolved.name),
            product_line_id=product_line_id,
            refresh_recent_days=search_cache_refresh_recent_days,
        )
    set_iterator = _progress(
        set_rows,
        enabled=progress,
        desc=f"{resolved.slug} sets",
        unit="set",
        leave=False,
        position=1,
    )
    for set_row in set_iterator:
        set_id = int(set_row["setNameId"])
        cached_set_products = cached_products.get(set_id, [])
        can_reuse = (
            set_id in cached_sets
            and cached_set_products
            and set_id not in refresh_ids
            and (not with_skus or _cached_products_have_skus(cached_set_products))
        )
        if can_reuse:
            sets.append(cached_sets[set_id])
            set_products = cached_set_products
            reused_sets += 1
        else:
            checkpoint = _load_set_checkpoint(
                checkpoint_dir,
                slug=resolved.slug,
                product_line_id=product_line_id,
                set_id=set_id,
                with_skus=with_skus,
                priceguide_rows=priceguide_rows,
            )
            if checkpoint is not None:
                set_summary, set_products = checkpoint
                reused_checkpoint_sets += 1
            else:
                set_summary, set_products = _fetch_set_products(
                    client,
                    product_line_name=product_line.get("productLineName", resolved.name),
                    product_line_id=product_line_id,
                    product_line_url_name=product_line_url_name,
                    set_row=set_row,
                    priceguide_rows=priceguide_rows,
                    with_skus=with_skus,
                    progress=progress,
                    detail_cache_dir=detail_cache_dir,
                    search_cache=search_cache,
                    search_cache_refresh_recent_days=search_cache_refresh_recent_days,
                )
                _write_set_checkpoint(
                    checkpoint_dir,
                    slug=resolved.slug,
                    product_line_id=product_line_id,
                    set_summary=set_summary,
                    products=set_products,
                    with_skus=with_skus,
                    priceguide_rows=priceguide_rows,
                )
                fetched_sets += 1
            sets.append(set_summary)
        products.extend(set_products)

    elapsed_seconds = time.perf_counter() - started
    sets.sort(key=lambda item: (item["name"], item["tcgplayerSetId"]))
    products.sort(key=lambda item: (item["setId"], item.get("collectorNumber", ""), item["name"]))
    return {
        "meta": {
            "object": "tcgjson_catalog",
            "version": 1,
            "source": "tcgplayer",
            "sourceMode": "priceguide+details" if with_skus else "priceguide",
            "generatedAt": exported_at,
            "productLine": product_line.get("productLineName", resolved.name),
            "slug": resolved.slug,
            "setCount": len(sets),
            "productCount": len(products),
            "cache": {
                "enabled": cache_dir is not None,
                "sourceGeneratedAt": (cached_catalog or {}).get("meta", {}).get("generatedAt", ""),
                "reusedSetCount": reused_sets,
                "reusedSetCheckpointCount": reused_checkpoint_sets,
                "fetchedSetCount": fetched_sets,
                "refreshRecentSetCount": refresh_recent_sets,
                "searchCacheEnabled": search_cache is not None,
                "searchCacheRefreshRecentDays": search_cache_refresh_recent_days,
                "recentSearchCacheRows": recent_search_cache_rows,
                "recentSearchCacheChangedRows": recent_search_cache_changed_rows,
                "searchMetadataCacheHitCount": sum(1 for item in sets if item.get("searchMetadataCacheHit")),
                "searchMetadataCacheWriteCount": sum(
                    int(item.get("searchMetadataCacheWriteCount") or 0) for item in sets
                ),
            },
            "metrics": {
                "durationSeconds": round(elapsed_seconds, 3),
                "setsPerSecond": round(len(sets) / max(elapsed_seconds, 0.001), 3),
                "productsPerSecond": round(len(products) / max(elapsed_seconds, 0.001), 3),
            },
        },
        "sets": sets,
        "products": products,
    }


def _refresh_recent_search_cache(
    client: TCGplayerClient,
    search_cache: SearchProductCache,
    *,
    product_line_name: str,
    product_line_id: int,
    refresh_recent_days: int,
) -> tuple[int, int]:
    refresh_after = _refresh_recent_after(refresh_recent_days)
    if refresh_after is None:
        return 0, 0
    offset = 0
    cached_rows = 0
    changed_rows = 0
    while True:
        page = client.search_products(
            product_line_name=product_line_name,
            offset=offset,
            sort={"field": "release-date", "order": "desc"},
        )
        rows = list(page.get("results") or [])
        if not rows:
            break
        changed_rows += search_cache.upsert_search_rows(
            rows,
            product_line_id=product_line_id,
            product_line_name=product_line_name,
        )
        cached_rows += len(rows)
        offset += len(rows)
        release_dates = [release_date for row in rows if (release_date := _search_row_release_date(row)) is not None]
        if release_dates and max(release_dates) < refresh_after:
            break
        total_results = int(page.get("totalResults") or 0)
        if offset >= total_results:
            break
    return cached_rows, changed_rows


def compact_catalog(full_catalog: dict[str, Any]) -> dict[str, Any]:
    meta = {**full_catalog["meta"], "object": "tcgjson_compact_catalog"}
    return {
        "meta": meta,
        "sets": full_catalog["sets"],
        "products": [compact_product(product) for product in full_catalog["products"]],
    }


def _file_manifest(path: Path, *, output_dir: Path, file_type: str, name: str, description: str) -> dict[str, Any]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    stat = path.stat()
    content_type = mimetypes.guess_type(path.name)[0] or "application/json"
    return {
        "object": "bulk_data",
        "type": file_type,
        "name": name,
        "description": description,
        "download_uri": path.relative_to(output_dir).as_posix(),
        "updated_at": _utc_timestamp_iso(stat.st_mtime),
        "size": stat.st_size,
        "sha256": digest,
        "content_type": content_type,
        "content_encoding": "identity",
    }


def write_metrics_file(output_dir: Path, metrics: dict[str, Any]) -> dict[str, Any]:
    path = output_dir / "metrics.json"
    atomic_write_json(path, metrics)
    return _file_manifest(
        path,
        output_dir=output_dir,
        file_type="build_metrics",
        name="Build Metrics",
        description="Timing, request-count, and cache-efficiency metrics for this tcgjson build.",
    )


def write_product_schema_files(output_dir: Path, catalog: dict[str, Any]) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = catalog["meta"]["slug"]
    product_line = catalog["meta"]["productLine"]
    profile = product_schema_profile(catalog)
    json_path = output_dir / f"{slug}.schema.json"
    markdown_path = output_dir / f"{slug}.schema.md"
    atomic_write_json(json_path, profile)
    atomic_write_text(markdown_path, product_schema_markdown(profile))
    return [
        _file_manifest(
            json_path,
            output_dir=output_dir,
            file_type=f"{slug}_schema",
            name=f"{product_line} Product Schema Profile",
            description=f"Observed product fields and population stats for {product_line}.",
        ),
        _file_manifest(
            markdown_path,
            output_dir=output_dir,
            file_type=f"{slug}_schema_markdown",
            name=f"{product_line} Product Schema Guide",
            description=f"Markdown product schema guide for {product_line}.",
        ),
    ]


def write_product_line_files(output_dir: Path, catalog: dict[str, Any]) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = catalog["meta"]["slug"]
    product_line = catalog["meta"]["productLine"]
    compact_path = output_dir / f"{slug}.json"
    full_path = output_dir / f"{slug}.full.json"
    atomic_write_json(compact_path, compact_catalog(catalog))
    atomic_write_json(full_path, catalog)
    return [
        _file_manifest(
            compact_path,
            output_dir=output_dir,
            file_type=f"{slug}_catalog",
            name=f"{product_line} Catalog",
            description=f"Compact TCGplayer catalog export for {product_line}.",
        ),
        _file_manifest(
            full_path,
            output_dir=output_dir,
            file_type=f"{slug}_catalog_full",
            name=f"{product_line} Full Catalog",
            description=f"Full TCGplayer catalog export for {product_line}, including price-guide rows and optional SKU IDs.",
        ),
    ]


def write_bulk_manifest(output_dir: Path, files: list[dict[str, Any]]) -> dict[str, Any]:
    generated_at = _utc_now_iso()
    manifest = {
        "object": "list",
        "source": "tcgjson",
        "generated_at": generated_at,
        "has_more": False,
        "data": sorted(files, key=lambda item: item["type"]),
    }
    atomic_write_json(output_dir / "bulk-data.json", manifest)
    return manifest


def build_release(
    output_dir: Path,
    product_lines: list[ProductLineRequest] | None = None,
    *,
    max_sets: int | None = None,
    priceguide_rows: int = 5000,
    with_skus: bool = False,
    cache_dir: Path | None = None,
    refresh_recent_sets: int = 0,
    client: TCGplayerClient | None = None,
    progress: bool = False,
    checkpoint_dir: Path | None = None,
    detail_cache_dir: Path | None = None,
    search_cache_db: Path | None = None,
    search_cache_refresh_recent_days: int = 45,
) -> dict[str, Any]:
    active_client = client or TCGplayerClient()
    selected_product_lines = product_lines or default_enabled_product_line_ids(active_client)
    build_started_at = _utc_now_iso()
    build_started = time.perf_counter()
    files: list[dict[str, Any]] = []
    product_line_metrics = []
    product_line_iterator = _progress(
        selected_product_lines,
        enabled=progress,
        desc="product lines",
        unit="line",
        position=0,
    )
    search_cache = SearchProductCache(search_cache_db) if search_cache_db is not None else None
    try:
        for product_line in product_line_iterator:
            line_started = time.perf_counter()
            stats_before = active_client.stats()
            catalog = fetch_product_line(
                active_client,
                product_line,
                max_sets=max_sets,
                priceguide_rows=priceguide_rows,
                with_skus=with_skus,
                cache_dir=cache_dir,
                refresh_recent_sets=refresh_recent_sets,
                progress=progress,
                checkpoint_dir=checkpoint_dir,
                detail_cache_dir=detail_cache_dir,
                search_cache=search_cache,
                search_cache_refresh_recent_days=search_cache_refresh_recent_days,
            )
            duration_seconds = round(time.perf_counter() - line_started, 3)
            files.extend(write_product_line_files(output_dir, catalog))
            files.extend(write_product_schema_files(output_dir, catalog))
            stats_after = active_client.stats()
            product_line_metrics.append(
                {
                    "productLine": catalog["meta"]["productLine"],
                    "slug": catalog["meta"]["slug"],
                    "durationSeconds": duration_seconds,
                    "setCount": catalog["meta"]["setCount"],
                    "productCount": catalog["meta"]["productCount"],
                    "cache": catalog["meta"].get("cache", {}),
                    "requests": _stats_delta(stats_before, stats_after),
                }
            )
    finally:
        if search_cache is not None:
            search_cache.close()
    metrics = {
        "object": "tcgjson_build_metrics",
        "startedAt": build_started_at,
        "finishedAt": _utc_now_iso(),
        "durationSeconds": round(time.perf_counter() - build_started, 3),
        "mode": "incremental" if cache_dir is not None else "full",
        "withSkus": with_skus,
        "cacheDir": str(cache_dir) if cache_dir is not None else "",
        "checkpointDir": str(checkpoint_dir) if checkpoint_dir is not None else "",
        "detailCacheDir": str(detail_cache_dir) if detail_cache_dir is not None else "",
        "searchCacheDb": str(search_cache_db) if search_cache_db is not None else "",
        "searchCacheRefreshRecentDays": search_cache_refresh_recent_days,
        "refreshRecentSetCount": refresh_recent_sets,
        "productLineCount": len(selected_product_lines),
        "productLines": product_line_metrics,
        "requests": _stats_dict(active_client.stats()),
    }
    files.append(write_metrics_file(output_dir, metrics))
    return write_bulk_manifest(output_dir, files)
