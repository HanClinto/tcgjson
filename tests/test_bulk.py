import json

import requests

from tcgjson.cli import build_parser

from tcgjson.bulk import (
    build_release,
    fetch_product_line,
    write_bulk_manifest,
    write_product_line_files,
    write_product_schema_files,
)
from tcgjson.search_cache import SearchProductCache
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


class SearchCacheOnlyClient(PriceguideWithSearchMetadataClient):
    def iter_search_products(self, *, product_line_name, set_name=None, page_size=50, **kwargs):
        raise AssertionError("search metadata should be loaded from the SQLite cache")

    def search_products(self, **kwargs):
        raise AssertionError("recent search cache refresh should be disabled for this test")


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
                "set": {"id": 1, "name": "Set"},
                "collectorNumber": "1",
                "rarity": "Common",
                "foilings": [],
                "imageUrls": [],
                "priceGuide": [],
            }
        ],
    }
    files = write_product_line_files(tmp_path, catalog)
    manifest = write_bulk_manifest(tmp_path, files)

    assert [item["type"] for item in manifest["data"]] == ["pokemon_catalog", "pokemon_catalog_full"]
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
    assert parser.parse_args(["build", "--search-cache-dir", "search-cache"]).search_cache_dir.name == "search-cache"
    assert parser.parse_args(["build", "--search-cache-db", "search.sqlite"]).search_cache_db.name == "search.sqlite"
    assert parser.parse_args(["build", "--no-search-cache"]).no_search_cache is True


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


def test_fetch_product_line_reuses_sqlite_search_metadata_cache(tmp_path) -> None:
    with SearchProductCache(tmp_path / "search-products.sqlite") as search_cache:
        search_cache.upsert_search_rows(
            [
                {
                    "productId": 540213,
                    "productName": "Overwhelming Barrage",
                    "setId": 23405,
                    "setName": "Spark of Rebellion",
                    "rarityName": "Uncommon",
                    "customAttributes": {"number": "092/252", "releaseDate": "2024-03-08T00:00:00Z"},
                }
            ],
            product_line_id=79,
            product_line_name="Star Wars: Unlimited",
        )

        catalog = fetch_product_line(
            SearchCacheOnlyClient(),
            79,
            search_cache=search_cache,
            search_cache_refresh_recent_days=0,
        )

    assert catalog["sets"][0]["searchMetadataCacheHit"] is True
    assert catalog["meta"]["cache"]["searchMetadataCacheHitCount"] == 1
    assert catalog["products"][0]["metadata"]["customAttributes"]["releaseDate"] == "2024-03-08T00:00:00Z"


def test_fetch_product_line_writes_product_line_search_cache_db(tmp_path) -> None:
    search_cache_dir = tmp_path / "search-products"

    catalog = fetch_product_line(
        PriceguideWithSearchMetadataClient(),
        79,
        search_cache_dir=search_cache_dir,
        search_cache_refresh_recent_days=0,
    )

    assert (search_cache_dir / "star-wars-unlimited.sqlite").exists()
    assert catalog["meta"]["cache"]["searchCachePath"].endswith("star-wars-unlimited.sqlite")
    assert catalog["meta"]["cache"]["searchMetadataCacheWriteCount"] == 1


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
