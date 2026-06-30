"""SQLite cache for normalized TCGplayer search product rows."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_date(value: str) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class SearchProductCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._initialize()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SearchProductCache":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _initialize(self) -> None:
        self.connection.executescript(
            """
            PRAGMA journal_mode = DELETE;
            CREATE TABLE IF NOT EXISTS search_products (
                product_id INTEGER PRIMARY KEY,
                product_line_id INTEGER NOT NULL,
                product_line_name TEXT NOT NULL,
                set_id INTEGER,
                set_name TEXT,
                release_date TEXT,
                product_name TEXT,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_fetched_at TEXT NOT NULL,
                last_changed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_search_products_line_set
                ON search_products(product_line_id, set_id);
            CREATE INDEX IF NOT EXISTS idx_search_products_line_set_name
                ON search_products(product_line_id, set_name);
            CREATE INDEX IF NOT EXISTS idx_search_products_release_date
                ON search_products(product_line_id, release_date);
            CREATE TABLE IF NOT EXISTS product_skus (
                product_id INTEGER NOT NULL,
                sku_id INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (product_id, sku_id)
            );
            """
        )
        self.connection.commit()

    def upsert_search_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        product_line_id: int,
        product_line_name: str,
        fetched_at: str | None = None,
    ) -> int:
        fetched_at = fetched_at or _utc_now_iso()
        changed = 0
        with self.connection:
            for row in rows:
                product_id = int(row.get("productId") or 0)
                if product_id <= 0:
                    continue
                custom_attributes = row.get("customAttributes") if isinstance(row.get("customAttributes"), dict) else {}
                set_id = int(row.get("setId") or 0) or None
                release_date = str(custom_attributes.get("releaseDate") or row.get("releaseDate") or "")
                payload_json = _json_dumps(row)
                payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
                existing = self.connection.execute(
                    "SELECT payload_hash, first_seen_at, last_changed_at FROM search_products WHERE product_id = ?",
                    (product_id,),
                ).fetchone()
                first_seen_at = existing["first_seen_at"] if existing else fetched_at
                last_changed_at = existing["last_changed_at"] if existing else fetched_at
                if existing is None or existing["payload_hash"] != payload_hash:
                    last_changed_at = fetched_at
                    changed += 1
                self.connection.execute(
                    """
                    INSERT INTO search_products (
                        product_id, product_line_id, product_line_name, set_id, set_name,
                        release_date, product_name, payload_json, payload_hash,
                        first_seen_at, last_fetched_at, last_changed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(product_id) DO UPDATE SET
                        product_line_id = excluded.product_line_id,
                        product_line_name = excluded.product_line_name,
                        set_id = excluded.set_id,
                        set_name = excluded.set_name,
                        release_date = excluded.release_date,
                        product_name = excluded.product_name,
                        payload_json = excluded.payload_json,
                        payload_hash = excluded.payload_hash,
                        last_fetched_at = excluded.last_fetched_at,
                        last_changed_at = excluded.last_changed_at
                    """,
                    (
                        product_id,
                        product_line_id,
                        product_line_name,
                        set_id,
                        row.get("setName") or "",
                        release_date,
                        row.get("productName") or "",
                        payload_json,
                        payload_hash,
                        first_seen_at,
                        fetched_at,
                        last_changed_at,
                    ),
                )
        return changed

    def get_set_rows(
        self,
        *,
        product_line_id: int,
        set_id: int,
        set_name: str,
        refresh_recent_after: dt.date | None = None,
    ) -> list[dict[str, Any]] | None:
        cached_rows = self.connection.execute(
            """
            SELECT payload_json, release_date
            FROM search_products
            WHERE product_line_id = ? AND (set_id = ? OR set_name = ?)
            ORDER BY product_id
            """,
            (product_line_id, set_id, set_name),
        ).fetchall()
        if not cached_rows:
            return None
        if refresh_recent_after is not None:
            for row in cached_rows:
                release_date = _parse_date(row["release_date"] or "")
                if release_date is None or release_date >= refresh_recent_after:
                    return None
        return [json.loads(row["payload_json"]) for row in cached_rows]

    def count_products(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM search_products").fetchone()[0])