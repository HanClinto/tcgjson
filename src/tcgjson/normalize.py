"""Normalize TCGplayer price-guide and details payloads into tcgjson files."""
from __future__ import annotations

from typing import Any

from .tcgplayer import TCGplayerClient


def _image_urls(product_id: int, image_count: int = 1) -> list[str]:
    return TCGplayerClient.product_image_urls(product_id, image_count)


def _base_condition(condition: str, printing: str) -> str:
    condition = condition.strip()
    printing = printing.strip()
    if printing and condition.lower().endswith(f" {printing}".lower()):
        return condition[: -len(printing)].strip()
    return condition


def _sku_lookup(skus: list[dict[str, Any]]) -> dict[tuple[str, str], list[int]]:
    lookup: dict[tuple[str, str], list[int]] = {}
    for sku in skus:
        key = (sku.get("condition", "").casefold(), sku.get("printing", "").casefold())
        lookup.setdefault(key, []).append(sku["tcgplayerSkuId"])
    return lookup


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _compact_mapping(mapping: Any) -> dict[str, Any]:
    if not isinstance(mapping, dict):
        return {}
    return {key: value for key, value in mapping.items() if value not in (None, "", [], {})}


def extract_metadata(details_payload: dict[str, Any]) -> dict[str, Any]:
    custom_attributes = _compact_mapping(details_payload.get("customAttributes"))
    formatted_attributes = _compact_mapping(details_payload.get("formattedAttributes"))
    metadata: dict[str, Any] = {}

    promoted_fields = {
        "description": "rulesText",
        "flavorText": "flavorText",
        "fullType": "typeLine",
        "convertedCost": "convertedCost",
        "power": "power",
        "powerNumber": "powerNumber",
        "toughness": "toughness",
        "toughnessNumber": "toughnessNumber",
        "color": "colors",
        "cardType": "cardTypes",
        "formats": "formats",
    }
    for source_key, target_key in promoted_fields.items():
        value = custom_attributes.get(source_key)
        if value not in (None, "", [], {}):
            metadata[target_key] = value

    artist = formatted_attributes.get("Artist")
    if artist:
        metadata["artist"] = artist
    if custom_attributes:
        metadata["customAttributes"] = custom_attributes
    if formatted_attributes:
        metadata["formattedAttributes"] = formatted_attributes
    return metadata


def apply_search_product_metadata(product: dict[str, Any], search_row: dict[str, Any]) -> None:
    metadata = extract_metadata({"customAttributes": search_row.get("customAttributes")})
    if metadata:
        product["metadata"] = metadata


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
                "productLineId": product_line_id,
                "setId": set_id,
                "collectorNumber": _text(row.get("number")),
                "rarity": _text(row.get("rarity")),
                "imageUrls": _image_urls(product_id),
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
            }
        )

    products = list(grouped.values())
    for product in products:
        product["foilings"].sort()
        product["priceGuide"].sort(key=lambda item: (item["printing"], item["condition"]))
    products.sort(key=lambda item: (item["setId"], item["collectorNumber"], item["name"]))
    return products


def normalize_search_products(
    rows: list[dict[str, Any]],
    *,
    product_line_name: str,
    product_line_id: int,
    product_line_url_name: str,
    set_row: dict[str, Any],
) -> list[dict[str, Any]]:
    products = []
    set_id = int(set_row["setNameId"])
    for row in rows:
        product_id = int(row["productId"])
        custom_attributes = row.get("customAttributes") or {}
        listing_printings = {
            listing.get("printing", "") for listing in row.get("listings", []) if listing.get("printing")
        }
        foilings = sorted(listing_printings)
        if not foilings and row.get("foilOnly"):
            foilings = ["Foil"]
        products.append(
            product := {
                "tcgplayerProductId": product_id,
                "name": row.get("productName", ""),
                "productLineId": product_line_id,
                "setId": set_id,
                "collectorNumber": _text(custom_attributes.get("number")),
                "rarity": _text(row.get("rarityName", custom_attributes.get("rarityDbName"))),
                "imageUrls": _image_urls(product_id),
                "foilings": foilings,
                "priceGuide": [
                    {
                        "condition": "",
                        "printing": "",
                        "lowPrice": row.get("lowestPrice"),
                        "marketPrice": row.get("marketPrice"),
                        "medianPrice": row.get("medianPrice"),
                    }
                ],
            }
        )
        apply_search_product_metadata(product, row)
    products.sort(key=lambda item: (item["setId"], item["collectorNumber"], item["name"]))
    return products


def apply_product_details(product: dict[str, Any], details_payload: dict[str, Any]) -> None:
    image_count = int(details_payload.get("imageCount") or 1)
    product["imageUrls"] = _image_urls(product["tcgplayerProductId"], image_count)
    product["skus"] = extract_skus(details_payload)
    metadata = extract_metadata(details_payload)
    if metadata:
        product["metadata"] = metadata
    sku_lookup = _sku_lookup(product["skus"])
    for price_row in product.get("priceGuide", []):
        condition = _base_condition(price_row.get("condition", ""), price_row.get("printing", ""))
        printing = price_row.get("printing", "")
        sku_ids = sku_lookup.get((condition.casefold(), printing.casefold()))
        if sku_ids:
            price_row["tcgplayerSkuIds"] = sorted(sku_ids)


def compact_product(product: dict[str, Any]) -> dict[str, Any]:
    old_product_line = product.get("productLine") or {}
    old_set = product.get("set") or {}
    return {
        "tcgplayerProductId": product["tcgplayerProductId"],
        "name": product["name"],
        "productLineId": product.get("productLineId", old_product_line.get("id", 0)),
        "setId": product.get("setId", old_set.get("id", 0)),
        "collectorNumber": product.get("collectorNumber", ""),
        "rarity": product.get("rarity", ""),
        "foilings": product.get("foilings", []),
        "imageUrls": product.get("imageUrls") or ([product["imageUrl"]] if product.get("imageUrl") else []),
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
        sku_id = row.get("sku") or row.get("skuId") or row.get("skuID") or row.get("id")
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
