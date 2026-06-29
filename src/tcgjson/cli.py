"""Command-line interface for tcgjson."""
from __future__ import annotations

import argparse
from pathlib import Path

from .bulk import build_release
from .config import default_product_line_names


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tcgjson")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Build bulk JSON catalog files")
    build.add_argument("--output", type=Path, default=Path("release"))
    build.add_argument("--product-line", action="append", dest="product_lines")
    build.add_argument("--max-sets", type=int, default=None)
    build.add_argument("--priceguide-rows", type=int, default=5000)
    build.add_argument("--with-skus", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "build":
        manifest = build_release(
            args.output,
            args.product_lines or default_product_line_names(),
            max_sets=args.max_sets,
            priceguide_rows=args.priceguide_rows,
            with_skus=args.with_skus,
        )
        print(f"Wrote {len(manifest['data'])} bulk files to {args.output}")
        return 0
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
