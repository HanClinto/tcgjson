import json

from tcgjson.bulk import write_bulk_manifest, write_product_line_files


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
