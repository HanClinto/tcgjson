import json

import requests

from tcgjson.cli import build_parser

from tcgjson.bulk import (
    assemble_release,
    build_release,
    fetch_product_line,
    write_bulk_manifest,
    write_product_line_files,
    write_product_schema_files,
    write_set_cache_files,
)
from tcgjson.tcgplayer import RequestStats


class CachedSetClient:
    requests = 0
    retries = 0
    errors = 0

    def stats(self):
        return RequestStats(self.requests, self.retries, self.errors)

    def get_product_lines(self):
        return [{"productLineId": 3, "productLineName": "Pokemon", "productLineUrlName": "pokemon"}]

    def get_set_names(self, product_line_id, *, active=True):
        assert product_line_id == 3
        return [{"setNameId": 10, "name": "Cached Set", "urlName": "cached-set"}]

    def get_priceguide_set_cards(self, set_id, *, rows=5000, product_type_id=1):
        raise AssertionError("cached set should not be refetched")


class SearchFallbackClient(CachedSetClient):
    def get_product_lines(self):
        return [
            {"productLineId": 79, "productLineName": "Star Wars: Unlimited", "productLineUrlName": "star-wars-unlimited"}
        ]

    def get_set_names(self, product_line_id, *, active=True):
        assert product_line_id == 79
        return [{"setNameId": 23405, "name": "Spark of Rebellion", "urlName": "spark-of-rebellion"}]

    def get_priceguide_set_cards(self, set_id, *, rows=5000, product_type_id=1):
        assert set_id == 23405
        return {}

    def iter_search_products(self, *, product_line_name, set_name, page_size=50):
        assert product_line_name == "Star Wars: Unlimited"
        assert set_name == "Spark of Rebellion"
        yield {
            "productId": 540213,
            "productName": "Overwhelming Barrage",
            "productLineId": 79,
            "productLineName": "Star Wars: Unlimited",
            "productLineUrlName": "Star Wars Unlimited",
            "setId": 23405,
            "setName": "Spark of Rebellion",
            "setUrlName": "Spark of Rebellion",
            "setCode": "SOR",
            "rarityName": "Uncommon",
            "lowestPrice": 0.45,
            "marketPrice": 0.63,
            "medianPrice": 0.95,
            "customAttributes": {"number": "092/252", "releaseDate": "2024-03-08T00:00:00Z"},
        }


class PriceguideWithSearchMetadataClient(SearchFallbackClient):
    def get_priceguide_set_cards(self, set_id, *, rows=5000, product_type_id=1):
        assert set_id == 23405
        return {
            "result": [
                {
                    "productID": 540213,
                    "productName": "Overwhelming Barrage",
                    "number": "092/252",
                    "rarity": "Uncommon",
                    "printing": "Normal",
                    "condition": "Near Mint",
                    "lowPrice": 0.45,
                    "marketPrice": 0.63,
                }
            ]
        }


class CheckpointOnlyClient(SearchFallbackClient):
    def get_priceguide_set_cards(self, set_id, *, rows=5000, product_type_id=1):
        raise AssertionError("set checkpoint should be reused before fetching price-guide rows")

    def iter_search_products(self, *, product_line_name, set_name, page_size=50):
        raise AssertionError("set checkpoint should be reused before search fallback")


class DetailsErrorClient(SearchFallbackClient):
    def get_product_details(self, product_id):
        raise requests.HTTPError("400 Client Error")


class DetailsClient(SearchFallbackClient):
    detail_requests = 0

    def get_product_details(self, product_id):
        self.detail_requests += 1
        return {
            "imageCount": 2,
            "skus": [{"sku": 99, "condition": "Near Mint", "variant": "Normal", "language": "English"}],
        }


class CachedDetailsOnlyClient(DetailsClient):
    def get_product_details(self, product_id):
        raise AssertionError("product details should be loaded from cache")


