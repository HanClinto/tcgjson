"""Discover and report TCGplayer product-line support."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from .atomic import atomic_write_json, atomic_write_text
from .config import (
    MANUAL_EXCLUDED_PRODUCT_LINES,
    MANUAL_INCLUDED_PRODUCT_LINES,
    normalize_key,
    product_line_for_id,
    slugify,
)
from .tcgplayer import TCGplayerClient, TCGplayerError


TCGPLAYER_WEB_BASE = "https://www.tcgplayer.com"


def _line_names(lines: tuple[Any, ...]) -> set[str]:
    names: set[str] = set()
    for line in lines:
        names.add(normalize_key(line.name))
        names.add(normalize_key(line.slug))
        names.update(normalize_key(alias) for alias in line.aliases)
    return names


def _line_ids(lines: tuple[Any, ...]) -> set[int]:
    return {line.tcgplayer_id for line in lines if line.tcgplayer_id is not None}


def _ordered_line_ids(lines: tuple[Any, ...]) -> list[int]:
    return [line.tcgplayer_id for line in lines if line.tcgplayer_id is not None]


def _matches_any_line(name: str, keys: set[str]) -> bool:
    candidate = normalize_key(name)
    return any(key == candidate or key in candidate or candidate in key for key in keys)


def _popular_name(row: dict[str, Any]) -> str:
    return row.get("full-title") or row.get("fullTitle") or row.get("title") or ""


def popular_product_line_names(client: TCGplayerClient) -> list[str]:
    names = [_popular_name(row) for row in client.get_popular_games()]
    return [name for name in names if name]


def _popular_product_line_ids(client: TCGplayerClient, product_lines: list[dict[str, Any]]) -> list[int]:
    return _popular_product_line_ids_from_names(popular_product_line_names(client), product_lines)


def _popular_product_line_ids_from_names(names: list[str], product_lines: list[dict[str, Any]]) -> list[int]:
    popular_keys = {normalize_key(name) for name in names}
    ids = []
    for product_line in product_lines:
        if normalize_key(product_line.get("productLineName", "")) in popular_keys:
            ids.append(int(product_line["productLineId"]))
    return ids


def _absolute_tcgplayer_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return f"{TCGPLAYER_WEB_BASE}/{url.lstrip('/')}"


def _resource_links(product_line: dict[str, Any], popular_row: dict[str, Any] | None) -> dict[str, Any]:
    url_name = product_line.get("productLineUrlName", "")
    search_url = popular_row.get("shopAllUrl") if popular_row else ""
    resources: dict[str, Any] = {
        "tcgplayer": {
            "searchUrl": _absolute_tcgplayer_url(
                search_url or f"/search/{url_name}/product?productLineName={url_name}&page=1"
            ),
        }
    }
    if not popular_row:
        return resources
    for output_name, source_name in [
        ("articlesUrl", "articlesUrl"),
        ("decksUrl", "decksUrl"),
        ("advancedSearchUrl", "advancedSearchUrl"),
        ("priceGuideUrl", "priceGuideUrl"),
    ]:
        value = _absolute_tcgplayer_url(popular_row.get(source_name, ""))
        if value:
            resources["tcgplayer"][output_name] = value
    feature = popular_row.get("feature")
    if isinstance(feature, dict):
        feature_resource = {
            "title": feature.get("title", ""),
            "url": _absolute_tcgplayer_url(feature.get("ctaUrl", "")),
            "imagePath": feature.get("imageUrl") or feature.get("imageUrlSm") or "",
        }
        resources["tcgplayer"]["feature"] = {key: value for key, value in feature_resource.items() if value}
    return resources


def _latest_set_ids(client: TCGplayerClient, product_line_id: int) -> list[int]:
    try:
        payload = client.get_latest_sets(product_line_id)
    except (requests.RequestException, TCGplayerError):
        return []
    latest_sets = []
    for group in payload:
        if int(group.get("categoryId") or 0) != product_line_id:
            continue
        latest_sets = list(group.get("latestSets") or [])
        break
    set_ids = []
    for set_row in latest_sets[:10]:
        set_id = int(set_row.get("setNameId") or 0)
        if not set_id:
            continue
        set_ids.append(set_id)
    return set_ids


def default_enabled_product_line_ids(client: TCGplayerClient) -> list[int]:
    product_lines = client.get_product_lines()
    excluded_ids = _line_ids(MANUAL_EXCLUDED_PRODUCT_LINES)
    ids = []
    seen: set[int] = set()
    for product_line_id in [*_popular_product_line_ids(client, product_lines), *_ordered_line_ids(MANUAL_INCLUDED_PRODUCT_LINES)]:
        if product_line_id in excluded_ids or product_line_id in seen:
            continue
        ids.append(product_line_id)
        seen.add(product_line_id)
    return ids


def default_enabled_product_line_names(client: TCGplayerClient) -> list[str]:
    product_lines_by_id = {int(row["productLineId"]): row for row in client.get_product_lines()}
    names = []
    for product_line_id in default_enabled_product_line_ids(client):
        row = product_lines_by_id.get(product_line_id)
        names.append(row.get("productLineName", "") if row else product_line_for_id(product_line_id).name)
    return names


def discover_game_support(client: TCGplayerClient) -> dict[str, Any]:
    product_lines = client.get_product_lines()
    popular_rows = client.get_popular_games()
    popular_names = [_popular_name(row) for row in popular_rows]
    popular_by_name = {normalize_key(_popular_name(row)): row for row in popular_rows if _popular_name(row)}
    popular_ids = set(_popular_product_line_ids_from_names(popular_names, product_lines))
    manual_include_ids = _line_ids(MANUAL_INCLUDED_PRODUCT_LINES)
    manual_exclude_ids = _line_ids(MANUAL_EXCLUDED_PRODUCT_LINES)
    manual_include_keys = _line_names(tuple(line for line in MANUAL_INCLUDED_PRODUCT_LINES if line.tcgplayer_id is None))
    manual_exclude_keys = _line_names(tuple(line for line in MANUAL_EXCLUDED_PRODUCT_LINES if line.tcgplayer_id is None))

    rows = []
    for product_line in product_lines:
        name = product_line.get("productLineName", "")
        product_line_id = int(product_line["productLineId"])
        is_popular = product_line_id in popular_ids
        is_manual = product_line_id in manual_include_ids or _matches_any_line(name, manual_include_keys)
        is_excluded = product_line_id in manual_exclude_ids or _matches_any_line(name, manual_exclude_keys)
        is_enabled = (is_popular or is_manual) and not is_excluded
        popular_row = popular_by_name.get(normalize_key(name))
        resources = _resource_links(product_line, popular_row)
        if is_enabled:
            resources["tcgplayer"]["latestSets"] = _latest_set_ids(client, product_line_id)
        rows.append(
            {
                "name": name,
                "slug": product_line_for_id(product_line_id, name).slug if is_enabled else slugify(name),
                "tcgplayerProductLineId": product_line_id,
                "tcgplayerUrlName": product_line.get("productLineUrlName", ""),
                "popular": is_popular,
                "manualInclude": is_manual,
                "manualExclude": is_excluded,
                "enabled": is_enabled,
                "resources": resources,
            }
        )
    rows.sort(key=lambda row: (not row["enabled"], not row["popular"], row["name"].casefold()))
    return {"object": "tcgjson_game_support", "games": rows}


def game_support_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# TCGplayer Product-Line Support",
        "",
        "Checked rows are included by default. Popular games come from TCGplayer navigation;",
        "manual inclusions and exclusions are configured in `src/tcgjson/config.py`.",
        "",
        "| Enabled | Product line | Popular | Manual include | Manual exclude | TCGplayer ID |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["games"]:
        lines.append(
            "| {enabled} | {name} | {popular} | {manual} | {excluded} | {line_id} |".format(
                enabled="[x]" if row["enabled"] else "[ ]",
                name=row["name"],
                popular="yes" if row["popular"] else "",
                manual="yes" if row["manualInclude"] else "",
                excluded="yes" if row["manualExclude"] else "",
                line_id=row.get("tcgplayerProductLineId") or "",
            )
        )
    return "\n".join(lines) + "\n"


def write_game_support_report(report: dict[str, Any], output: Path, *, json_output: Path | None) -> None:
    atomic_write_text(output, game_support_markdown(report))
    if json_output is not None:
        atomic_write_json(json_output, report)