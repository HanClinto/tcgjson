"""Build bulk catalog files and manifests."""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import mimetypes
import time
from pathlib import Path
from typing import Any, Iterable, TypeVar

import requests

from .atomic import atomic_write_json, atomic_write_json_gzip
from .config import normalize_key, product_line_for_id, product_line_for_name
from .games import default_enabled_product_line_ids
from .normalize import (
    apply_product_details,
    compact_product,
    normalize_search_products,
)
from .schema import product_schema_profile
from .tcgplayer import RequestStats, TCGplayerClient, TCGplayerError


T = TypeVar("T")
SET_CHECKPOINT_VERSION = 5
CACHE_PRODUCT_SEARCH_FILTER = "setId"


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


def _log_progress(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[{_utc_now_iso()}] {message}", flush=True)


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
    for path in [cache_dir / f"{slug}.full.json", cache_dir / f"{slug}.full.json.gz"]:
        if path.exists():
            return _load_json(path)
    return None


def _load_json(path: Path) -> dict[str, Any]:
    if path.name.endswith(".json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def _load_cached_set_from_catalog(
    cached_catalog: dict[str, Any] | None,
    *,
    product_line_id: int,
    set_id: int,
    with_skus: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], str] | None:
    if cached_catalog is None:
        return None
    if cached_catalog.get("meta", {}).get("cache", {}).get("productSearchFilter") != CACHE_PRODUCT_SEARCH_FILTER:
        return None
    cached_set = next(
        (
            set_payload
            for set_payload in cached_catalog.get("sets", [])
            if int(set_payload.get("setId", set_payload.get("tcgplayerSetId") or 0)) == set_id
        ),
        None,
    )
    if cached_set is None:
        return None
    cached_products = []
    for product in cached_catalog.get("products", []):
        migrated_product = _migrate_cached_product(product)
        if int(migrated_product.get("setId") or 0) == set_id:
            cached_products.append(migrated_product)
    cached_product_count = int(cached_set.get("productCount") or 0)
    if (not cached_products and cached_product_count > 0) or (
        cached_products and with_skus and not _cached_products_have_skus(cached_products)
    ):
        return None
    set_summary = _migrate_cached_set(cached_set)
    set_summary["productCount"] = len(cached_products)
    return set_summary, cached_products, str(cached_catalog.get("meta", {}).get("generatedAt") or "")


def _compact_set_icon_name(value: str) -> str:
    replacements = {
        "&": "and",
        "+": "plus",
        "%": "pct",
        ".com": "-dotcom",
        ".net": "-dotnet",
        ".org": "-dotorg",
        ".biz": "-dotbiz",
    }
    text = value
    for old, new in replacements.items():
        text = text.replace(old, new)
    for char in ":®@[](){}<>|#*`‛’′!?.\"'=/\\":
        text = text.replace(char, "")
    return "".join(text.split())


def _set_icon_url(set_id: int | str, set_name: str) -> str:
    compact_name = _compact_set_icon_name(set_name)
    if not compact_name:
        return ""
    return f"https://tcgplayer-cdn.tcgplayer.com/set_icon/{set_id}{compact_name}.png"


