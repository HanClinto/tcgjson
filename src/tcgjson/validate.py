"""Validate generated release files."""
from __future__ import annotations

import argparse
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
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("object") == "tcgjson_build_metrics":
            if "durationSeconds" not in payload or "productLines" not in payload:
                raise ValueError(f"{path} is missing required metrics keys")
        elif "meta" not in payload or "products" not in payload or "sets" not in payload:
            raise ValueError(f"{path} is missing required catalog keys")
        if path.stat().st_size != item["size"]:
            raise ValueError(f"size mismatch for {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise ValueError(f"sha256 mismatch for {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tcgjson.validate")
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args(argv)
    validate_release(args.output_dir)
    print(f"Validated {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
