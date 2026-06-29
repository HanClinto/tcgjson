"""Build bulk catalog files and manifests."""
from __future__ import annotations

import datetime as dt
import hashlib
import mimetypes
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .config import normalize_key, product_line_for_name
from .normalize import compact_product, extract_skus, group_priceguide_products
from .tcgplayer import TCGplayerClient, TCGplayerError


def _resolve_product_line(client: TCGplayerClient, requested_name: str) -> dict[str, Any]:
    requested = product_line_for_name(requested_name)
    wanted = {normalize_key(requested.name), normalize_key(requested.slug)}
    wanted.update(normalize_key(alias) for alias in requested.aliases)
    for row in client.get_product_lines():
        candidates = [row.get("productLineName", ""), row.get("productLineUrlName", "")]
        if any(normalize_key(candidate) in wanted for candidate in candidates):
            return row
    raise TCGplayerError(f"Unknown TCGplayer product line: {requested_name}")


def fetch_product_line(
    client: TCGplayerClient,
    product_line_name: str,
    *,
    max_sets: int | None = None,
    priceguide_rows: int = 5000,
    with_skus: bool = False,
) -> dict[str, Any]:
    resolved = product_line_for_name(product_line_name)
    product_line = _resolve_product_line(client, product_line_name)
    product_line_id = int(product_line["productLineId"])
    product_line_url_name = product_line.get("productLineUrlName", "")
    set_rows = client.get_set_names(product_line_id)
    if max_sets is not None:
        set_rows = set_rows[:max_sets]

    exported_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    sets = []
    products = []
    for set_row in set_rows:
        priceguide = client.get_priceguide_set_cards(set_row["setNameId"], rows=priceguide_rows)
        rows = list(priceguide.get("result") or [])
        set_products = group_priceguide_products(
            rows,
            product_line_name=product_line.get("productLineName", resolved.name),
            product_line_id=product_line_id,
            product_line_url_name=product_line_url_name,
            set_row=set_row,
        )
        sets.append(
            {
                "tcgplayerSetId": int(set_row["setNameId"]),
                "name": set_row.get("name", ""),
                "urlName": set_row.get("urlName", ""),
                "abbreviation": set_row.get("abbreviation", ""),
                "releaseDate": set_row.get("releaseDate", ""),
                "isSupplemental": bool(set_row.get("isSupplemental")),
                "productCount": len(set_products),
                "priceGuideRowCount": len(rows),
            }
        )
        products.extend(set_products)

    if with_skus:
        for product in products:
            details = client.get_product_details(product["tcgplayerProductId"])
            product["skus"] = extract_skus(details)

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
        "updated_at": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "size": stat.st_size,
        "sha256": digest,
        "content_type": content_type,
        "content_encoding": "identity",
    }


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
    generated_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
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
    product_lines: list[str],
    *,
    max_sets: int | None = None,
    priceguide_rows: int = 5000,
    with_skus: bool = False,
    client: TCGplayerClient | None = None,
) -> dict[str, Any]:
    active_client = client or TCGplayerClient()
    files: list[dict[str, Any]] = []
    for product_line in product_lines:
        catalog = fetch_product_line(
            active_client,
            product_line,
            max_sets=max_sets,
            priceguide_rows=priceguide_rows,
            with_skus=with_skus,
        )
        files.extend(write_product_line_files(output_dir, catalog))
    return write_bulk_manifest(output_dir, files)
