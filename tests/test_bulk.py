import gzip
import json

import pytest
import requests

from tcgjson.bulk import (
    _recent_set_ids,
    _write_set_checkpoint,
    assemble_release,
    build_release,
    fetch_product_line,
    write_bulk_manifest,
    write_product_line_files,
    write_product_schema_files,
)
from tcgjson.cli import build_parser
from tcgjson.tcgplayer import RequestStats, TCGplayerError
from tcgjson.validate import validate_release


def load_json(path):
    if path.name.endswith(".json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


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


class SearchFallbackClient(CachedSetClient):
    def get_product_lines(self):
        return [
            {"productLineId": 79, "productLineName": "Star Wars: Unlimited", "productLineUrlName": "star-wars-unlimited"}
        ]

    def get_set_names(self, product_line_id, *, active=True):
        assert product_line_id == 79
        return [{"setNameId": 23405, "name": "Spark of Rebellion", "urlName": "spark-of-rebellion"}]

    def iter_search_products(self, *, product_line_name, set_id, set_name=None, page_size=50):
        assert product_line_name == "Star Wars: Unlimited"
        assert set_id == 23405
        assert set_name is None
        yield {
            "productId": 999999,
            "productName": "Wrong Set Card",
            "productLineId": 79,
            "productLineName": "Star Wars: Unlimited",
            "productLineUrlName": "Star Wars Unlimited",
            "setId": 99999,
            "setName": "Wrong Set",
            "setUrlName": "Wrong Set",
            "setCode": "BAD",
            "rarityName": "Common",
            "customAttributes": {},
        }
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
            "customAttributes": {"number": "092/252", "releaseDate": "2024-03-08T00:00:00Z"},
        }


class CheckpointOnlyClient(SearchFallbackClient):
    def iter_search_products(self, *, product_line_name, set_id, set_name=None, page_size=50):
        raise AssertionError("set checkpoint should be reused before fetching search rows")


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
            "sourceMode": "search",
            "generatedAt": "2026-06-29T00:00:00Z",
            "productLine": "Pokemon",
            "slug": "pokemon",
            "setCount": 1,
            "productCount": 1,
        },
        "sets": [{"setId": 1, "name": "Set", "productCount": 1}],
        "products": [
            {
                "productId": 10,
                "name": "Card",
                "productLineId": 3,
                "setId": 1,
                "collectorNumber": "1",
                "rarity": "Common",
                "foilings": [],
                "imageUrls": [],
                "priceGuide": [{"condition": "Near Mint", "marketPrice": 1.0}],
            }
        ],
    }
    files = write_product_line_files(tmp_path, catalog)
    manifest = write_bulk_manifest(tmp_path, files)
    full_catalog = load_json(tmp_path / "pokemon.full.json.gz")

    assert [item["type"] for item in manifest["data"]] == [
        "pokemon_catalog",
        "pokemon_catalog_full",
    ]
    assert "source" not in full_catalog["meta"]
    assert "sourceMode" not in full_catalog["meta"]
    assert "priceGuide" not in full_catalog["products"][0]
    assert "productLineId" not in full_catalog["products"][0]
    assert list(full_catalog["products"][0])[:2] == ["productId", "name"]
    assert {item["download_uri"] for item in manifest["data"]} == {"pokemon.json.gz", "pokemon.full.json.gz"}
    assert all(item["content_encoding"] == "gzip" for item in manifest["data"])
    assert all(item["content_type"] == "application/json" for item in manifest["data"])
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
                "productId": 10,
                "name": "Card",
                "productLineId": 3,
                "setId": 1,
                "metadata": {"rulesText": "Draw a card.", "colors": ["Blue"]},
            }
        ],
    }

    files = write_product_schema_files(tmp_path, catalog)
    profile = load_json(tmp_path / "pokemon.schema.json.gz")

    assert {item["type"] for item in files} == {"pokemon_schema"}
    assert any(field["path"] == "metadata.rulesText" for field in profile["fields"])


def test_write_product_schema_files_omits_price_fields(tmp_path) -> None:
    catalog = {
        "meta": {"productLine": "Pokemon", "slug": "pokemon"},
        "products": [
            {
                "productId": 10,
                "name": "Card",
                "productLineId": 3,
                "setId": 1,
                "priceGuide": [{"marketPrice": 1.23}],
                "marketPrice": 1.23,
            }
        ],
    }

    write_product_schema_files(tmp_path, catalog)

    profile = load_json(tmp_path / "pokemon.schema.json.gz")
    field_paths = {field["path"] for field in profile["fields"]}
    assert "priceGuide" not in field_paths
    assert "marketPrice" not in field_paths
    assert "productLineId" not in field_paths


