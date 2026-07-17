import pytest

from tcgjson.bulk import write_bulk_manifest, write_product_line_files
from tcgjson.validate import validate_release


def test_validate_release_rejects_duplicate_product_ids(tmp_path) -> None:
    catalog = {
        "meta": {"productLine": "Pokemon", "slug": "pokemon"},
        "sets": [{"setId": 1, "name": "Set", "productCount": 2}],
        "products": [
            {"productId": 10, "name": "Card", "setId": 1, "imageUrls": []},
            {"productId": 10, "name": "Card", "setId": 1, "imageUrls": []},
        ],
    }
    files = write_product_line_files(tmp_path, catalog)
    write_bulk_manifest(tmp_path, files)

    with pytest.raises(ValueError, match="duplicate productId"):
        validate_release(tmp_path)


def test_validate_release_rejects_set_count_mismatch(tmp_path) -> None:
    catalog = {
        "meta": {"productLine": "Pokemon", "slug": "pokemon"},
        "sets": [{"setId": 1, "name": "Set", "productCount": 2}],
        "products": [{"productId": 10, "name": "Card", "setId": 1, "imageUrls": []}],
    }
    files = write_product_line_files(tmp_path, catalog)
    write_bulk_manifest(tmp_path, files)

    with pytest.raises(ValueError, match="productCount 2 does not match 1 products"):
        validate_release(tmp_path)


def test_validate_release_rejects_unknown_product_set(tmp_path) -> None:
    catalog = {
        "meta": {"productLine": "Pokemon", "slug": "pokemon"},
        "sets": [{"setId": 1, "name": "Set", "productCount": 0}],
        "products": [{"productId": 10, "name": "Card", "setId": 2, "imageUrls": []}],
    }
    files = write_product_line_files(tmp_path, catalog)
    write_bulk_manifest(tmp_path, files)

    with pytest.raises(ValueError, match="references unknown setId"):
        validate_release(tmp_path)