def _migrate_cached_set(set_summary: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(set_summary)
    if "setId" not in migrated and "tcgplayerSetId" in migrated:
        migrated["setId"] = int(migrated["tcgplayerSetId"])
    if "iconUrl" not in migrated:
        migrated["iconUrl"] = _set_icon_url(migrated.get("setId", ""), migrated.get("name", ""))
    migrated.pop("tcgplayerSetId", None)
    migrated.pop("priceGuideRowCount", None)
    migrated.pop("source", None)
    migrated.pop("searchMetadataProductCount", None)
    migrated.pop("searchMetadataErrorCount", None)
    return migrated


def _set_checkpoint_path(checkpoint_dir: Path, slug: str, set_id: int) -> Path:
    return checkpoint_dir / slug / f"{set_id}.json"


def _load_set_checkpoint(
    checkpoint_dir: Path | None,
    *,
    slug: str,
    product_line_id: int,
    set_id: int,
    with_skus: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    if checkpoint_dir is None:
        return None
    path = _set_checkpoint_path(checkpoint_dir, slug, set_id)
    if path is None:
        return None
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("object") != "tcgjson_set_checkpoint"
        or int(payload.get("version") or 0) != SET_CHECKPOINT_VERSION
        or int(payload.get("productLineId") or 0) != product_line_id
        or int(payload.get("setId", payload.get("tcgplayerSetId") or 0)) != set_id
        or bool(payload.get("withSkus")) != with_skus
    ):
        return None
    set_summary = payload.get("set")
    products = payload.get("products")
    if not isinstance(set_summary, dict) or not isinstance(products, list):
        return None
    return _migrate_cached_set(set_summary), [_migrate_cached_product(product) for product in products]


def _write_set_checkpoint(
    checkpoint_dir: Path | None,
    *,
    slug: str,
    product_line_id: int,
    set_summary: dict[str, Any],
    products: list[dict[str, Any]],
    with_skus: bool,
) -> None:
    if checkpoint_dir is None:
        return
    set_id = int(set_summary["setId"])
    atomic_write_json(
        _set_checkpoint_path(checkpoint_dir, slug, set_id),
        {
            "object": "tcgjson_set_checkpoint",
            "version": SET_CHECKPOINT_VERSION,
            "generatedAt": _utc_now_iso(),
            "productLineId": product_line_id,
            "slug": slug,
            "setId": set_id,
            "withSkus": with_skus,
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
        or int(payload.get("productId", payload.get("tcgplayerProductId") or 0)) != int(product_id)
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
            "productId": int(product_id),
            "details": details,
        },
    )


def _recent_set_ids(set_rows: list[dict[str, Any]], refresh_recent_sets: int) -> set[int]:
    today = dt.datetime.now(dt.timezone.utc).date()
    future_ids = set()
    released_rows = []
    for row in set_rows:
        release_date = str(row.get("releaseDate") or "")
        try:
            parsed_date = dt.datetime.fromisoformat(release_date.replace("Z", "+00:00")).date()
            if parsed_date >= today:
                future_ids.add(int(row["setNameId"]))
            else:
                released_rows.append(row)
        except (KeyError, TypeError, ValueError):
            released_rows.append(row)
    if refresh_recent_sets <= 0:
        return future_ids
    sorted_rows = sorted(
        released_rows,
        key=lambda row: (row.get("releaseDate") or "", int(row.get("setNameId") or 0)),
    )
    return future_ids | {int(row["setNameId"]) for row in sorted_rows[-refresh_recent_sets:]}


def _cached_products_have_skus(products: list[dict[str, Any]]) -> bool:
    return all("skus" in product for product in products)


def _migrate_cached_product(product: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(product)
    migrated.pop("productLine", None)
    migrated.pop("productLineId", None)

    old_set = migrated.pop("set", {})
    if "setId" not in migrated:
        old_set_id = old_set.get("id") if isinstance(old_set, dict) else None
        migrated["setId"] = int(old_set_id or 0)
    else:
        migrated.pop("set", None)

    if "imageUrls" not in migrated:
        image_url = migrated.get("imageUrl", "")
        migrated["imageUrls"] = [image_url] if image_url else []
    if "productId" not in migrated and "tcgplayerProductId" in migrated:
        migrated["productId"] = int(migrated["tcgplayerProductId"])
    migrated.pop("tcgplayerProductId", None)
    migrated.pop("imageUrl", None)
    migrated.pop("priceGuide", None)
    return _order_product_fields(migrated)


def _search_row_matches_set(row: dict[str, Any], *, set_id: int, set_name: str) -> bool:
    row_set_id = row.get("setId")
    if row_set_id not in (None, ""):
        try:
            return int(float(row_set_id)) == set_id
        except (TypeError, ValueError):
            pass
    return bool(set_name) and row.get("setName") == set_name


def _order_product_fields(product: dict[str, Any]) -> dict[str, Any]:
    preferred_order = [
        "productId",
        "name",
        "setId",
        "collectorNumber",
        "rarity",
        "foilings",
        "imageUrls",
        "metadata",
        "skus",
    ]
    return {
        **{key: product[key] for key in preferred_order if key in product},
        **{key: value for key, value in product.items() if key not in preferred_order},
    }


def _fetch_set_products(
    client: TCGplayerClient,
    *,
    product_line_name: str,
    product_line_id: int,
    product_line_url_name: str,
    set_row: dict[str, Any],
    with_skus: bool,
    progress: bool,
    detail_cache_dir: Path | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    set_id = int(set_row["setNameId"])
    set_name = set_row.get("name", "")
    search_rows = list(
        client.iter_search_products(
            product_line_name=product_line_name,
            set_id=set_id,
        )
    )
    search_rows = [_row for _row in search_rows if _search_row_matches_set(_row, set_id=set_id, set_name=set_name)]
    set_products = normalize_search_products(
        search_rows,
        product_line_name=product_line_name,
        product_line_id=product_line_id,
        product_line_url_name=product_line_url_name,
        set_row=set_row,
    )
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
            product_id = product["productId"]
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
            "setId": set_id,
            "name": set_name,
            "urlName": set_row.get("urlName", ""),
            "abbreviation": set_row.get("abbreviation", ""),
            "releaseDate": set_row.get("releaseDate", ""),
            "iconUrl": _set_icon_url(set_row["setNameId"], set_row.get("cleanSetName") or set_row.get("name", "")),
            "isSupplemental": bool(set_row.get("isSupplemental")),
            "productCount": len(set_products),
            "detailErrorCount": detail_error_count,
            "detailCacheHitCount": detail_cache_hit_count,
            "detailFetchCount": detail_fetch_count,
        },
        set_products,
    )


def fetch_product_line(
    client: TCGplayerClient,
    product_line_name: ProductLineRequest,
    *,
    max_sets: int | None = None,
    with_skus: bool = False,
    cache_dir: Path | None = None,
    refresh_recent_sets: int = 0,
    progress: bool = False,
    log_progress: bool = False,
    checkpoint_dir: Path | None = None,
    detail_cache_dir: Path | None = None,
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
    cached_source_generated_at = str((cached_catalog or {}).get("meta", {}).get("generatedAt") or "")
    refresh_ids = _recent_set_ids(set_rows, refresh_recent_sets)
    sets = []
    products = []
    reused_sets = 0
    reused_checkpoint_sets = 0
    fetched_sets = 0
    _log_progress(
        log_progress,
        f"{resolved.slug}: starting {len(set_rows)} set(s), refreshRecentSets={refresh_recent_sets}, cacheDir={cache_dir or ''}",
    )
    set_iterator = _progress(
        set_rows,
        enabled=progress,
        desc=f"{resolved.slug} sets",
        unit="set",
        leave=False,
        position=1,
    )
    for set_index, set_row in enumerate(set_iterator, start=1):
        set_started = time.perf_counter()
        set_id = int(set_row["setNameId"])
        set_name = set_row.get("name", "")
        cached_set = _load_cached_set_from_catalog(
            cached_catalog,
            product_line_id=product_line_id,
            set_id=set_id,
            with_skus=with_skus,
        )
        can_reuse = (
            cached_set is not None
            and set_id not in refresh_ids
        )
        if can_reuse:
            set_summary, set_products, set_source_generated_at = cached_set
            if set_source_generated_at and not cached_source_generated_at:
                cached_source_generated_at = set_source_generated_at
            sets.append(set_summary)
            reused_sets += 1
            _log_progress(
                log_progress,
                f"{resolved.slug}: set {set_index}/{len(set_rows)} {set_id} {set_name!r} reused {len(set_products)} product(s) in {time.perf_counter() - set_started:.1f}s",
            )
        else:
            _log_progress(
                log_progress,
                f"{resolved.slug}: set {set_index}/{len(set_rows)} {set_id} {set_name!r} fetching",
            )
            checkpoint = _load_set_checkpoint(
                checkpoint_dir,
                slug=resolved.slug,
                product_line_id=product_line_id,
                set_id=set_id,
                with_skus=with_skus,
            )
            if checkpoint is not None:
                set_summary, set_products = checkpoint
                reused_checkpoint_sets += 1
                _log_progress(
                    log_progress,
                    f"{resolved.slug}: set {set_index}/{len(set_rows)} {set_id} {set_name!r} reused checkpoint with {len(set_products)} product(s) in {time.perf_counter() - set_started:.1f}s",
                )
            else:
                set_summary, set_products = _fetch_set_products(
                    client,
                    product_line_name=product_line.get("productLineName", resolved.name),
                    product_line_id=product_line_id,
                    product_line_url_name=product_line_url_name,
                    set_row=set_row,
                    with_skus=with_skus,
                    progress=progress,
                    detail_cache_dir=detail_cache_dir,
                )
                _write_set_checkpoint(
                    checkpoint_dir,
                    slug=resolved.slug,
                    product_line_id=product_line_id,
                    set_summary=set_summary,
                    products=set_products,
                    with_skus=with_skus,
                )
                fetched_sets += 1
                _log_progress(
                    log_progress,
                    f"{resolved.slug}: set {set_index}/{len(set_rows)} {set_id} {set_name!r} fetched {len(set_products)} product(s) in {time.perf_counter() - set_started:.1f}s",
                )
            sets.append(set_summary)
        products.extend(set_products)

    elapsed_seconds = time.perf_counter() - started
    sets.sort(key=lambda item: (item["name"], item["setId"]))
    products.sort(key=lambda item: (item["setId"], item.get("collectorNumber", ""), item["name"]))
    _log_progress(
        log_progress,
        f"{resolved.slug}: finished {len(sets)} set(s), {len(products)} product(s), reused={reused_sets}, checkpoints={reused_checkpoint_sets}, fetched={fetched_sets}, duration={elapsed_seconds:.1f}s",
    )
    return {
        "meta": {
            "object": "tcgjson_catalog",
            "version": 3,
            "generatedAt": exported_at,
            "productLine": product_line.get("productLineName", resolved.name),
            "slug": resolved.slug,
            "setCount": len(sets),
            "productCount": len(products),
            "cache": {
                "enabled": cache_dir is not None,
                "productSearchFilter": CACHE_PRODUCT_SEARCH_FILTER,
                "sourceGeneratedAt": cached_source_generated_at,
                "reusedSetCount": reused_sets,
                "reusedSetCheckpointCount": reused_checkpoint_sets,
                "fetchedSetCount": fetched_sets,
                "refreshRecentSetCount": refresh_recent_sets,
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
    content_type = "application/json" if path.name.endswith(".json.gz") else mimetypes.guess_type(path.name)[0] or "application/json"
    content_encoding = "gzip" if path.name.endswith(".json.gz") else "identity"
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
        "content_encoding": content_encoding,
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
    catalog = _without_price_fields(catalog)
    slug = catalog["meta"]["slug"]
    product_line = catalog["meta"]["productLine"]
    profile = product_schema_profile(catalog)
    json_path = output_dir / f"{slug}.schema.json.gz"
    atomic_write_json_gzip(json_path, profile)
    return [
        _file_manifest(
            json_path,
            output_dir=output_dir,
            file_type=f"{slug}_schema",
            name=f"{product_line} Product Schema Profile",
            description=f"Observed product fields and population stats for {product_line}.",
        )
    ]


def write_product_line_files(output_dir: Path, catalog: dict[str, Any]) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = catalog["meta"]["slug"]
    product_line = catalog["meta"]["productLine"]
    compact_path = output_dir / f"{slug}.json.gz"
    full_path = output_dir / f"{slug}.full.json.gz"
    catalog = _without_price_fields(catalog)
    atomic_write_json_gzip(compact_path, compact_catalog(catalog))
    atomic_write_json_gzip(full_path, catalog)
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
            description=f"Full TCGplayer catalog export for {product_line}, including metadata and optional SKU IDs.",
        ),
    ]


def _without_price_fields(catalog: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(catalog)
    meta = dict(catalog.get("meta", {}))
    meta.pop("source", None)
    meta.pop("sourceMode", None)
    meta.pop("productLineId", None)
    sanitized["meta"] = meta
    sanitized["sets"] = []
    for set_row in catalog.get("sets", []):
        set_row = _migrate_cached_set(set_row)
        sanitized["sets"].append(set_row)
    sanitized["products"] = []
    for product in catalog.get("products", []):
        product = _migrate_cached_product(product)
        for field in ("priceGuide", "lowPrice", "marketPrice", "medianPrice", "productLineId"):
            product.pop(field, None)
        sanitized["products"].append(_order_product_fields(product))
    return sanitized


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


def assemble_release(output_dir: Path, *, metrics_dir: Path | None = None) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    product_line_metrics = []
    metric_fragments = []
    metrics_source_dir = metrics_dir or output_dir / ".metrics"
    if metrics_source_dir.exists():
        for path in sorted(metrics_source_dir.glob("*.json")):
            metric_fragments.append(json.loads(path.read_text(encoding="utf-8")))

    full_catalog_paths = [*output_dir.glob("*.full.json"), *output_dir.glob("*.full.json.gz")]
    for full_catalog_path in sorted(full_catalog_paths):
        catalog = _load_json(full_catalog_path)
        files.extend(write_product_line_files(output_dir, catalog))
        files.extend(write_product_schema_files(output_dir, catalog))

    for fragment in metric_fragments:
        product_line_metrics.extend(fragment.get("productLines", []))

    started_at_values = [fragment.get("startedAt") for fragment in metric_fragments if fragment.get("startedAt")]
    finished_at_values = [fragment.get("finishedAt") for fragment in metric_fragments if fragment.get("finishedAt")]
    request_totals = {"requests": 0, "retries": 0, "errors": 0, "cacheHits": 0}
    for product_line in product_line_metrics:
        for key, value in product_line.get("requests", {}).items():
            request_totals[key] = request_totals.get(key, 0) + int(value or 0)

    first_fragment = metric_fragments[0] if metric_fragments else {}
    metrics = {
        "object": "tcgjson_build_metrics",
        "startedAt": min(started_at_values) if started_at_values else _utc_now_iso(),
        "finishedAt": max(finished_at_values) if finished_at_values else _utc_now_iso(),
        "durationSeconds": round(sum(float(fragment.get("durationSeconds") or 0) for fragment in metric_fragments), 3),
        "mode": first_fragment.get("mode", "assembled"),
        "withSkus": bool(first_fragment.get("withSkus", False)),
        "cacheDir": first_fragment.get("cacheDir", ""),
        "checkpointDir": first_fragment.get("checkpointDir", ""),
        "detailCacheDir": first_fragment.get("detailCacheDir", ""),
        "refreshRecentSetCount": int(first_fragment.get("refreshRecentSetCount") or 0),
        "productLineCount": len(product_line_metrics),
        "productLines": product_line_metrics,
        "requests": request_totals,
    }
    files.append(write_metrics_file(output_dir, metrics))
    return write_bulk_manifest(output_dir, files)


def build_release(
    output_dir: Path,
    product_lines: list[ProductLineRequest] | None = None,
    *,
    max_sets: int | None = None,
    with_skus: bool = False,
    cache_dir: Path | None = None,
    refresh_recent_sets: int = 0,
    client: TCGplayerClient | None = None,
    progress: bool = False,
    log_progress: bool = False,
    checkpoint_dir: Path | None = None,
    detail_cache_dir: Path | None = None,
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
    _log_progress(log_progress, f"build: starting {len(selected_product_lines)} product line(s)")
    for product_line in product_line_iterator:
        line_started = time.perf_counter()
        stats_before = active_client.stats()
        _log_progress(log_progress, f"build: starting product line {product_line}")
        catalog = fetch_product_line(
            active_client,
            product_line,
            max_sets=max_sets,
            with_skus=with_skus,
            cache_dir=cache_dir,
            refresh_recent_sets=refresh_recent_sets,
            progress=progress,
            log_progress=log_progress,
            checkpoint_dir=checkpoint_dir,
            detail_cache_dir=detail_cache_dir,
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
        _log_progress(
            log_progress,
            f"build: finished {catalog['meta']['slug']} in {duration_seconds:.1f}s, sets={catalog['meta']['setCount']}, products={catalog['meta']['productCount']}, requests={_stats_delta(stats_before, stats_after)['requests']}",
        )
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
        "refreshRecentSetCount": refresh_recent_sets,
        "productLineCount": len(selected_product_lines),
        "productLines": product_line_metrics,
        "requests": _stats_dict(active_client.stats()),
    }
    files.append(write_metrics_file(output_dir, metrics))
    return write_bulk_manifest(output_dir, files)