def test_fetch_product_line_reuses_cached_full_catalog(tmp_path) -> None:
    cached = {
        "meta": {
            "object": "tcgjson_catalog",
            "generatedAt": "2026-06-01T00:00:00Z",
            "productLine": "Pokemon",
            "slug": "pokemon",
            "cache": {"catalogVersion": 2, "productSearchFilter": "setId"},
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
                "priceGuide": [{"condition": "Near Mint", "marketPrice": 1.23}],
            }
        ],
    }
    (tmp_path / "pokemon.full.json").write_text(json.dumps(cached), encoding="utf-8")

    catalog = fetch_product_line(CachedSetClient(), 3, cache_dir=tmp_path)

    assert catalog["meta"]["cache"]["reusedSetCount"] == 1
    assert catalog["sets"][0]["iconUrl"] == "https://tcgplayer-cdn.tcgplayer.com/set_icon/10CachedSet.png"
    assert catalog["sets"][0]["setId"] == 10
    assert "tcgplayerSetId" not in catalog["sets"][0]
    assert "priceGuideRowCount" not in catalog["sets"][0]
    assert catalog["meta"]["cache"]["fetchedSetCount"] == 0
    assert catalog["products"][0]["productId"] == 100
    assert catalog["products"][0]["name"] == "Cached Card"
    assert list(catalog["products"][0])[:2] == ["productId", "name"]
    assert catalog["products"][0]["imageUrls"] == ["https://tcgplayer-cdn.tcgplayer.com/product/100_in_1000x1000.jpg"]
    assert "imageUrl" not in catalog["products"][0]
    assert "priceGuide" not in catalog["products"][0]


def test_fetch_product_line_emits_plain_progress_logs(tmp_path, capsys) -> None:
    cached = {
        "meta": {
            "object": "tcgjson_catalog",
            "generatedAt": "2026-06-01T00:00:00Z",
            "productLine": "Pokemon",
            "slug": "pokemon",
            "cache": {"catalogVersion": 2, "productSearchFilter": "setId"},
        },
        "sets": [{"setId": 10, "name": "Cached Set", "productCount": 1}],
        "products": [
            {
                "productId": 100,
                "name": "Cached Card",
                "productLineId": 3,
                "setId": 10,
                "imageUrls": [],
            }
        ],
    }
    (tmp_path / "pokemon.full.json").write_text(json.dumps(cached), encoding="utf-8")

    fetch_product_line(CachedSetClient(), 3, cache_dir=tmp_path, log_progress=True)

    output = capsys.readouterr().out
    assert "pokemon: starting 1 set(s)" in output
    assert "pokemon: set 1/1 10 'Cached Set' reused 1 product(s)" in output
    assert "pokemon: finished 1 set(s), 1 product(s)" in output


def test_fetch_product_line_uses_search_as_product_source() -> None:
    catalog = fetch_product_line(SearchFallbackClient(), 79)

    assert catalog["meta"]["version"] == 3
    assert "productLineId" not in catalog["meta"]
    assert catalog["sets"][0]["setId"] == 23405
    assert catalog["sets"][0]["productCount"] == 1
    assert catalog["products"][0]["name"] == "Overwhelming Barrage"
    assert "productLineId" not in catalog["products"][0]
    assert catalog["products"][0]["collectorNumber"] == "092/252"
    assert "priceGuide" not in catalog["products"][0]
    assert "marketPrice" not in catalog["products"][0]
    assert catalog["products"][0]["metadata"]["customAttributes"]["releaseDate"] == "2024-03-08T00:00:00Z"


def test_fetch_product_line_ignores_cache_without_set_id_search_marker(tmp_path) -> None:
    cached = {
        "meta": {
            "object": "tcgjson_catalog",
            "generatedAt": "2026-06-01T00:00:00Z",
            "productLine": "Star Wars: Unlimited",
            "slug": "star-wars-unlimited",
        },
        "sets": [{"setId": 23405, "name": "Spark of Rebellion", "productCount": 1}],
        "products": [
            {
                "productId": 1,
                "name": "Polluted Cache Card",
                "setId": 23405,
                "imageUrls": [],
            }
        ],
    }
    (tmp_path / "star-wars-unlimited.full.json").write_text(json.dumps(cached), encoding="utf-8")

    catalog = fetch_product_line(SearchFallbackClient(), 79, cache_dir=tmp_path)

    assert catalog["meta"]["cache"]["reusedSetCount"] == 0
    assert catalog["meta"]["cache"]["fetchedSetCount"] == 1
    assert catalog["meta"]["cache"]["catalogVersion"] == 2
    assert catalog["meta"]["cache"]["productSearchFilter"] == "setId"
    assert catalog["products"][0]["name"] == "Overwhelming Barrage"


