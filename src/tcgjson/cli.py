"""Command-line interface for tcgjson."""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from .bulk import assemble_release, build_release
from .docs import generate_catalog_docs
from .games import discover_game_support, write_game_support_report
from .operations import DEFAULT_CONSTRAINTS_PATH, data_cache_delta_megabytes, evaluate_operations, evaluation_text
from .tcgplayer import TCGplayerClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tcgjson")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Build bulk JSON catalog files")
    build.add_argument("--output", type=Path, default=Path("release"))
    build.add_argument(
        "--data-cache-dir",
        type=Path,
        default=Path("data-cache"),
        help="Directory for local generated cache files such as product details. Defaults to data-cache.",
    )
    build.add_argument("--product-line", action="append", dest="product_lines", help="TCGplayer product-line ID or name")
    build.add_argument("--max-sets", type=int, default=None)
    build.add_argument(
        "--with-details",
        "--with-skus",
        action="store_true",
        dest="with_details",
        help="Fetch per-product details for SKU IDs, card metadata, and multi-image URLs.",
    )
    build.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bars and plain progress logs during catalog builds.",
    )
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
    build.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=None,
        help="Directory for per-set checkpoint files. Defaults to .tcgjson-cache/set-checkpoints.",
    )
    build.add_argument(
        "--no-checkpoints",
        action="store_true",
        help="Disable per-set checkpoint writes and resume.",
    )
    build.add_argument(
        "--detail-cache-dir",
        type=Path,
        default=None,
        help="Directory for durable per-product detail cache. Defaults to <data-cache-dir>/product-details.",
    )
    build.add_argument(
        "--no-detail-cache",
        action="store_true",
        help="Disable the durable per-product detail cache used by --with-details.",
    )
    build.add_argument(
        "--request-cache-dir",
        type=Path,
        default=None,
        help="Directory for short-lived HTTP response cache. Defaults to .tcgjson-cache/http/<UTC date>.",
    )
    build.add_argument(
        "--request-cache-ttl-hours",
        type=float,
        default=24.0,
        help="Hours to reuse cached TCGplayer API responses during local builds.",
    )
    build.add_argument(
        "--no-request-cache",
        action="store_true",
        help="Disable the short-lived HTTP response cache.",
    )

    assemble = subparsers.add_parser("assemble-release", help="Assemble manifest and metrics from per-line release outputs")
    assemble.add_argument("--output", type=Path, default=Path("release"))
    assemble.add_argument(
        "--metrics-dir",
        type=Path,
        default=None,
        help="Directory containing per-product-line metrics JSON files. Defaults to <output>/.metrics.",
    )

    games = subparsers.add_parser("games", help="Report TCGplayer product-line support")
    games.add_argument("--output", type=Path, default=Path("games.md"))
    games.add_argument("--json-output", type=Path, default=Path("games.json"))

    docs = subparsers.add_parser("docs", help="Generate source-controlled catalog documentation")
    docs_subparsers = docs.add_subparsers(dest="docs_command", required=True)
    docs_generate = docs_subparsers.add_parser("generate", help="Generate Markdown docs from release artifacts")
    docs_generate.add_argument("--release-dir", type=Path, default=Path("release"))
    docs_generate.add_argument("--previous-release-dir", type=Path, default=None)
    docs_generate.add_argument("--output", type=Path, default=Path("docs/catalog"))
    docs_generate.add_argument("--release-tag", default="")
    docs_generate.add_argument("--release-url", default="")
    docs_generate.add_argument(
        "--no-probe-catalog-banners",
        action="store_true",
        help="Skip CDN probes used to pick representative current-catalog row backgrounds.",
    )

    ops = subparsers.add_parser("ops", help="Evaluate operational constraints")
    ops_subparsers = ops.add_subparsers(dest="ops_command", required=True)
    evaluate = ops_subparsers.add_parser("evaluate", help="Evaluate cache and build metrics against constraints")
    evaluate.add_argument("--constraints", type=Path, default=DEFAULT_CONSTRAINTS_PATH)
    evaluate.add_argument("--metrics", type=Path, default=None)
    evaluate.add_argument("--data-cache-dir", type=Path, default=Path("data-cache"))
    evaluate.add_argument("--json", action="store_true", help="Write machine-readable evaluation JSON.")
    evaluate.add_argument("--strict", action="store_true", help="Exit non-zero when operating targets are exceeded.")
    cache_delta = ops_subparsers.add_parser("cache-delta", help="Print uncommitted data-cache delta in MiB")
    cache_delta.add_argument("--data-cache-dir", type=Path, default=Path("data-cache"))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "build":
        checkpoint_dir = None if args.no_checkpoints else args.checkpoint_dir or Path(".tcgjson-cache") / "set-checkpoints"
        detail_cache_dir = None
        if args.with_details and not args.no_detail_cache:
            detail_cache_dir = args.detail_cache_dir or args.data_cache_dir / "product-details"
        request_cache_dir = None
        if not args.no_request_cache:
            utc_date = dt.datetime.now(dt.timezone.utc).date().isoformat()
            request_cache_dir = args.request_cache_dir or Path(".tcgjson-cache") / "http" / utc_date
        client = TCGplayerClient(
            request_cache_dir=request_cache_dir,
            request_cache_ttl_seconds=int(args.request_cache_ttl_hours * 60 * 60),
        )
        manifest = build_release(
            args.output,
            args.product_lines,
            max_sets=args.max_sets,
            with_skus=args.with_details,
            cache_dir=args.cache_dir,
            refresh_recent_sets=args.refresh_recent_sets,
            client=client,
            progress=not args.no_progress and sys.stderr.isatty(),
            log_progress=not args.no_progress,
            checkpoint_dir=checkpoint_dir,
            detail_cache_dir=detail_cache_dir,
        )
        print(f"Wrote {len(manifest['data'])} bulk files to {args.output}")
        return 0
    if args.command == "assemble-release":
        manifest = assemble_release(args.output, metrics_dir=args.metrics_dir)
        print(f"Assembled {len(manifest['data'])} bulk files in {args.output}")
        return 0
    if args.command == "games":
        client = TCGplayerClient()
        report = discover_game_support(client)
        write_game_support_report(report, args.output, json_output=args.json_output)
        enabled = sum(1 for row in report["games"] if row["enabled"])
        print(f"Wrote {args.output} with {enabled} enabled product lines")
        return 0
    if args.command == "docs" and args.docs_command == "generate":
        written = generate_catalog_docs(
            release_dir=args.release_dir,
            output_dir=args.output,
            previous_release_dir=args.previous_release_dir,
            release_tag=args.release_tag,
            release_url=args.release_url,
            probe_catalog_banners=not args.no_probe_catalog_banners,
        )
        print(f"Wrote {len(written)} catalog doc files to {args.output}")
        return 0
    if args.command == "ops" and args.ops_command == "evaluate":
        evaluation = evaluate_operations(
            constraints_path=args.constraints,
            metrics_path=args.metrics,
            data_cache_dir=args.data_cache_dir,
        )
        if args.json:
            import json

            print(json.dumps(evaluation, indent=2, sort_keys=True))
        else:
            print(evaluation_text(evaluation))
        return 0 if evaluation["passed"] or not args.strict else 1
    if args.command == "ops" and args.ops_command == "cache-delta":
        print(data_cache_delta_megabytes(args.data_cache_dir))
        return 0
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