def test_write_manifest_records_sizes_and_hashes(tmp_path) -> None:
    catalog = {
        "meta": {
            "object": "tcgjson_catalog",
            "version": 1,
            "source": "tcgplayer",
            "sourceMode": "priceguide",
            "generatedAt": "2026-06-29T00:00:00Z",
            "productLine": "Pokemon",
            "slug": "pokemon",
            "setCount": 1,
            "productCount": 1,
        },
        "sets": [{"tcgplayerSetId": 1, "name": "Set", "productCount": 1}],
        "products": [
            {
                "tcgplayerProductId": 10,
                "name": "Card",
                "productLineId": 3,
                "setId": 1,
                "collectorNumber": "1",
                "rarity": "Common",
                "foilings": [],
                "imageUrls": [],
                "priceGuide": [],
            }
        ],
    }
    files = write_product_line_files(tmp_path, catalog)
    files.extend(write_set_cache_files(tmp_path, catalog))
    manifest = write_bulk_manifest(tmp_path, files)

    assert [item["type"] for item in manifest["data"]] == [
        "pokemon_catalog",
        "pokemon_catalog_full",
        "pokemon_set_1_cache",
    ]
    assert json.loads((tmp_path / "bulk-data.json").read_text())["object"] == "list"
    for item in manifest["data"]:
        assert (tmp_path / item["download_uri"]).stat().st_size == item["size"]


def test_build_parser_accepts_with_details_and_legacy_with_skus() -> None:
    parser = build_parser()

    assert parser.parse_args(["build", "--with-details"]).with_details is True
    assert parser.parse_args(["build", "--with-skus"]).with_details is True
    assert parser.parse_args(["build"]).data_cache_dir.name == "data-cache"
    assert parser.parse_args(["build", "--data-cache-dir", "cache-data"]).data_cache_dir.name == "cache-data"
    assert parser.parse_args(["build", "--detail-cache-dir", "details"]).detail_cache_dir.name == "details"


