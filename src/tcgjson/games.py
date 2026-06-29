"""Discover and report TCGplayer product-line support."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .atomic import atomic_write_json, atomic_write_text
from .config import (
    MANUAL_EXCLUDED_PRODUCT_LINES,
    MANUAL_INCLUDED_PRODUCT_LINES,
    normalize_key,
    product_line_for_name,
    slugify,
)
from .tcgplayer import TCGplayerClient


def _line_names(lines: tuple[Any, ...]) -> set[str]:
    names: set[str] = set()
    for line in lines:
        names.add(normalize_key(line.name))
        names.add(normalize_key(line.slug))
        names.update(normalize_key(alias) for alias in line.aliases)
    return names


def _matches_any_line(name: str, keys: set[str]) -> bool:
    candidate = normalize_key(name)
    return any(key == candidate or key in candidate or candidate in key for key in keys)


def _popular_name(row: dict[str, Any]) -> str:
    return row.get("full-title") or row.get("fullTitle") or row.get("title") or ""


def popular_product_line_names(client: TCGplayerClient) -> list[str]:
    names = [_popular_name(row) for row in client.get_popular_games()]
    return [name for name in names if name]


def default_enabled_product_line_names(client: TCGplayerClient) -> list[str]:
    excluded = _line_names(MANUAL_EXCLUDED_PRODUCT_LINES)
    names = []
    seen: set[str] = set()
    for name in [*popular_product_line_names(client), *(line.name for line in MANUAL_INCLUDED_PRODUCT_LINES)]:
        key = normalize_key(name)
        if key in excluded or key in seen:
            continue
        names.append(name)
        seen.add(key)
    return names


def discover_game_support(client: TCGplayerClient) -> dict[str, Any]:
    popular_keys = {normalize_key(name) for name in popular_product_line_names(client)}
    manual_include_keys = _line_names(MANUAL_INCLUDED_PRODUCT_LINES)
    manual_exclude_keys = _line_names(MANUAL_EXCLUDED_PRODUCT_LINES)

    rows = []
    for product_line in client.get_product_lines():
        name = product_line.get("productLineName", "")
        key = normalize_key(name)
        is_popular = key in popular_keys
        is_manual = _matches_any_line(name, manual_include_keys)
        is_excluded = _matches_any_line(name, manual_exclude_keys)
        is_enabled = (is_popular or is_manual) and not is_excluded
        rows.append(
            {
                "name": name,
                "slug": product_line_for_name(name).slug if is_enabled else slugify(name),
                "tcgplayerProductLineId": product_line.get("productLineId"),
                "tcgplayerUrlName": product_line.get("productLineUrlName", ""),
                "popular": is_popular,
                "manualInclude": is_manual,
                "manualExclude": is_excluded,
                "enabled": is_enabled,
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