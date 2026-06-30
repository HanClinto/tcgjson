"""Generate source-controlled Markdown documentation from release artifacts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from .atomic import atomic_write_text


CATALOG_DOCS_VERSION = 1


def generate_catalog_docs(
    *,
    release_dir: Path,
    output_dir: Path,
    previous_release_dir: Path | None = None,
    release_tag: str = "",
    release_url: str = "",
) -> list[Path]:
    manifest = _load_json(release_dir / "bulk-data.json")
    metrics = _load_json(release_dir / "metrics.json")
    games = _load_json(release_dir / "games.json") if (release_dir / "games.json").exists() else {"games": []}

    output_dir.mkdir(parents=True, exist_ok=True)
    game_dir = output_dir / "games"
    game_dir.mkdir(parents=True, exist_ok=True)

    catalog_items = [item for item in manifest.get("data", []) if item.get("type", "").endswith("_catalog_full")]
    catalogs = [_load_json(release_dir / item["download_uri"]) for item in catalog_items]
    catalogs.sort(key=lambda catalog: catalog.get("meta", {}).get("productLine", ""))

    written: list[Path] = []
    written.append(_write_index(output_dir / "README.md", catalogs, metrics, manifest, release_tag, release_url))
    written.append(_write_objects(output_dir / "objects.md", catalogs, manifest, release_tag, release_url))
    written.append(
        _write_release_history(
            output_dir / "release-history.md",
            catalogs,
            metrics,
            manifest,
            previous_release_dir,
            release_tag,
            release_url,
        )
    )
    written.append(_write_games_index(output_dir / "games.md", games, catalogs, release_tag, release_url))
    for catalog in catalogs:
        written.append(_write_game_page(game_dir / f"{catalog['meta']['slug']}.md", catalog, metrics, release_tag, release_url))
    return written


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_index(path: Path, catalogs: list[dict[str, Any]], metrics: dict[str, Any], manifest: dict[str, Any], release_tag: str, release_url: str) -> Path:
    lines = [
        "# tcgjson Catalog Docs",
        "",
        "Welcome. These pages describe the generated TCGplayer bulk catalog JSON in a human-friendly way.",
        "The JSON files themselves are published through GitHub Releases; these Markdown pages live in source control so changes are easy to review.",
        "",
        _generated_note(metrics, release_tag, release_url),
        "",
        "## Start Here",
        "",
        "- [Object guide](objects.md) explains the catalog, set, product, price, and manifest shapes.",
        "- [Game index](games.md) lists supported and discovered TCGplayer product lines.",
        "- [Release history](release-history.md) summarizes each generated release and its changes.",
        "",
        "## Current Catalogs",
        "",
        "| Game | Sets | Products | Full JSON | Compact JSON | Schema |",
        "| --- | ---: | ---: | --- | --- | --- |",
    ]
    by_name = _manifest_by_download(manifest)
    for catalog in catalogs:
        meta = catalog.get("meta", {})
        slug = meta.get("slug", "")
        full_name = f"{slug}.full.json"
        compact_name = f"{slug}.json"
        schema_name = f"{slug}.schema.json"
        lines.append(
            "| "
            f"[{_escape_table(meta.get('productLine', slug))}](games/{slug}.md) | "
            f"{meta.get('setCount', len(catalog.get('sets', [])))} | "
            f"{meta.get('productCount', len(catalog.get('products', [])))} | "
            f"{_asset_link(full_name, by_name, release_url)} | {_asset_link(compact_name, by_name, release_url)} | {_asset_link(schema_name, by_name, release_url)} |"
        )
    lines.extend(
        [
            "",
            "## What Is Included",
            "",
            "tcgjson focuses on singles catalog data: products, sets, collector numbers, rarities, image URLs, and price-guide rows where TCGplayer exposes them.",
            "It does not publish marketplace listings, seller inventory, sealed products, or downloaded card images.",
            "",
            "## Release Artifacts",
            "",
            f"The current manifest lists {len(manifest.get('data', []))} JSON artifacts. Start with `bulk-data.json` in the release to discover filenames, sizes, hashes, and stable file types.",
        ]
    )
    return _write(path, lines)


def _write_objects(path: Path, catalogs: list[dict[str, Any]], manifest: dict[str, Any], release_tag: str, release_url: str) -> Path:
    example_catalog = catalogs[0] if catalogs else {}
    example_product = next(iter(example_catalog.get("products", [])), {}) if example_catalog else {}
    example_set = next(iter(example_catalog.get("sets", [])), {}) if example_catalog else {}
    price_rows = example_product.get("priceGuide") or []
    example_price = price_rows[0] if price_rows else {}
    lines = [
        "# Object Guide",
        "",
        "These object notes are generated from the release files and written for people exploring the data for the first time.",
        "The names are intentionally plain: catalogs contain sets and products; products may contain price-guide rows and optional metadata.",
        "",
        _generated_note({}, release_tag, release_url),
        "",
        "## Bulk Manifest",
        "",
        "`bulk-data.json` is the entry point. It is a list object whose `data` array describes each downloadable JSON artifact.",
        "Each item includes a stable `type`, `download_uri`, `size`, `sha256`, `updated_at`, and a short description.",
        "",
        "## Catalog Object",
        "",
        "A full catalog file is named `<slug>.full.json`. The compact companion is named `<slug>.json` and omits fields intended mainly for auditing or deeper integrations.",
        "",
        _field_table(example_catalog, ["meta", "sets", "products"]),
        "",
        "## Set Object",
        "",
        "A set summarizes a TCGplayer set/category grouping. Set pages link back to TCGplayer search pages so a person can inspect the source storefront context.",
        "",
        _field_table(example_set, ["tcgplayerSetId", "name", "urlName", "productCount", "priceGuideRowCount", "source"]),
        "",
        "## Product Object",
        "",
        "A product is one catalog card/product record. Most integrations should start with `tcgplayerProductId`, `name`, `setId`, `collectorNumber`, `rarity`, `imageUrls`, and `priceGuide`.",
        "",
        _field_table(example_product, ["tcgplayerProductId", "name", "productLineId", "setId", "collectorNumber", "rarity", "foilings", "imageUrls", "metadata", "priceGuide"]),
        "",
        "## Price Guide Row",
        "",
        "Price-guide rows are normalized from TCGplayer's priceguide endpoint when available. Search-only fallback sets may have aggregate price fields instead of condition-by-printing rows.",
        "",
        _field_table(example_price, sorted(example_price) if example_price else []),
    ]
    return _write(path, lines)


def _write_release_history(
    path: Path,
    catalogs: list[dict[str, Any]],
    metrics: dict[str, Any],
    manifest: dict[str, Any],
    previous_release_dir: Path | None,
    release_tag: str,
    release_url: str,
) -> Path:
    old_sections = ""
    marker = "\n## "
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if marker in existing:
            old_sections = existing[existing.index(marker) :].strip()
    heading = release_tag or metrics.get("finishedAt") or "current release"
    lines = [
        "# Release History",
        "",
        "This generated document keeps a running, human-readable summary of catalog releases.",
        "Each new run updates the top section from `metrics.json` and the generated catalogs.",
        "",
        f"## {heading}",
        "",
        _generated_note(metrics, release_tag, release_url),
        "",
        "### Summary",
        "",
        f"- Product lines: {metrics.get('productLineCount', len(catalogs))}",
        f"- Release files in manifest: {len(manifest.get('data', []))}",
        f"- Build duration: {_duration(metrics.get('durationSeconds'))}",
        f"- Requests: {metrics.get('requests', {}).get('requests', 0)} total, {metrics.get('requests', {}).get('retries', 0)} retries, {metrics.get('requests', {}).get('errors', 0)} errors",
        "",
        "### Product-Line Stats",
        "",
        "| Game | Sets | Products | Reused Sets | Fetched Sets | Duration |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for line in sorted(metrics.get("productLines", []), key=lambda item: item.get("productLine", "")):
        cache = line.get("cache", {})
        lines.append(
            f"| [{_escape_table(line.get('productLine', line.get('slug', '')))}](games/{line.get('slug', '')}.md) | "
            f"{line.get('setCount', 0)} | {line.get('productCount', 0)} | "
            f"{cache.get('reusedSetCount', 0)} | {cache.get('fetchedSetCount', 0)} | {_duration(line.get('durationSeconds'))} |"
        )
    lines.extend(["", "### Change Notes", ""])
    lines.extend(_change_notes(catalogs, previous_release_dir))
    if old_sections:
        current_header = f"## {heading}"
        sections = [section for section in old_sections.split("\n## ") if section.strip()]
        filtered = []
        for section in sections:
            normalized = section if section.startswith("## ") else f"## {section}"
            if not normalized.startswith(current_header):
                filtered.append(normalized)
        if filtered:
            lines.extend(["", *filtered])
    return _write(path, lines)


def _write_games_index(path: Path, games: dict[str, Any], catalogs: list[dict[str, Any]], release_tag: str, release_url: str) -> Path:
    enabled_slugs = {catalog.get("meta", {}).get("slug") for catalog in catalogs}
    catalog_by_slug = {catalog.get("meta", {}).get("slug"): catalog for catalog in catalogs}
    lines = [
        "# Game Index",
        "",
        "This page lists TCGplayer product lines discovered by tcgjson. Enabled games have generated catalog pages.",
        "",
        _generated_note({}, release_tag, release_url),
        "",
        "## Enabled Catalogs",
        "",
        "| Game | TCGplayer ID | Sets | Products | Catalog Page |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in games.get("games", []):
        if row.get("slug") not in enabled_slugs:
            continue
        catalog = catalog_by_slug.get(row.get("slug"), {})
        meta = catalog.get("meta", {})
        lines.append(
            f"| {_escape_table(row.get('name', ''))} | {row.get('tcgplayerProductLineId', '')} | "
            f"{meta.get('setCount', 0)} | {meta.get('productCount', 0)} | [Open](games/{row.get('slug')}.md) |"
        )
    disabled = [row for row in games.get("games", []) if not row.get("enabled")]
    if disabled:
        lines.extend(["", "## Discovered But Not Enabled", "", "| Game | TCGplayer ID | URL Name |", "| --- | ---: | --- |"])
        for row in disabled:
            lines.append(f"| {_escape_table(row.get('name', ''))} | {row.get('tcgplayerProductLineId', '')} | `{row.get('tcgplayerUrlName', '')}` |")
    return _write(path, lines)


def _write_game_page(path: Path, catalog: dict[str, Any], metrics: dict[str, Any], release_tag: str, release_url: str) -> Path:
    meta = catalog.get("meta", {})
    slug = meta.get("slug", "")
    line_metrics = next((line for line in metrics.get("productLines", []) if line.get("slug") == slug), {})
    cache = line_metrics.get("cache", {})
    sets = sorted(catalog.get("sets", []), key=lambda item: item.get("name", ""))
    products = catalog.get("products", [])
    top_sets = sorted(sets, key=lambda item: int(item.get("productCount") or 0), reverse=True)[:12]
    lines = [
        f"# {meta.get('productLine', slug)}",
        "",
        _generated_note(metrics, release_tag, release_url),
        "",
        "## Catalog Snapshot",
        "",
        f"- Sets: {meta.get('setCount', len(sets))}",
        f"- Products: {meta.get('productCount', len(products))}",
        f"- Build source mode: `{meta.get('sourceMode', '')}`",
        f"- Build duration: {_duration(line_metrics.get('durationSeconds'))}",
        f"- Cache reuse: {cache.get('reusedSetCount', 0)} reused sets, {cache.get('fetchedSetCount', 0)} fetched sets",
        "",
        "## Files",
        "",
        f"- Compact catalog: {_download_link(f'{slug}.json', release_url)}",
        f"- Full catalog: {_download_link(f'{slug}.full.json', release_url)}",
        f"- Schema profile: {_download_link(f'{slug}.schema.json', release_url)}",
        "",
        "## Largest Sets",
        "",
        "| Set | Products | Source | TCGplayer |",
        "| --- | ---: | --- | --- |",
    ]
    for set_row in top_sets:
        set_name = set_row.get("name", "")
        lines.append(
            f"| {_escape_table(set_name)} | {set_row.get('productCount', 0)} | `{set_row.get('source', '')}` | "
            f"[Search]({_tcgplayer_search_link(meta.get('productLine', ''), set_name)}) |"
        )
    lines.extend(
        [
            "",
            "## Field Guide",
            "",
            "Use the generated schema JSON in the release for the complete observed field list. Common product fields include:",
            "",
            "- `tcgplayerProductId`: stable TCGplayer product identifier.",
            "- `name`: product/card name as provided by TCGplayer.",
            "- `setId`: TCGplayer set identifier matching the set table.",
            "- `collectorNumber` and `rarity`: normalized card catalog fields when available.",
            "- `imageUrls`: TCGplayer CDN URLs derived from product IDs; images are linked, not republished.",
            "- `priceGuide`: price-guide rows when the endpoint exposes them for the set.",
            "- `metadata`: promoted and raw search metadata, especially useful for game-specific text fields.",
        ]
    )
    return _write(path, lines)


def _change_notes(catalogs: list[dict[str, Any]], previous_release_dir: Path | None) -> list[str]:
    lines = []
    for catalog in sorted(catalogs, key=lambda item: item.get("meta", {}).get("productLine", "")):
        meta = catalog.get("meta", {})
        slug = meta.get("slug", "")
        comparison = _compare_catalog(catalog, previous_release_dir / f"{slug}.full.json" if previous_release_dir else None)
        lines.append(
            f"- {meta.get('productLine', slug)}: {meta.get('setCount', 0)} sets, {meta.get('productCount', 0)} products, "
            f"{comparison}."
        )
    return lines


def _compare_catalog(catalog: dict[str, Any], previous_path: Path | None) -> str:
    if previous_path is None or not previous_path.exists():
        return "no previous full catalog available for comparison"
    previous = _load_json(previous_path)
    current_products = _products_by_id(catalog)
    previous_products = _products_by_id(previous)
    current_ids = set(current_products)
    previous_ids = set(previous_products)
    added = current_ids - previous_ids
    removed = previous_ids - current_ids
    shared = current_ids & previous_ids
    changed = {product_id for product_id in shared if current_products[product_id] != previous_products[product_id]}
    return f"{len(added)} added, {len(removed)} removed, {len(changed)} changed product records"


def _products_by_id(catalog: dict[str, Any]) -> dict[int, dict[str, Any]]:
    products = {}
    for product in catalog.get("products", []):
        product_id = product.get("tcgplayerProductId")
        if product_id is not None:
            products[int(product_id)] = product
    return products


def _field_table(example: dict[str, Any], fields: list[str]) -> str:
    if not fields:
        return "No example fields were available in this release."
    lines = ["| Field | Meaning | Example |", "| --- | --- | --- |"]
    for field in fields:
        lines.append(f"| `{field}` | {_field_description(field)} | {_markdown_example(example.get(field))} |")
    return "\n".join(lines)


def _field_description(field: str) -> str:
    descriptions = {
        "meta": "Build metadata for the catalog.",
        "sets": "Array of set summary objects.",
        "products": "Array of product/card objects.",
        "tcgplayerSetId": "TCGplayer set identifier.",
        "name": "Display name from TCGplayer.",
        "urlName": "TCGplayer URL-friendly name when exposed.",
        "productCount": "Number of products associated with this object.",
        "priceGuideRowCount": "Number of raw price-guide rows observed for the set.",
        "source": "Endpoint path used for this set, usually priceguide or search.",
        "tcgplayerProductId": "TCGplayer product identifier.",
        "productLineId": "TCGplayer product-line identifier.",
        "setId": "TCGplayer set identifier for this product.",
        "collectorNumber": "Card number or collector number when available.",
        "rarity": "Rarity label when available.",
        "foilings": "Observed printings or foil treatments.",
        "imageUrls": "Linked TCGplayer CDN image URLs.",
        "metadata": "Game-specific metadata preserved from search/details payloads.",
        "priceGuide": "Normalized price-guide rows for this product.",
    }
    return descriptions.get(field, "Observed field in the generated JSON.")


def _generated_note(metrics: dict[str, Any], release_tag: str, release_url: str) -> str:
    parts = [f"Generated by tcgjson docs v{CATALOG_DOCS_VERSION}"]
    timestamp = metrics.get("finishedAt") or metrics.get("generated_at")
    if timestamp:
        parts.append(f"last updated {timestamp}")
    if release_tag and release_url:
        parts.append(f"from [{release_tag}]({release_url})")
    elif release_tag:
        parts.append(f"from `{release_tag}`")
    return "_" + "; ".join(parts) + "._"


def _manifest_by_download(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item.get("download_uri", ""): item for item in manifest.get("data", [])}


def _asset_link(name: str, by_name: dict[str, dict[str, Any]], release_url: str) -> str:
    item = by_name.get(name)
    if not item:
        return f"`{name}`"
    return f"{_download_link(name, release_url)} ({_human_bytes(int(item.get('size') or 0))})"


def _download_link(name: str, release_url: str) -> str:
    if not release_url:
        return f"`{name}`"
    download_base = release_url.replace("/releases/tag/", "/releases/download/")
    return f"[`{name}`]({download_base}/{name})"


def _duration(value: Any) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "n/a"
    minutes, remainder = divmod(int(round(seconds)), 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m {remainder}s"
    return f"{minutes}m {remainder}s"


def _human_bytes(value: int) -> str:
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MiB"
    if value >= 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value} B"


def _markdown_example(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    text = text.replace("\n", " ").replace("|", "\\|")
    if len(text) > 90:
        text = text[:87] + "..."
    return f"`{text}`"


def _escape_table(value: Any) -> str:
    return str(value).replace("|", "\\|")


def _tcgplayer_search_link(product_line: str, set_name: str) -> str:
    query = quote_plus(f"{product_line} {set_name}".strip())
    return f"https://www.tcgplayer.com/search/all/product?q={query}"


def _write(path: Path, lines: list[str]) -> Path:
    atomic_write_text(path, "\n".join(lines).rstrip() + "\n")
    return path
