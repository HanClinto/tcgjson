import json
from copy import deepcopy

from tcgjson.docs import generate_catalog_docs
from tcgjson.bulk import write_bulk_manifest, write_metrics_file, write_product_line_files, write_product_schema_files
from tcgjson.games import write_game_support_report


def test_generate_catalog_docs_writes_index_game_and_history(tmp_path) -> None:
    release_dir = tmp_path / "release"
    docs_dir = tmp_path / "docs"
    catalog = {
        "meta": {
            "object": "tcgjson_catalog",
            "generatedAt": "2026-06-30T00:00:00Z",
            "productLine": "Pokemon",
            "slug": "pokemon",
            "sourceMode": "priceguide",
            "setCount": 1,
            "productCount": 1,
        },
        "sets": [
            {
                "tcgplayerSetId": 604,
                "name": "Base Set",
                "urlName": "base-set",
                "releaseDate": "1999-01-09",
                "productCount": 1,
                "priceGuideRowCount": 1,
                "source": "priceguide",
            }
        ],
        "products": [
            {
                "tcgplayerProductId": 42382,
                "name": "Alakazam",
                "productLineId": 3,
                "setId": 604,
                "collectorNumber": "1/102",
                "rarity": "Holo Rare",
                "foilings": ["Holofoil"],
                "imageUrls": ["https://tcgplayer-cdn.tcgplayer.com/product/42382_in_1000x1000.jpg"],
                "metadata": {"stage": "Stage 2"},
            }
        ],
    }
    files = write_product_line_files(release_dir, catalog)
    files.extend(write_product_schema_files(release_dir, catalog))
    larger_catalog = deepcopy(catalog)
    larger_catalog["meta"] = {
        **larger_catalog["meta"],
        "productLine": "Magic: The Gathering",
        "slug": "magic-the-gathering",
        "setCount": 1,
        "productCount": 5,
    }
    larger_catalog["sets"][0] = {
        **larger_catalog["sets"][0],
        "tcgplayerSetId": 1,
        "name": "Limited Edition Alpha",
        "urlName": "limited-edition-alpha",
        "productCount": 5,
    }
    larger_catalog["products"][0] = {
        **larger_catalog["products"][0],
        "tcgplayerProductId": 1,
        "name": "Black Lotus",
        "productLineId": 1,
        "setId": 1,
    }
    files.extend(write_product_line_files(release_dir, larger_catalog))
    files.extend(write_product_schema_files(release_dir, larger_catalog))
    files.append(
        write_metrics_file(
            release_dir,
            {
                "object": "tcgjson_build_metrics",
                "finishedAt": "2026-06-30T00:05:00Z",
                "durationSeconds": 300,
                "productLineCount": 1,
                "requests": {"requests": 2, "retries": 0, "errors": 0},
                "productLines": [
                    {
                        "productLine": "Pokemon",
                        "slug": "pokemon",
                        "durationSeconds": 300,
                        "setCount": 1,
                        "productCount": 1,
                        "cache": {"reusedSetCount": 0, "fetchedSetCount": 1},
                    }
                ],
            },
        )
    )
    write_game_support_report(
        {
            "object": "tcgjson_game_support",
            "games": [
                {
                    "name": "Pokemon",
                    "slug": "pokemon",
                    "tcgplayerProductLineId": 3,
                    "tcgplayerUrlName": "pokemon",
                    "popular": True,
                    "manualInclude": False,
                    "manualExclude": False,
                    "enabled": True,
                    "resources": {
                        "tcgplayer": {
                            "searchUrl": "https://www.tcgplayer.com/search/pokemon/product?productLineName=pokemon&page=1",
                            "priceGuideUrl": "https://www.tcgplayer.com/categories/trading-and-collectible-card-games/pokemon/price-guides",
                        }
                    },
                },
                {
                    "name": "Alpha Clash",
                    "slug": "alpha-clash",
                    "tcgplayerProductLineId": 78,
                    "tcgplayerUrlName": "alpha-clash",
                    "popular": False,
                    "manualInclude": False,
                    "manualExclude": False,
                    "enabled": False,
                }
            ],
        },
        release_dir / "games.md",
        json_output=release_dir / "games.json",
    )
    write_bulk_manifest(release_dir, files)
    previous_dir = tmp_path / "previous"
    previous_catalog = {**catalog, "products": []}
    previous_files = write_product_line_files(previous_dir, previous_catalog)
    write_bulk_manifest(previous_dir, previous_files)

    written = generate_catalog_docs(
        release_dir=release_dir,
        output_dir=docs_dir,
        previous_release_dir=previous_dir,
        release_tag="weekly-test",
        release_url="https://example.test/release",
    )

    assert {path.relative_to(docs_dir).as_posix() for path in written} == {
        "README.md",
        "objects.md",
        "release-history.md",
        "games.md",
        "games/magic-the-gathering.md",
        "games/pokemon.md",
    }
    index = (docs_dir / "README.md").read_text(encoding="utf-8")
    objects = (docs_dir / "objects.md").read_text(encoding="utf-8")
    game = (docs_dir / "games" / "pokemon.md").read_text(encoding="utf-8")
    games_index = (docs_dir / "games.md").read_text(encoding="utf-8")
    history = (docs_dir / "release-history.md").read_text(encoding="utf-8")

    assert "[Pokemon](games/pokemon.md)" in index
    assert "| Banner | Game | Sets | Products | Full JSON | Compact JSON | Schema |" in index
    assert index.index("[Magic: The Gathering](games/magic-the-gathering.md)") < index.index("[Pokemon](games/pokemon.md)")
    assert "| ![Pokemon](https://tcgplayer-cdn.tcgplayer.com/set_icon/604BaseSet.png) | [Pokemon](games/pokemon.md) | 1 | 1 |" in index
    assert "tcgjson publishes reliable, regularly updated bulk catalog JSON for trading card games listed on TCGplayer." in index
    assert "## Project Goals" in index
    assert "- Reliable bulk data: dependable card, set, and metadata snapshots that other sites and applications can build on." in index
    assert "- Automatic updates: catalog refreshes run on [GitHub Actions](https://github.com/HanClinto/tcgjson/actions/workflows/weekly-release.yml)" in index
    assert "- Practical downloads: inspired by [mtgjson](https://mtgjson.com/) and [Scryfall bulk data](https://scryfall.com/docs/api/bulk-data)" in index
    assert "- Reviewable formats: these docs are generated from source each release to document the format of game-specific information available for each card." in index
    assert "[View the project on GitHub](https://github.com/HanClinto/tcgjson)" in index
    assert "## Release Artifacts" not in index
    assert "<summary>Example bulk manifest object</summary>" in objects
    assert "<summary>Example bulk manifest item object</summary>" in objects
    assert "<summary>Example full catalog object shape</summary>" in objects
    assert "<summary>Example compact catalog object shape</summary>" in objects
    assert "<summary>Example full set object</summary>" in objects
    assert "<summary>Example full product object</summary>" in objects
    assert "<summary>Example compact product object</summary>" in objects
    assert objects.index("<summary>Example full catalog object shape</summary>") < objects.index("| `meta` | Build metadata for the catalog.")
    assert objects.index("<summary>Example compact catalog object shape</summary>") < objects.index("| `meta` | Build metadata for the catalog.")
    assert objects.index("<summary>Example full set object</summary>") < objects.index("| `tcgplayerSetId` | TCGplayer set identifier.")
    assert objects.index("<summary>Example full product object</summary>") < objects.index("| `tcgplayerProductId` | TCGplayer product identifier.")
    assert objects.index("<summary>Example compact product object</summary>") < objects.index("| `tcgplayerProductId` | TCGplayer product identifier.")
    assert '"products": [' in objects
    assert '"priceGuide":' not in objects
    assert '"lowPrice":' not in objects
    assert '"marketPrice":' not in objects
    assert '"medianPrice":' not in objects
    assert "TCGplayer" in game
    assert "`games.json` is the discovery/support report behind this page; `bulk-data.json` is the release manifest" in games_index
    assert "| Game | TCGplayer Category ID | Sets | Products |" in games_index
    assert "| [Pokemon](games/pokemon.md) | 3 | 1 | 1 |" in games_index
    assert "Catalog Page" not in games_index
    assert "TCGplayer ID" not in games_index
    assert "Want one of these product lines added? Open a prefilled GitHub issue from the Request column." in games_index
    assert "| Game | TCGplayer Category ID | URL Name | Request |" in games_index
    assert "| Alpha Clash | 78 | `alpha-clash` | [Request](https://github.com/HanClinto/tcgjson/issues/new?" in games_index
    assert "Request+catalog+support+for+Alpha+Clash" in games_index
    assert "## TCGplayer Resources" in game
    assert "[Price guide](https://www.tcgplayer.com/categories/trading-and-collectible-card-games/pokemon/price-guides)" in game
    assert "<summary>Game object raw JSON</summary>" in game
    assert game.index("<summary>Game object raw JSON</summary>") < game.index("## Files")
    assert '"tcgplayerProductLineId": 3' in game
    assert "Compact catalog: [`pokemon.json`](https://example.test/release/pokemon.json) (" in game
    assert "Full catalog: [`pokemon.full.json`](https://example.test/release/pokemon.full.json) (" in game
    assert "<summary>Example compact product object</summary>" in game
    assert "<summary>Example full product object</summary>" in game
    assert '"metadata": {' in game
    assert "Latest Set Icons" not in game
    assert "## Recently Released Sets" in game
    assert "![Base Set](https://tcgplayer-cdn.tcgplayer.com/set_icon/604BaseSet.png)" in game
    assert '| ![Base Set](https://tcgplayer-cdn.tcgplayer.com/set_icon/604BaseSet.png) | <a class="tcg-set-link" href="https://www.tcgplayer.com/search/pokemon/base-set?productLineName=pokemon&amp;setName=base-set&amp;view=grid&amp;ProductTypeName=Cards&amp;page=1" data-set-preview="' in game
    assert 'Base Set</a> | 1999-01-09 | 1 | `priceguide` |' in game
    assert "%22type%22%3A%22set%22" in game
    assert "%22rawJson%22%3A%7B%22tcgplayerSetId%22%3A604" in game
    assert "TCGplayer |" not in game
    assert "## Recently Added Cards" in game
    assert "| Card | Set | Set Release Date | Added To tcgjson | Rarity |" in game
    assert '| <a class="tcg-card-link" href="https://www.tcgplayer.com/product/42382" data-card-preview="' in game
    assert 'Alakazam</a> | Base Set | 1999-01-09 | [weekly-test](https://example.test/release) | Holo Rare |' in game
    assert "%22imageUrl%22%3A%22https%3A%2F%2Ftcgplayer-cdn.tcgplayer.com%2Fproduct%2F42382_in_1000x1000.jpg%22" in game
    assert "%22rawJson%22%3A%7B%22tcgplayerProductId%22%3A42382" in game
    assert "## Product Field Coverage" in game
    assert "| `tcgplayerProductId` | integer | 1 / 1 | 100% | `42382` |" in game
    assert "## Game-Specific Metadata Coverage" in game
    assert "The table follows the metadata JSON structure and sorts fields alphabetically by path." in game
    assert "| `stage` | string | 1 / 1 | 100% | `Stage 2` |" in game
    assert "weekly-test" in history
    assert "1 added, 0 removed, 0 changed product records" in history
    assert json.loads((release_dir / "bulk-data.json").read_text(encoding="utf-8"))["object"] == "list"