def test_write_product_schema_files_profiles_full_catalog_fields(tmp_path) -> None:
    catalog = {
        "meta": {"productLine": "Pokemon", "slug": "pokemon"},
        "products": [
            {
                "tcgplayerProductId": 10,
                "name": "Card",
                "productLineId": 3,
                "setId": 1,
                "metadata": {"rulesText": "Draw a card.", "colors": ["Blue"]},
            }
        ],
    }

    files = write_product_schema_files(tmp_path, catalog)
    profile = json.loads((tmp_path / "pokemon.schema.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "pokemon.schema.md").read_text(encoding="utf-8")

    assert {item["type"] for item in files} == {"pokemon_schema", "pokemon_schema_markdown"}
    assert any(field["path"] == "metadata.rulesText" for field in profile["fields"])
    assert "metadata.colors[]" in markdown


def test_fetch_product_line_reuses_cached_full_catalog(tmp_path) -> None:
    cached = {
        "meta": {
            "object": "tcgjson_catalog",
            "generatedAt": "2026-06-01T00:00:00Z",
            "productLine": "Pokemon",
            "slug": "pokemon",
        },
        "sets": [
            {
                "tcgplayerSetId": 10,
                "name": "Cached Set",
                "urlName": "cached-set",
                "productCount": 1,
                "priceGuideRowCount": 1,
            }
        ],
        "products": [
            {
                "tcgplayerProductId": 100,
                "name": "Cached Card",
                "set": {"id": 10, "name": "Cached Set"},
                "collectorNumber": "001",
                "rarity": "Common",
                "foilings": ["Normal"],
                "imageUrl": "https://tcgplayer-cdn.tcgplayer.com/product/100_in_1000x1000.jpg",
                "priceGuide": [],
            }
        ],
    }
    (tmp_path / "pokemon.full.json").write_text(json.dumps(cached), encoding="utf-8")

    catalog = fetch_product_line(CachedSetClient(), 3, cache_dir=tmp_path)

    assert catalog["meta"]["cache"]["reusedSetCount"] == 1
    assert catalog["meta"]["cache"]["fetchedSetCount"] == 0
    assert catalog["products"][0]["name"] == "Cached Card"
    assert catalog["products"][0]["imageUrls"] == ["https://tcgplayer-cdn.tcgplayer.com/product/100_in_1000x1000.jpg"]
    assert "imageUrl" not in catalog["products"][0]


def test_fetch_product_line_reuses_cached_set_file(tmp_path) -> None:
    cached = {
        "object": "tcgjson_set_cache",
        "version": 1,
        "generatedAt": "2026-06-01T00:00:00Z",
        "sourceGeneratedAt": "2026-06-01T00:00:00Z",
        "productLineId": 3,
        "slug": "pokemon",
        "tcgplayerSetId": 10,
        "set": {
            "tcgplayerSetId": 10,
            "name": "Cached Set",
            "urlName": "cached-set",
            "productCount": 1,
            "priceGuideRowCount": 1,
        },
        "products": [
            {
                "tcgplayerProductId": 100,
                "name": "Cached Card",
                "productLineId": 3,
                "setId": 10,
                "collectorNumber": "001",
                "rarity": "Common",
                "foilings": ["Normal"],
                "imageUrls": ["https://tcgplayer-cdn.tcgplayer.com/product/100_in_1000x1000.jpg"],
                "priceGuide": [],
            }
        ],
    }
    (tmp_path / "pokemon.set.10.json").write_text(json.dumps(cached), encoding="utf-8")

    catalog = fetch_product_line(CachedSetClient(), 3, cache_dir=tmp_path)

    assert catalog["meta"]["cache"]["reusedSetCount"] == 1
    assert catalog["meta"]["cache"]["sourceGeneratedAt"] == "2026-06-01T00:00:00Z"
    assert catalog["products"][0]["name"] == "Cached Card"


def test_fetch_product_line_emits_plain_progress_logs(tmp_path, capsys) -> None:
    cached = {
        "object": "tcgjson_set_cache",
        "version": 1,
        "generatedAt": "2026-06-01T00:00:00Z",
        "sourceGeneratedAt": "2026-06-01T00:00:00Z",
        "productLineId": 3,
        "slug": "pokemon",
        "tcgplayerSetId": 10,
        "set": {"tcgplayerSetId": 10, "name": "Cached Set", "productCount": 1},
        "products": [
            {
                "tcgplayerProductId": 100,
                "name": "Cached Card",
                "productLineId": 3,
                "setId": 10,
                "imageUrls": [],
                "priceGuide": [],
            }
        ],
    }
    (tmp_path / "pokemon.set.10.json").write_text(json.dumps(cached), encoding="utf-8")

    fetch_product_line(CachedSetClient(), 3, cache_dir=tmp_path, log_progress=True)

    output = capsys.readouterr().out
    assert "pokemon: starting 1 set(s)" in output
    assert "pokemon: set 1/1 10 'Cached Set' reused 1 product(s)" in output
    assert "pokemon: finished 1 set(s), 1 product(s)" in output


def test_fetch_product_line_falls_back_to_search_when_priceguide_is_empty() -> None:
    catalog = fetch_product_line(SearchFallbackClient(), 79)

    assert catalog["sets"][0]["source"] == "search"
    assert catalog["sets"][0]["priceGuideRowCount"] == 0
    assert catalog["sets"][0]["productCount"] == 1
    assert catalog["products"][0]["name"] == "Overwhelming Barrage"
    assert catalog["products"][0]["collectorNumber"] == "092/252"
    assert catalog["products"][0]["priceGuide"][0]["marketPrice"] == 0.63
    assert catalog["sets"][0]["searchMetadataProductCount"] == 1
    assert catalog["products"][0]["metadata"]["customAttributes"]["releaseDate"] == "2024-03-08T00:00:00Z"


def test_fetch_product_line_enriches_priceguide_products_with_search_metadata() -> None:
    catalog = fetch_product_line(PriceguideWithSearchMetadataClient(), 79)

    assert catalog["sets"][0]["source"] == "priceguide"
    assert catalog["sets"][0]["searchMetadataProductCount"] == 1
    assert catalog["products"][0]["metadata"]["customAttributes"]["releaseDate"] == "2024-03-08T00:00:00Z"


def test_fetch_product_line_writes_and_reuses_set_checkpoints(tmp_path) -> None:
    checkpoint_dir = tmp_path / "set-checkpoints"
    first_catalog = fetch_product_line(SearchFallbackClient(), 79, checkpoint_dir=checkpoint_dir)

    assert (checkpoint_dir / "star-wars-unlimited" / "search" / "23405.json").exists()
    assert first_catalog["meta"]["cache"]["fetchedSetCount"] == 1

    second_catalog = fetch_product_line(CheckpointOnlyClient(), 79, checkpoint_dir=checkpoint_dir)

    assert second_catalog["meta"]["cache"]["reusedSetCheckpointCount"] == 1
    assert second_catalog["meta"]["cache"]["fetchedSetCount"] == 0
    assert second_catalog["products"][0]["name"] == "Overwhelming Barrage"
    assert "imageUrl" not in second_catalog["products"][0]


def test_fetch_product_line_skips_products_with_unavailable_details() -> None:
    catalog = fetch_product_line(DetailsErrorClient(), 79, with_skus=True)

    assert catalog["sets"][0]["detailErrorCount"] == 1
    assert catalog["products"][0]["name"] == "Overwhelming Barrage"
    assert "skus" not in catalog["products"][0]


def test_fetch_product_line_writes_and_reuses_product_detail_cache(tmp_path) -> None:
    detail_cache_dir = tmp_path / "product-details"
    first_client = DetailsClient()

    first_catalog = fetch_product_line(first_client, 79, with_skus=True, detail_cache_dir=detail_cache_dir)
    second_catalog = fetch_product_line(CachedDetailsOnlyClient(), 79, with_skus=True, detail_cache_dir=detail_cache_dir)

    assert (detail_cache_dir / "540" / "213" / "540213.json").exists()
    assert first_client.detail_requests == 1
    assert first_catalog["sets"][0]["detailFetchCount"] == 1
    assert second_catalog["sets"][0]["detailCacheHitCount"] == 1
    assert second_catalog["products"][0]["skus"][0]["tcgplayerSkuId"] == 99


def test_build_release_writes_metrics_file(tmp_path) -> None:
    cached = {
        "meta": {
            "object": "tcgjson_catalog",
            "generatedAt": "2026-06-01T00:00:00Z",
            "productLine": "Pokemon",
            "slug": "pokemon",
        },
        "sets": [{"tcgplayerSetId": 10, "name": "Cached Set", "productCount": 1}],
        "products": [
            {
                "tcgplayerProductId": 100,
                "name": "Cached Card",
                "set": {"id": 10, "name": "Cached Set"},
                "collectorNumber": "001",
                "rarity": "Common",
                "foilings": ["Normal"],
                "imageUrls": [],
                "priceGuide": [],
            }
        ],
    }
    (tmp_path / "pokemon.full.json").write_text(json.dumps(cached), encoding="utf-8")

    manifest = build_release(
        tmp_path / "release",
        [3],
        cache_dir=tmp_path,
        client=CachedSetClient(),
    )
    metrics = json.loads((tmp_path / "release" / "metrics.json").read_text(encoding="utf-8"))

    assert "build_metrics" in {item["type"] for item in manifest["data"]}
    assert metrics["mode"] == "incremental"
    assert metrics["productLines"][0]["cache"]["reusedSetCount"] == 1


def test_assemble_release_combines_per_line_outputs_and_metrics(tmp_path) -> None:
    output_dir = tmp_path / "release"
    metrics_dir = output_dir / ".metrics"
    metrics_dir.mkdir(parents=True)
    catalog = {
        "meta": {
            "object": "tcgjson_catalog",
            "generatedAt": "2026-06-01T00:00:00Z",
            "productLine": "Pokemon",
            "slug": "pokemon",
            "setCount": 1,
            "productCount": 1,
        },
        "sets": [{"tcgplayerSetId": 10, "name": "Set", "productCount": 1}],
        "products": [
            {
                "tcgplayerProductId": 100,
                "name": "Card",
                "set": {"id": 10, "name": "Set"},
                "imageUrls": [],
                "priceGuide": [],
            }
        ],
    }
    write_product_line_files(output_dir, catalog)
    (metrics_dir / "pokemon.json").write_text(
        json.dumps(
            {
                "object": "tcgjson_build_metrics",
                "startedAt": "2026-06-01T00:00:00Z",
                "finishedAt": "2026-06-01T00:00:05Z",
                "durationSeconds": 5,
                "mode": "incremental",
                "withSkus": False,
                "cacheDir": "release-cache",
                "checkpointDir": "",
                "detailCacheDir": "",
                "refreshRecentSetCount": 3,
                "productLineCount": 1,
                "productLines": [
                    {
                        "productLine": "Pokemon",
                        "slug": "pokemon",
                        "durationSeconds": 5,
                        "setCount": 1,
                        "productCount": 1,
                        "cache": {"reusedSetCount": 1},
                        "requests": {"requests": 2, "retries": 0, "errors": 0, "cacheHits": 0},
                    }
                ],
                "requests": {"requests": 2, "retries": 0, "errors": 0, "cacheHits": 0},
            }
        ),
        encoding="utf-8",
    )

    manifest = assemble_release(output_dir)
    metrics = json.loads((output_dir / "metrics.json").read_text(encoding="utf-8"))

    assert "bulk-data.json" not in [item["download_uri"] for item in manifest["data"]]
    assert {
        "pokemon_catalog",
        "pokemon_catalog_full",
        "pokemon_schema",
        "pokemon_schema_markdown",
        "pokemon_set_10_cache",
        "build_metrics",
    } == {
        item["type"] for item in manifest["data"]
    }
    assert metrics["productLineCount"] == 1
    assert metrics["requests"]["requests"] == 2
