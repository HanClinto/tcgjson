import datetime as dt
import sqlite3

from tcgjson.search_cache import SearchProductCache


def test_search_product_cache_upserts_and_reuses_set_rows(tmp_path) -> None:
    row = {
        "productId": 540213,
        "productName": "Overwhelming Barrage",
        "setId": 23405,
        "setName": "Spark of Rebellion",
        "customAttributes": {"number": "092/252", "releaseDate": "2024-03-08T00:00:00Z"},
    }
    with SearchProductCache(tmp_path / "search-products.sqlite") as cache:
        assert cache.upsert_search_rows([row], product_line_id=79, product_line_name="Star Wars: Unlimited") == 1
        assert cache.upsert_search_rows([row], product_line_id=79, product_line_name="Star Wars: Unlimited") == 0
        cache.mark_set_complete(product_line_id=79, set_id=23405, set_name="Spark of Rebellion", row_count=1)
        assert cache.count_products() == 1

        rows = cache.get_set_rows(product_line_id=79, set_id=23405, set_name="Spark of Rebellion")

    assert rows == [row]


def test_search_product_cache_does_not_reuse_incomplete_set_rows(tmp_path) -> None:
    row = {
        "productId": 540213,
        "productName": "Overwhelming Barrage",
        "setId": 23405,
        "setName": "Spark of Rebellion",
        "customAttributes": {"number": "092/252", "releaseDate": "2024-03-08T00:00:00Z"},
    }
    with SearchProductCache(tmp_path / "search-products.sqlite") as cache:
        cache.upsert_search_rows([row], product_line_id=79, product_line_name="Star Wars: Unlimited")

        rows = cache.get_set_rows(product_line_id=79, set_id=23405, set_name="Spark of Rebellion")

    assert rows is None


def test_search_product_cache_treats_recent_rows_as_stale(tmp_path) -> None:
    row = {
        "productId": 1,
        "productName": "Future Spoiler",
        "setId": 2,
        "setName": "Old Promo Set",
        "customAttributes": {"releaseDate": "9999-01-01T00:00:00Z"},
    }
    with SearchProductCache(tmp_path / "search-products.sqlite") as cache:
        cache.upsert_search_rows([row], product_line_id=1, product_line_name="Magic")
        cache.mark_set_complete(product_line_id=1, set_id=2, set_name="Old Promo Set", row_count=1)

        assert cache.get_set_rows(
            product_line_id=1,
            set_id=2,
            set_name="Old Promo Set",
            refresh_recent_after=dt.date(2026, 1, 1),
        ) is None


def test_search_product_cache_creates_future_sku_mapping_table(tmp_path) -> None:
    path = tmp_path / "search-products.sqlite"
    with SearchProductCache(path):
        pass
    with sqlite3.connect(path) as connection:
        table_names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }

    assert "product_skus" in table_names