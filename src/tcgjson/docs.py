"""Generate source-controlled Markdown documentation from release artifacts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus

from .atomic import atomic_write_text
from .normalize import compact_product


CATALOG_DOCS_VERSION = 1
PROJECT_URL = "https://github.com/HanClinto/tcgjson"
RELEASES_URL = "https://github.com/HanClinto/tcgjson/releases"
WEEKLY_WORKFLOW_URL = "https://github.com/HanClinto/tcgjson/actions/workflows/weekly-release.yml"


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
    catalogs = [_catalog_with_set_icon_urls(_load_json(release_dir / item["download_uri"])) for item in catalog_items]
    catalogs.sort(key=lambda catalog: catalog.get("meta", {}).get("productLine", ""))
    schema_profiles = _load_schema_profiles(release_dir, catalogs)

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
    games_by_slug = {game.get("slug"): game for game in games.get("games", [])}
    for catalog in catalogs:
        slug = catalog["meta"]["slug"]
        written.append(
            _write_game_page(
                game_dir / f"{slug}.md",
                catalog,
                metrics,
                manifest,
                schema_profiles.get(slug, {}),
                games_by_slug.get(slug, {}),
                previous_release_dir,
                release_tag,
                release_url,
            )
        )
    return written


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_schema_profiles(release_dir: Path, catalogs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    profiles = {}
    for catalog in catalogs:
        slug = catalog.get("meta", {}).get("slug", "")
        path = release_dir / f"{slug}.schema.json"
        if path.exists():
            profiles[slug] = _load_json(path)
    return profiles


def _catalog_with_set_icon_urls(catalog: dict[str, Any]) -> dict[str, Any]:
    hydrated = dict(catalog)
    hydrated["sets"] = [_set_with_icon_url(set_row) for set_row in catalog.get("sets", [])]
    return hydrated


def _set_with_icon_url(set_row: dict[str, Any]) -> dict[str, Any]:
    if set_row.get("iconUrl"):
        return set_row
    hydrated = dict(set_row)
    set_id = hydrated.get("tcgplayerSetId")
    set_name = hydrated.get("name", "")
    if set_id and set_name:
        hydrated["iconUrl"] = _tcgplayer_set_icon_url(set_id, set_name)
    return hydrated


def _tcgplayer_set_icon_url(set_id: Any, set_name: str) -> str:
    compact_name = _compact_set_icon_name(set_name)
    if not compact_name:
        return ""
    return f"https://tcgplayer-cdn.tcgplayer.com/set_icon/{set_id}{compact_name}.png"


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


def _write_index(path: Path, catalogs: list[dict[str, Any]], metrics: dict[str, Any], manifest: dict[str, Any], release_tag: str, release_url: str) -> Path:
    lines = [
        "# tcgjson Catalog Docs",
        "",
        "tcgjson publishes reliable, regularly updated bulk catalog JSON for trading card games listed on TCGplayer.",
        "",
        "## Project Goals",
        "",
        "- Reliable bulk data: dependable card, set, and metadata snapshots that other sites and applications can build on.",
        f"- Automatic updates: catalog refreshes run on [GitHub Actions]({WEEKLY_WORKFLOW_URL}) so future updates are not dependent on manual releases or human follow-through.",
        "- Broad TCGplayer coverage: weekly catalog files for multiple card games listed on TCGplayer, not just one product line.",
        "- Practical downloads: inspired by [mtgjson](https://mtgjson.com/) and [Scryfall bulk data](https://scryfall.com/docs/api/bulk-data), with release files published through [GitHub Releases](https://github.com/HanClinto/tcgjson/releases).",
        "- Reviewable formats: these docs are generated from source each release to document the format of game-specific information available for each card.",
        "",
        _generated_note(metrics, release_tag, release_url),
        "",
        "## Start Here",
        "",
        "- [Object guide](objects.md) explains the catalog, set, product, price, and manifest shapes.",
        "- [Game index](games.md) lists supported and discovered TCGplayer product lines.",
        "- [Release history](release-history.md) summarizes each generated release and its changes.",
        f"- [View the project on GitHub]({PROJECT_URL}) for source, issues, and release automation.",
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
            "tcgjson focuses on singles catalog data: products, sets, collector numbers, rarities, image URLs, and metadata where TCGplayer exposes it.",
            "It does not publish pricing data, marketplace listings, seller inventory, sealed products, or downloaded card images.",
            "Each game page includes product field coverage and game-specific metadata coverage generated from the schema profile for that release.",
            "The build may use TCGplayer priceguide endpoints as a catalog discovery path, but price values are stripped from release files because weekly catalog snapshots are not a reliable pricing source.",
            "",
            "## Publishing Schedule",
            "",
            "Catalogs are rebuilt automatically on GitHub Actions once per week. The goal is to scrape TCGplayer's public catalog endpoints once, package the results into bulk downloads, and reduce repeated API traffic from people who only need semi-regular catalog snapshots.",
            "",
            "This is intentionally not an hourly or daily scraper. If you need card pricing or near-real-time market data, tcgjson is not the right source.",
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
    lines = [
        "# Object Guide",
        "",
        "These object notes are generated from the release files and written for people exploring the data for the first time.",
        "The names are intentionally plain: catalogs contain sets and products; products may contain optional metadata but never published pricing fields.",
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
        _field_table(example_set, ["tcgplayerSetId", "name", "urlName", "releaseDate", "iconUrl", "productCount", "priceGuideRowCount", "source"]),
        "",
        "## Product Object",
        "",
        "A product is one catalog card/product record. Most integrations should start with `tcgplayerProductId`, `name`, `setId`, `collectorNumber`, `rarity`, and `imageUrls`.",
        "",
        _field_table(example_product, ["tcgplayerProductId", "name", "productLineId", "setId", "collectorNumber", "rarity", "foilings", "imageUrls", "metadata", "skus"]),
        "",
        "## Pricing",
        "",
        "Pricing fields are intentionally omitted from release files. Weekly catalog snapshots are intended for product identity and metadata, not current market prices.",
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


def _write_game_page(
    path: Path,
    catalog: dict[str, Any],
    metrics: dict[str, Any],
    manifest: dict[str, Any],
    schema_profile: dict[str, Any],
    game: dict[str, Any],
    previous_release_dir: Path | None,
    release_tag: str,
    release_url: str,
) -> Path:
    meta = catalog.get("meta", {})
    slug = meta.get("slug", "")
    line_metrics = next((line for line in metrics.get("productLines", []) if line.get("slug") == slug), {})
    cache = line_metrics.get("cache", {})
    sets = sorted(catalog.get("sets", []), key=lambda item: item.get("name", ""))
    products = catalog.get("products", [])
    by_name = _manifest_by_download(manifest)
    added_to_tcgjson = _release_reference(metrics, release_tag, release_url)
    recent_sets = sorted(
        sets,
        key=lambda item: (str(item.get("releaseDate") or ""), int(item.get("tcgplayerSetId") or 0)),
        reverse=True,
    )[:12]
    recently_added_products = _recently_added_products(
        catalog,
        previous_release_dir / f"{slug}.full.json" if previous_release_dir else None,
    )
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
        f"- Compact catalog: {_asset_link(f'{slug}.json', by_name, release_url)}",
        f"- Full catalog: {_asset_link(f'{slug}.full.json', by_name, release_url)}",
        f"- Schema profile: {_asset_link(f'{slug}.schema.json', by_name, release_url)}",
        "",
        *_catalog_example_blocks(catalog),
        *_resource_section(game.get("resources", {})),
        "## Recently Released Sets",
        "",
        "| Banner | Set | Release Date | Products | Source |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for set_row in recent_sets:
        set_name = set_row.get("name", "")
        icon_url = set_row.get("iconUrl", "")
        icon_cell = f"![{_escape_table(set_name)}]({icon_url})" if icon_url else ""
        search_link = _tcgplayer_set_product_link(set_row, game.get("tcgplayerUrlName", ""), meta.get("productLine", ""), set_name)
        lines.append(
            f"| {icon_cell} | [{_escape_table(set_name)}]({search_link}) | {_escape_table(_date_only(set_row.get('releaseDate', '')))} | {set_row.get('productCount', 0)} | `{set_row.get('source', '')}` |"
        )
    if recently_added_products:
        lines.extend(
            [
                "",
                "## Recently Added Cards",
                "",
                "| Card | Set | Set Release Date | Added To tcgjson | Rarity |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for product in recently_added_products:
            product_name = product.get("name", "")
            set_name = product.get("setName", "")
            product_link = _tcgplayer_product_link(product, meta.get("productLine", ""), product_name, set_name)
            lines.append(
                f"| [{_escape_table(product_name)}]({product_link}) | {_escape_table(set_name)} | "
                f"{_escape_table(_date_only(product.get('setReleaseDate', '')))} | {added_to_tcgjson} | {_escape_table(product.get('rarity', ''))} |"
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
            "- `metadata`: promoted and raw search metadata, especially useful for game-specific text fields.",
        ]
    )
    lines.extend(_schema_profile_sections(schema_profile))
    return _write(path, lines)


def _resource_section(resources: dict[str, Any]) -> list[str]:
    tcgplayer = resources.get("tcgplayer", {}) if isinstance(resources, dict) else {}
    links = []
    for label, key in [
        ("Shop/Search on TCGplayer", "searchUrl"),
        ("Price guide", "priceGuideUrl"),
        ("Articles", "articlesUrl"),
        ("Decks", "decksUrl"),
        ("Advanced search", "advancedSearchUrl"),
    ]:
        url = tcgplayer.get(key)
        if url:
            links.append(f"- [{label}]({url})")
    feature = tcgplayer.get("feature")
    if isinstance(feature, dict) and feature.get("title") and feature.get("url"):
        links.append(f"- Featured on TCGplayer: [{feature.get('title')}]({feature.get('url')})")
    if not links:
        return []
    lines = ["## TCGplayer Resources", "", *links, ""]
    return lines


def _catalog_example_blocks(catalog: dict[str, Any]) -> list[str]:
    product = next(iter(catalog.get("products", [])), {})
    if not product:
        return []
    compact_example = compact_product(product)
    full_example = product
    return [
        "<details>",
        "<summary>Example compact product object</summary>",
        "",
        "```json",
        _json_example(compact_example),
        "```",
        "",
        "</details>",
        "",
        "<details>",
        "<summary>Example full product object</summary>",
        "",
        "```json",
        _json_example(full_example),
        "```",
        "",
        "</details>",
        "",
    ]


def _schema_profile_sections(profile: dict[str, Any]) -> list[str]:
    fields = profile.get("fields", [])
    if not fields:
        return [
            "",
            "## Product Field Coverage",
            "",
            "No schema profile was available for this catalog release.",
        ]

    product_count = int(profile.get("productCount") or 0)
    top_level_fields = [field for field in fields if _is_top_level_schema_field(field)]
    metadata_fields = [field for field in fields if _is_metadata_leaf_field(field)]

    lines = [
        "",
        "## Product Field Coverage",
        "",
        f"The schema profile observed {profile.get('fieldCount', len(fields))} product fields across {product_count} product records.",
        "Population counts show how often a field had a non-empty value in this release.",
        "",
        _schema_field_table(top_level_fields, product_count, limit=30),
    ]
    if metadata_fields:
        lines.extend(
            [
                "",
                "## Game-Specific Metadata Coverage",
                "",
                "These fields come from TCGplayer search/detail metadata and vary by game.",
                "The table follows the metadata JSON structure and sorts fields alphabetically by path.",
                "",
                _schema_field_table(metadata_fields, product_count, limit=30, strip_prefix="metadata.", sort_key=_metadata_field_sort_key),
            ]
        )
    return lines


def _is_top_level_schema_field(field: dict[str, Any]) -> bool:
    path = field.get("path", "")
    return "." not in path and "[]" not in path


def _is_metadata_leaf_field(field: dict[str, Any]) -> bool:
    path = field.get("path", "")
    types = set(field.get("types", []))
    if not path.startswith("metadata.") or path.endswith("[]"):
        return False
    return types != {"object"} and types != {"array"}


def _schema_field_table(
    fields: list[dict[str, Any]],
    product_count: int,
    *,
    limit: int,
    strip_prefix: str = "",
    sort_key: Any = None,
) -> str:
    if not fields:
        return "No populated fields were available in this release."
    lines = ["| Field | Types | Products | Populated | Example |", "| --- | --- | ---: | ---: | --- |"]
    sort_key = sort_key or _schema_field_sort_key
    for field in sorted(fields, key=sort_key)[:limit]:
        path = str(field.get("path", ""))
        if strip_prefix and path.startswith(strip_prefix):
            path = path[len(strip_prefix) :]
        populated_count = int(field.get("populatedCount") or 0)
        lines.append(
            f"| `{_escape_table(path)}` | {_escape_table(', '.join(field.get('types', [])))} | "
            f"{populated_count} / {product_count} | {_format_percent(field.get('populatedPercent'))} | "
            f"{_markdown_example(field.get('example'))} |"
        )
    return "\n".join(lines)


def _schema_field_sort_key(field: dict[str, Any]) -> tuple[int, float, str]:
    priority = {
        "tcgplayerProductId": 0,
        "name": 1,
        "productLineId": 2,
        "setId": 3,
        "setName": 4,
        "collectorNumber": 5,
        "rarity": 6,
        "foilings": 7,
        "imageUrls": 8,
        "metadata": 9,
        "skus": 10,
    }
    path = str(field.get("path", ""))
    return (priority.get(path, 100), -float(field.get("populatedPercent") or 0), path)


def _metadata_field_sort_key(field: dict[str, Any]) -> tuple[str]:
    return (str(field.get("path", "")),)


def _format_percent(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "0%"
    if number.is_integer():
        return f"{int(number)}%"
    return f"{number:.2f}".rstrip("0").rstrip(".") + "%"


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


def _recently_added_products(catalog: dict[str, Any], previous_path: Path | None, limit: int = 12) -> list[dict[str, Any]]:
    if previous_path is None or not previous_path.exists():
        return []
    previous = _load_json(previous_path)
    current_products = _products_by_id(catalog)
    previous_ids = set(_products_by_id(previous))
    sets_by_id = {int(set_row.get("tcgplayerSetId") or 0): set_row for set_row in catalog.get("sets", [])}
    added_products = []
    for product_id in sorted(set(current_products) - previous_ids, reverse=True):
        product = dict(current_products[product_id])
        set_row = sets_by_id.get(int(product.get("setId") or 0), {})
        product["setName"] = set_row.get("name", "")
        product["setReleaseDate"] = set_row.get("releaseDate", "")
        added_products.append(product)
    added_products.sort(
        key=lambda product: (str(product.get("setReleaseDate") or ""), int(product.get("tcgplayerProductId") or 0)),
        reverse=True,
    )
    return added_products[:limit]


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
        "releaseDate": "Set release date from TCGplayer when exposed.",
        "iconUrl": "Linked TCGplayer CDN set banner URL derived from the set ID and clean set name.",
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
        "skus": "Optional SKU rows from product details builds.",
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
    text = text.replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    if len(text) > 90:
        text = text[:87] + "..."
    return f"`{text}`"


def _json_example(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _escape_table(value: Any) -> str:
    return str(value).replace("|", "\\|")


def _date_only(value: Any) -> str:
    return str(value).split("T", 1)[0]


def _release_reference(metrics: dict[str, Any], release_tag: str, release_url: str) -> str:
    label = release_tag or _date_only(metrics.get("finishedAt", "")) or "this release"
    if release_url:
        return f"[{_escape_table(label)}]({release_url})"
    return _escape_table(label)


def _tcgplayer_search_link(product_line: str, set_name: str) -> str:
    query = quote_plus(f"{product_line} {set_name}".strip())
    return f"https://www.tcgplayer.com/search/all/product?q={query}&productTypeName=Cards"


def _tcgplayer_set_product_link(set_row: dict[str, Any], product_line_url_name: str, product_line: str, set_name: str) -> str:
    set_url_name = str(set_row.get("urlName") or "").strip()
    product_line_url_name = str(product_line_url_name or "").strip()
    if product_line_url_name and set_url_name:
        return (
            f"https://www.tcgplayer.com/search/{quote(product_line_url_name, safe='')}/{quote(set_url_name, safe='')}"
            f"?productLineName={quote_plus(product_line_url_name)}&setName={quote_plus(set_url_name)}&view=grid&ProductTypeName=Cards&page=1"
        )
    set_id = set_row.get("tcgplayerSetId")
    if set_id:
        return f"https://www.tcgplayer.com/search/all/product?setId={set_id}&productTypeName=Cards"
    return _tcgplayer_search_link(product_line, set_name)


def _tcgplayer_card_search_link(product_line: str, product_name: str, set_name: str) -> str:
    query = quote_plus(f"{product_line} {product_name} {set_name}".strip())
    return f"https://www.tcgplayer.com/search/all/product?q={query}&productTypeName=Cards"


def _tcgplayer_product_link(product: dict[str, Any], product_line: str, product_name: str, set_name: str) -> str:
    product_id = product.get("tcgplayerProductId")
    if product_id:
        return f"https://www.tcgplayer.com/product/{product_id}"
    return _tcgplayer_card_search_link(product_line, product_name, set_name)


def _write(path: Path, lines: list[str]) -> Path:
    atomic_write_text(path, "\n".join(lines).rstrip() + "\n")
    return path