def test_recent_set_ids_always_include_future_sets() -> None:
    rows = [
        {"setNameId": 1, "releaseDate": "2024-01-01T00:00:00"},
        {"setNameId": 2, "releaseDate": "2024-02-01T00:00:00"},
        {"setNameId": 3, "releaseDate": "2099-01-01T00:00:00"},
    ]

    assert _recent_set_ids(rows, 1) == {2, 3}
    assert _recent_set_ids(rows, 0) == {3}


def test_fetch_product_line_writes_and_reuses_set_checkpoints(tmp_path) -> None:
    checkpoint_dir = tmp_path / "set-checkpoints"
    first_catalog = fetch_product_line(SearchFallbackClient(), 79, checkpoint_dir=checkpoint_dir)

    assert (checkpoint_dir / "star-wars-unlimited" / "23405.json").exists()
    assert first_catalog["meta"]["cache"]["fetchedSetCount"] == 1

    second_catalog = fetch_product_line(CheckpointOnlyClient(), 79, checkpoint_dir=checkpoint_dir)

    assert second_catalog["meta"]["cache"]["reusedSetCheckpointCount"] == 1
    assert second_catalog["meta"]["cache"]["fetchedSetCount"] == 0
    assert second_catalog["products"][0]["name"] == "Overwhelming Barrage"
    assert "imageUrl" not in second_catalog["products"][0]


@pytest.mark.parametrize(
    ("old_source", "new_source"),
    [("release cache", "fetch"), ("release cache", "checkpoint"), ("checkpoint", "fetch")],
)
@pytest.mark.parametrize("reverse_sets", [False, True])
@pytest.mark.parametrize("empty_old_set", [False, True])
def test_fetch_product_line_reconciles_moved_products(
    tmp_path, capsys, old_source, new_source, reverse_sets, empty_old_set,
) -> None:
    old_products = [{"productId": 683198, "name": "Old name", "setId": 10}]
    if not empty_old_set:
        old_products.append({"productId": 100, "name": "Unchanged card", "setId": 10})
    old_set = {"setId": 10, "name": "Old Set", "productCount": len(old_products)}
    new_set = {"setId": 20, "name": "New Set", "productCount": 1}
    checkpoint_dir = tmp_path / "checkpoints"
    if old_source == "release cache":
        cached = {
            "meta": {"cache": {"catalogVersion": 2, "productSearchFilter": "setId"}},
            "sets": [old_set],
            "products": old_products,
        }
        (tmp_path / "pokemon.full.json").write_text(json.dumps(cached), encoding="utf-8")
    else:
        _write_set_checkpoint(
            checkpoint_dir, slug="pokemon", product_line_id=3,
            set_summary=old_set, products=old_products, with_skus=False,
        )
    if new_source == "checkpoint":
        _write_set_checkpoint(
            checkpoint_dir, slug="pokemon", product_line_id=3,
            set_summary=new_set,
            products=[{"productId": 683198, "name": "Current name", "setId": 20}],
            with_skus=False,
        )

    class MovedProductClient(CachedSetClient):
        search_calls = 0

        def get_set_names(self, product_line_id, *, active=True):
            rows = [
                {"setNameId": 10, "name": "Old Set"},
                {"setNameId": 20, "name": "New Set"},
            ]
            return rows[::-1] if reverse_sets else rows

        def iter_search_products(self, *, product_line_name, set_id):
            assert new_source == "fetch"
            assert set_id == 20
            self.search_calls += 1
            yield {"productId": 683198, "productName": "Current name", "setId": 20}

    client = MovedProductClient()
    catalog = fetch_product_line(
        client, 3, cache_dir=tmp_path, checkpoint_dir=checkpoint_dir, log_progress=True,
    )
    expected_count = 1 if empty_old_set else 2
    assert catalog["meta"]["productCount"] == expected_count
    assert len(catalog["products"]) == expected_count
    moved = [product for product in catalog["products"] if product["productId"] == 683198]
    assert len(moved) == 1
    assert moved[0]["setId"] == 20
    assert moved[0]["name"] == "Current name"
    assert {row["setId"]: row["productCount"] for row in catalog["sets"]} == {
        10: 0 if empty_old_set else 1, 20: 1,
    }
    if not empty_old_set:
        assert next(p for p in catalog["products"] if p["productId"] == 100)["name"] == "Unchanged card"
    assert client.search_calls == (1 if new_source == "fetch" else 0)
    assert "reconciled productId 683198: replaced set 10" in capsys.readouterr().out

    output_dir = tmp_path / "release"
    files = write_product_line_files(output_dir, catalog)
    files.extend(write_product_schema_files(output_dir, catalog))
    write_bulk_manifest(output_dir, files)
    validate_release(output_dir)
    for filename in ["pokemon.json.gz", "pokemon.full.json.gz"]:
        published = load_json(output_dir / filename)
        assert len(published["products"]) == expected_count
        assert published["meta"]["productCount"] == expected_count
    assert load_json(output_dir / "pokemon.schema.json.gz")["productCount"] == expected_count

    next_catalog = fetch_product_line(client, 3, cache_dir=output_dir)
    assert next_catalog["products"] == catalog["products"]
    assert next_catalog["meta"]["cache"]["reusedSetCount"] == 2
    assert client.search_calls == (1 if new_source == "fetch" else 0)


