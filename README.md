# tcgjson

`tcgjson` builds weekly bulk JSON catalog exports from TCGplayer catalog data.
It is intentionally narrow: reliable consolidated downloads by product line,
not storefront inventory, not image datasets, and not marketplace listing
archives.

The shape is inspired by Scryfall bulk data and MTGJSON:

- a machine-readable manifest describing every generated file;
- stable file types and filenames;
- per-product-line JSON files;
- compact files for common catalog use;
- full files that keep product, price-guide, and optional SKU-level identifiers.

## Current Scope

The default build targets popular card-game product lines that TCGplayer exposes
through its catalog and price-guide endpoints:

- Pokemon
- YuGiOh
- One Piece Card Game
- Flesh and Blood TCG
- Star Wars Unlimited
- Disney Lorcana

Each product line produces at least two files:

- `<slug>.json`: compact catalog metadata for products and sets.
- `<slug>.full.json`: full normalized catalog data, including price-guide rows
  and optional SKU IDs when `--with-skus` is enabled.

The build also writes `bulk-data.json`, a Scryfall-style manifest with file
types, descriptions, timestamps, sizes, SHA-256 digests, and relative download
paths. GitHub Releases attach all generated JSON files weekly.

## Data Sources

The first implementation uses the fast path from `ccg_card_id`:

- `https://mp-search-api.tcgplayer.com/v1/search/productLines`
- `https://mpapi.tcgplayer.com/v2/Catalog/SetNames`
- `https://infinite-api.tcgplayer.com/priceguide/set/{setId}/cards/?rows=5000&productTypeID=1`

Optional SKU enrichment uses:

- `https://mp-search-api.tcgplayer.com/v2/product/{productId}/details`

The price-guide path is much faster than crawling search results and contains
the core product, set, collector number, rarity, print/condition, price, and
TCGplayer product-condition identifiers needed for bulk catalog delivery. SKU
details are an explicit enrichment pass because they require one request per
product.

## Future Work: Listos

Building historical back catalogs of Listos, TCGplayer listings with seller
photos, is explicitly future work and is not implemented here. The Listos work
belongs in a later dataset/archive track because it has different size, rate,
retention, image, and privacy considerations than catalog bulk JSON delivery.

## Local Usage

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

# Build the default weekly export set.
tcgjson build --output release

# Add SKU-level details. This is slower because it fetches per-product details.
tcgjson build --output release --with-skus

# Faster smoke build for development.
tcgjson build --output release --product-line Pokemon --max-sets 2
```

## Efficient Weekly Updates

The first full export can take longer than is comfortable for GitHub-hosted
runners, especially once SKU-level enrichment is enabled. The intended operating
model is:

1. Prime the catalog locally with a full read.
2. Upload that local output as the first GitHub Release.
3. Let scheduled GitHub Actions runs reuse the prior release and only refresh
   missing sets plus a small number of recent sets per product line.

Local priming:

```bash
tcgjson build --output release
python -m tcgjson.validate release
gh release create bootstrap-$(date +%Y-%m-%d) release/*.json \
  --repo HanClinto/tcgjson \
  --title "Bootstrap catalog $(date +%Y-%m-%d)" \
  --notes "Initial locally primed tcgjson catalog export."
```

Incremental update from a previous release directory:

```bash
tcgjson build --output release \
  --cache-dir release-cache \
  --refresh-recent-sets 3
```

The scheduled workflow downloads the latest release into `release-cache` before
building. Cached full catalogs are reused set-by-set; any missing sets are
fetched, and the `--refresh-recent-sets` newest sets are refetched so new release
activity stays fresh without recrawling entire back catalogs. A manual full
refresh can still be run locally whenever older price-guide rows need a complete
rebake.

## Release Layout

```text
release/
  bulk-data.json
  pokemon.json
  pokemon.full.json
  yugioh.json
  yugioh.full.json
  ...
```

`bulk-data.json` is the stable entry point. Consumers should read it first and
then fetch the files they need by `type`.

## GitHub Actions

The weekly workflow runs on Monday, builds the catalog, validates the generated
manifest, and publishes a GitHub Release named `weekly-YYYY-MM-DD`. It can also
be started manually from the Actions tab.

## Legal Notes

This project is not produced by or endorsed by TCGplayer or any game publisher.
TCGplayer and product-line names are trademarks of their respective owners.
Catalog and price information should be treated as informational and may become
stale.
