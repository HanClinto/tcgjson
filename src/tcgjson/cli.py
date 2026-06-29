"""Command-line interface for tcgjson."""
from __future__ import annotations

import argparse
from pathlib import Path

from .bulk import build_release
from .games import discover_game_support, write_game_support_report
from .tcgplayer import TCGplayerClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tcgjson")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Build bulk JSON catalog files")
    build.add_argument("--output", type=Path, default=Path("release"))
    build.add_argument("--product-line", action="append", dest="product_lines")
    build.add_argument("--max-sets", type=int, default=None)
    build.add_argument("--priceguide-rows", type=int, default=5000)
    build.add_argument("--with-skus", action="store_true")
    build.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Directory containing prior <slug>.full.json files to reuse as a baseline.",
    )
    build.add_argument(
        "--refresh-recent-sets",
        type=int,
        default=0,
        help="When using --cache-dir, refetch this many most-recent sets per product line.",
    )

    games = subparsers.add_parser("games", help="Report TCGplayer product-line support")
    games.add_argument("--output", type=Path, default=Path("games.md"))
    games.add_argument("--json-output", type=Path, default=Path("games.json"))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    client = TCGplayerClient()
    if args.command == "build":
        manifest = build_release(
            args.output,
            args.product_lines,
            max_sets=args.max_sets,
            priceguide_rows=args.priceguide_rows,
            with_skus=args.with_skus,
            cache_dir=args.cache_dir,
            refresh_recent_sets=args.refresh_recent_sets,
            client=client,
        )
        print(f"Wrote {len(manifest['data'])} bulk files to {args.output}")
        return 0
    if args.command == "games":
        report = discover_game_support(client)
        write_game_support_report(report, args.output, json_output=args.json_output)
        enabled = sum(1 for row in report["games"] if row["enabled"])
        print(f"Wrote {args.output} with {enabled} enabled product lines")
        return 0
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