@pytest.mark.parametrize("source", ["release cache", "checkpoint", "fetch"])
def test_fetch_product_line_rejects_ambiguous_duplicate_products(tmp_path, source) -> None:
    sets = [
        {"setId": set_id, "name": f"Set {set_id}", "productCount": 1}
        for set_id in (10, 20)
    ]
    products = [
        {"productId": 683198, "name": "Conflicting card", "setId": set_id}
        for set_id in (10, 20)
    ]
    checkpoint_dir = tmp_path / "checkpoints"
    if source == "release cache":
        cached = {
            "meta": {"cache": {"catalogVersion": 2, "productSearchFilter": "setId"}},
            "sets": sets,
            "products": products,
        }
        (tmp_path / "pokemon.full.json").write_text(json.dumps(cached), encoding="utf-8")
    elif source == "checkpoint":
        for set_summary, product in zip(sets, products):
            _write_set_checkpoint(
                checkpoint_dir, slug="pokemon", product_line_id=3,
                set_summary=set_summary, products=[product], with_skus=False,
            )

    class ConflictingProductClient(CachedSetClient):
        def get_set_names(self, product_line_id, *, active=True):
            return [{"setNameId": s["setId"], "name": s["name"]} for s in sets]

        def iter_search_products(self, *, product_line_name, set_id):
            assert source == "fetch"
            yield {"productId": 683198, "productName": "Conflicting card", "setId": set_id}

    with pytest.raises(
        TCGplayerError, match=f"duplicate productId 683198 in sets 10 and 20 from {source}",
    ):
        fetch_product_line(
            ConflictingProductClient(), 3, cache_dir=tmp_path, checkpoint_dir=checkpoint_dir,
        )


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
    assert second_catalog["products"][0]["skus"][0]["sku"] == 99


def test_build_release_writes_metrics_file(tmp_path) -> None:
    cached = {
        "meta": {
            "object": "tcgjson_catalog",
            "generatedAt": "2026-06-01T00:00:00Z",
            "productLine": "Pokemon",
            "slug": "pokemon",
            "cache": {"catalogVersion": 2, "productSearchFilter": "setId"},
        },
        "sets": [{"setId": 10, "name": "Cached Set", "productCount": 1}],
        "products": [
            {
                "productId": 100,
                "name": "Cached Card",
                "set": {"id": 10, "name": "Cached Set"},
                "collectorNumber": "001",
                "rarity": "Common",
                "foilings": ["Normal"],
                "imageUrls": [],
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
    metrics = load_json(tmp_path / "release" / "metrics.json")

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
        "sets": [{"setId": 10, "name": "Set", "productCount": 1}],
        "products": [
            {
                "productId": 100,
                "name": "Card",
                "set": {"id": 10, "name": "Set"},
                "imageUrls": [],
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
    metrics = load_json(output_dir / "metrics.json")

    assert "bulk-data.json" not in [item["download_uri"] for item in manifest["data"]]
    assert {
        "pokemon_catalog",
        "pokemon_catalog_full",
        "pokemon_schema",
        "build_metrics",
    } == {
        item["type"] for item in manifest["data"]
    }
    assert metrics["productLineCount"] == 1
    assert metrics["requests"]["requests"] == 2
