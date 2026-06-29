"""Generate product schema/profile reports from built catalogs."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _is_populated(value: Any) -> bool:
    return value not in (None, "", [], {})


def _walk(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else key
            yield child_path, child
            yield from _walk(child, child_path)
    elif isinstance(value, list):
        for child in value:
            child_path = f"{prefix}[]"
            yield child_path, child
            yield from _walk(child, child_path)


def product_schema_profile(catalog: dict[str, Any]) -> dict[str, Any]:
    products = catalog.get("products") or []
    total = len(products)
    field_counts: Counter[str] = Counter()
    populated_counts: Counter[str] = Counter()
    type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, Any] = {}

    for product in products:
        seen_in_product: set[str] = set()
        populated_in_product: set[str] = set()
        for path, value in _walk(product):
            seen_in_product.add(path)
            type_counts[path][_value_type(value)] += 1
            if _is_populated(value):
                populated_in_product.add(path)
                examples.setdefault(path, value)
        field_counts.update(seen_in_product)
        populated_counts.update(populated_in_product)

    fields = []
    for path in sorted(field_counts):
        populated_count = populated_counts[path]
        fields.append(
            {
                "path": path,
                "types": sorted(type_counts[path]),
                "populatedCount": populated_count,
                "populatedPercent": round((populated_count / total) * 100, 2) if total else 0.0,
                "example": examples.get(path),
            }
        )

    meta = catalog.get("meta", {})
    return {
        "object": "tcgjson_product_schema_profile",
        "version": 1,
        "productLine": meta.get("productLine", ""),
        "slug": meta.get("slug", ""),
        "productCount": total,
        "fieldCount": len(fields),
        "fields": fields,
    }


def product_schema_markdown(profile: dict[str, Any]) -> str:
    lines = [
        f"# {profile['productLine']} Product Schema",
        "",
        f"Products profiled: {profile['productCount']}",
        f"Fields observed: {profile['fieldCount']}",
        "",
        "| Field | Types | Populated | Example |",
        "| --- | --- | ---: | --- |",
    ]
    total = int(profile.get("productCount") or 0)
    for field in profile.get("fields", []):
        populated = f"{field['populatedCount']}"
        if total:
            populated += f" ({field['populatedPercent']}%)"
        example = _markdown_example(field.get("example"))
        lines.append(
            f"| `{field['path']}` | {', '.join(field['types'])} | "
            f"{populated} | {example} |"
        )
    return "\n".join(lines) + "\n"


def _markdown_example(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = value[:3]
    text = str(value).replace("\n", " ").replace("|", "\\|")
    if len(text) > 80:
        text = text[:77] + "..."
    return f"`{text}`"