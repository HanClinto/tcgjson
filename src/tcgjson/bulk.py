"""Build bulk catalog files and manifests."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import mimetypes
import time
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .config import normalize_key, product_line_for_name
from .games import default_enabled_product_line_names
from .normalize import compact_product, extract_skus, group_priceguide_products
from .tcgplayer import RequestStats, TCGplayerClient, TCGplayerError


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _utc_timestamp_iso(timestamp: float) -> str:
    return (
        dt.datetime.fromtimestamp(timestamp, dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _stats_delta(before: RequestStats, after: RequestStats) -> dict[str, int]:
    return {
        "requests": after.requests - before.requests,
        "retries": after.retries - before.retries,
        "errors": after.errors - before.errors,
    }


def _stats_dict(stats: RequestStats) -> dict[str, int]:
    return {"requests": stats.requests, "retries": stats.retries, "errors": stats.errors}


def _resolve_product_line(client: TCGplayerClient, requested_name: str) -> dict[str, Any]:
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


def _fetch_set_products(
    client: TCGplayerClient,
    *,
    product_line_name: str,
    product_line_id: int,
    product_line_url_name: str,
    set_row: dict[str, Any],
    priceguide_rows: int,
    with_skus: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    priceguide = client.get_priceguide_set_cards(set_row["setNameId"], rows=priceguide_rows)
    rows = list(priceguide.get("result") or [])
    set_products = group_priceguide_products(
        rows,
        product_line_name=product_line_name,
        product_line_id=product_line_id,
        product_line_url_name=product_line_url_name,
        set_row=set_row,
    )
    if with_skus:
        for product in set_products:
            details = client.get_product_details(product["tcgplayerProductId"])
            product["skus"] = extract_skus(details)
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
        },
        set_products,
    )


def fetch_product_line(
    client: TCGplayerClient,
    product_line_name: str,
    *,
    max_sets: int | None = None,
    priceguide_rows: int = 5000,
    with_skus: bool = False,
    cache_dir: Path | None = None,
    refresh_recent_sets: int = 0,
) -> dict[str, Any]:
    started = time.perf_counter()
    resolved = product_line_for_name(product_line_name)
    product_line = _resolve_product_line(client, product_line_name)
    product_line_id = int(product_line["productLineId"])
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
        set_id = int(product.get("set", {}).get("id") or 0)
        cached_products.setdefault(set_id, []).append(product)
    refresh_ids = _recent_set_ids(set_rows, refresh_recent_sets)
    sets = []
    products = []
    reused_sets = 0
    fetched_sets = 0
    for set_row in set_rows:
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
            set_summary, set_products = _fetch_set_products(
                client,
                product_line_name=product_line.get("productLineName", resolved.name),
                product_line_id=product_line_id,
                product_line_url_name=product_line_url_name,
                set_row=set_row,
                priceguide_rows=priceguide_rows,
                with_skus=with_skus,
            )
            sets.append(set_summary)
            fetched_sets += 1
        products.extend(set_products)

    elapsed_seconds = time.perf_counter() - started
    sets.sort(key=lambda item: (item["name"], item["tcgplayerSetId"]))
    products.sort(key=lambda item: (item["set"]["name"], item.get("collectorNumber", ""), item["name"]))
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
    product_lines: list[str] | None = None,
    *,
    max_sets: int | None = None,
    priceguide_rows: int = 5000,
    with_skus: bool = False,
    cache_dir: Path | None = None,
    refresh_recent_sets: int = 0,
    client: TCGplayerClient | None = None,
) -> dict[str, Any]:
    active_client = client or TCGplayerClient()
    selected_product_lines = product_lines or default_enabled_product_line_names(active_client)
    build_started_at = _utc_now_iso()
    build_started = time.perf_counter()
    files: list[dict[str, Any]] = []
    product_line_metrics = []
    for product_line in selected_product_lines:
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
        )
        duration_seconds = round(time.perf_counter() - line_started, 3)
        files.extend(write_product_line_files(output_dir, catalog))
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
    metrics = {
        "object": "tcgjson_build_metrics",
        "startedAt": build_started_at,
        "finishedAt": _utc_now_iso(),
        "durationSeconds": round(time.perf_counter() - build_started, 3),
        "mode": "incremental" if cache_dir is not None else "full",
        "withSkus": with_skus,
        "cacheDir": str(cache_dir) if cache_dir is not None else "",
        "refreshRecentSetCount": refresh_recent_sets,
        "productLineCount": len(selected_product_lines),
        "productLines": product_line_metrics,
        "requests": _stats_dict(active_client.stats()),
    }
    files.append(write_metrics_file(output_dir, metrics))
    return write_bulk_manifest(output_dir, files)
