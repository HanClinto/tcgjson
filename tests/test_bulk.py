import json

from tcgjson.bulk import build_release, fetch_product_line, write_bulk_manifest, write_product_line_files
from tcgjson.tcgplayer import RequestStats


class CachedSetClient:
    requests = 0
    retries = 0
    errors = 0

    def stats(self):
        return RequestStats(self.requests, self.retries, self.errors)

    def get_product_lines(self):
        return [{"productLineId": 1, "productLineName": "Pokemon", "productLineUrlName": "pokemon"}]

    def get_set_names(self, product_line_id, *, active=True):
        assert product_line_id == 1
        return [{"setNameId": 10, "name": "Cached Set", "urlName": "cached-set"}]

    def get_priceguide_set_cards(self, set_id, *, rows=5000, product_type_id=1):
        raise AssertionError("cached set should not be refetched")


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
                "imageUrl": "",
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
                "imageUrl": "",
                "priceGuide": [],
            }
        ],
    }
    (tmp_path / "pokemon.full.json").write_text(json.dumps(cached), encoding="utf-8")

    catalog = fetch_product_line(CachedSetClient(), "Pokemon", cache_dir=tmp_path)

    assert catalog["meta"]["cache"]["reusedSetCount"] == 1
    assert catalog["meta"]["cache"]["fetchedSetCount"] == 0
    assert catalog["products"][0]["name"] == "Cached Card"


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
                "imageUrl": "",
                "priceGuide": [],
            }
        ],
    }
    (tmp_path / "pokemon.full.json").write_text(json.dumps(cached), encoding="utf-8")

    manifest = build_release(
        tmp_path / "release",
        ["Pokemon"],
        cache_dir=tmp_path,
        client=CachedSetClient(),
    )
    metrics = json.loads((tmp_path / "release" / "metrics.json").read_text(encoding="utf-8"))

    assert "build_metrics" in {item["type"] for item in manifest["data"]}
    assert metrics["mode"] == "incremental"
    assert metrics["productLines"][0]["cache"]["reusedSetCount"] == 1
