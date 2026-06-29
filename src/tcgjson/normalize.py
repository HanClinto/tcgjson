"""Normalize TCGplayer price-guide and details payloads into tcgjson files."""
from __future__ import annotations

from typing import Any

from .tcgplayer import TCGplayerClient


def group_priceguide_products(
    rows: list[dict[str, Any]],
    *,
    product_line_name: str,
    product_line_id: int,
    product_line_url_name: str,
    set_row: dict[str, Any],
) -> list[dict[str, Any]]:
    set_id = int(set_row["setNameId"])
    grouped: dict[int, dict[str, Any]] = {}
    for row in rows:
        product_id = int(row["productID"])
        product = grouped.setdefault(
            product_id,
            {
                "tcgplayerProductId": product_id,
                "name": row.get("productName", ""),
                "productLine": {
                    "id": product_line_id,
                    "name": product_line_name,
                    "urlName": product_line_url_name,
                },
                "set": {
                    "id": set_id,
                    "name": set_row.get("name", ""),
                    "urlName": set_row.get("urlName", ""),
                    "abbreviation": set_row.get("abbreviation", ""),
                    "releaseDate": set_row.get("releaseDate", ""),
                },
                "collectorNumber": row.get("number", ""),
                "rarity": row.get("rarity", ""),
                "imageUrl": TCGplayerClient.product_image_url(product_id),
                "foilings": [],
                "priceGuide": [],
            },
        )
        printing = row.get("printing", "")
        if printing and printing not in product["foilings"]:
            product["foilings"].append(printing)
        product["priceGuide"].append(
            {
                "condition": row.get("condition", ""),
                "printing": printing,
                "lowPrice": row.get("lowPrice"),
                "marketPrice": row.get("marketPrice"),
                "sales": row.get("sales"),
                "tcgplayerProductConditionId": row.get("productConditionID"),
            }
        )

    products = list(grouped.values())
    for product in products:
        product["foilings"].sort()
        product["priceGuide"].sort(key=lambda item: (item["printing"], item["condition"]))
    products.sort(key=lambda item: (item["set"]["name"], item["collectorNumber"], item["name"]))
    return products


def compact_product(product: dict[str, Any]) -> dict[str, Any]:
    return {
        "tcgplayerProductId": product["tcgplayerProductId"],
        "name": product["name"],
        "setId": product["set"]["id"],
        "setName": product["set"]["name"],
        "collectorNumber": product.get("collectorNumber", ""),
        "rarity": product.get("rarity", ""),
        "foilings": product.get("foilings", []),
        "imageUrl": product.get("imageUrl", ""),
    }


def extract_skus(details_payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidate_lists = [
        details_payload.get("skus"),
        details_payload.get("product", {}).get("skus") if isinstance(details_payload.get("product"), dict) else None,
        details_payload.get("results", {}).get("skus") if isinstance(details_payload.get("results"), dict) else None,
    ]
    rows = next((value for value in candidate_lists if isinstance(value, list)), [])
    skus = []
    for row in rows:
        sku_id = row.get("skuId") or row.get("skuID") or row.get("id")
        if sku_id is None:
            continue
        skus.append(
            {
                "tcgplayerSkuId": int(sku_id),
                "condition": row.get("condition", row.get("conditionName", "")),
                "printing": row.get("printing", row.get("printingName", row.get("variant", ""))),
                "language": row.get("language", row.get("languageName", "")),
            }
        )
    skus.sort(key=lambda item: (item["condition"], item["printing"], item["language"], item["tcgplayerSkuId"]))
    return skus
