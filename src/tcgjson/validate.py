"""Validate generated release files."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def validate_release(output_dir: Path) -> None:
    manifest_path = output_dir / "bulk-data.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("object") != "list" or not isinstance(manifest.get("data"), list):
        raise ValueError("bulk-data.json must be a list object with data[]")
    seen_types: set[str] = set()
    for item in manifest["data"]:
        file_type = item["type"]
        if file_type in seen_types:
            raise ValueError(f"duplicate bulk file type: {file_type}")
        seen_types.add(file_type)
        path = output_dir / item["download_uri"]
        if not path.exists():
            raise FileNotFoundError(path)
        if path.suffix == ".md":
            path.read_text(encoding="utf-8")
            if path.stat().st_size != item["size"]:
                raise ValueError(f"size mismatch for {path}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != item["sha256"]:
                raise ValueError(f"sha256 mismatch for {path}")
            continue
        payload = _load_json(path)
        if payload.get("object") == "tcgjson_build_metrics":
            if "durationSeconds" not in payload or "productLines" not in payload:
                raise ValueError(f"{path} is missing required metrics keys")
        elif payload.get("object") == "tcgjson_product_schema_profile":
            if "fields" not in payload or "productCount" not in payload:
                raise ValueError(f"{path} is missing required schema profile keys")
        elif "meta" not in payload or "products" not in payload or "sets" not in payload:
            raise ValueError(f"{path} is missing required catalog keys")
        elif "products" in payload:
            _validate_no_published_prices(path, payload)
        if path.stat().st_size != item["size"]:
            raise ValueError(f"size mismatch for {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise ValueError(f"sha256 mismatch for {path}")


def _validate_no_published_prices(path: Path, catalog: dict) -> None:
    forbidden_fields = {"priceGuide", "lowPrice", "marketPrice", "medianPrice"}
    for product in catalog.get("products", []):
        present = forbidden_fields & set(product)
        if present:
            product_id = product.get("productId", "")
            raise ValueError(f"{path} product {product_id} includes price field(s): {sorted(present)}")


def _load_json(path: Path) -> dict:
    if path.name.endswith(".json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tcgjson.validate")
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args(argv)
    validate_release(args.output_dir)
    print(f"Validated {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
