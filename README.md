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
# tcgjson

`tcgjson` builds weekly bulk JSON catalog files from TCGplayer catalog data. The goal is deliberately narrow: reliable consolidated catalog downloads for product lines such as Pokemon, Yu-Gi-Oh!, One Piece, Flesh and Blood, Star Wars Unlimited, and Disney Lorcana.

It is inspired by Scryfall bulk data and MTGJSON, but it is not trying to become a gameplay rules database, image mirror, seller-listing archive, or storefront pricing API.

## Scope

Core deliverables:

- One compact JSON file per product line, for basic set/product metadata.
- One full JSON file per product line, including TCGplayer price-guide rows.
- Optional SKU enrichment from TCGplayer product details for product/condition/printing/language SKU IDs.
- A `bulk-data.json` manifest modeled after Scryfall's bulk data object list, with file type, description, size, SHA-256, timestamp, content type, and download URI.
- A weekly GitHub Actions workflow that builds artifacts and attaches them to a rolling public release.

Intentionally out of scope for now:

- Building back catalogs of Listos, meaning TCGplayer listings with photos. The sibling `ccg_card_id` project has notes and endpoint knowledge for historical custom listings, but that should be a future dataset project, not part of this initial catalog delivery surface.
- Downloading or republishing card images.
- Nightly updates. Weekly is enough for catalog use.
- Marketplace inventory, seller data, or live pricing guarantees.

## Output Shape

Each product line produces at least:

- `{product-line}.compact.json`
- `{product-line}.full.json`
- gzip copies of each file for releases

Example compact product entry:

```json
{
  "tcgplayerProductId": 100,
  "name": "Pikachu",
  "collectorNumber": "025",
  "rarity": "Common",
  "imageUrl": "https://tcgplayer-cdn.tcgplayer.com/product/100_in_1000x1000.jpg",
  "foilingOptions": ["Normal"]
}
```

Full files keep the same product/set structure and add `priceRows`; when `--include-skus` is used, products also include the SKU table from TCGplayer product details.

The manifest is written to `bulk-data.json`:

```json
{
  "object": "list",
  "has_more": false,
  "generated_at": "2026-06-29T00:00:00Z",
  "data": [
    {
      "object": "bulk_data",
      "type": "pokemon_compact",
      "name": "pokemon compact catalog",
      "download_uri": "pokemon.compact.json",
      "content_type": "application/json",
      "content_encoding": "identity"
    }
  ]
}
```

## Why Price-Guide First

The `ccg_card_id` TCGplayer exploration found that the price-guide endpoint is the faster bulk source:

`https://infinite-api.tcgplayer.com/priceguide/set/{setId}/cards/?rows=5000&productTypeID=1`

It provides enough for the initial catalog layer: product line, set, product ID, name, collector number, rarity, image URL derivation, foiling/printing options, condition rows, and market/low prices. Per-product details can be layered in later or enabled in a manual workflow run for SKU-heavy files.

## Usage

```bash
python -m pip install '.[dev]'
pytest
tcgjson build --out dist/tcgjson --product-line Pokemon --max-sets 2 --no-gzip
```

Build the default product lines:

```bash
tcgjson build --out dist/tcgjson --workers 4 --rate-limit-delay 0.05
```

Build with SKU enrichment:

```bash
tcgjson build --out dist/tcgjson --product-line Pokemon --include-skus --rate-limit-delay 0.1
```

## Product Lines

The initial default list is conservative:

- Pokemon
- YuGiOh
- One Piece Card Game
- Flesh and Blood TCG
- Star Wars Unlimited
- Disney Lorcana

More TCGplayer product lines can be added by passing `--product-line` or by extending `DEFAULT_PRODUCT_LINES` in [tcgjson/build.py](tcgjson/build.py).

## GitHub Releases

[.github/workflows/build-release.yml](.github/workflows/build-release.yml) runs every Monday and publishes a rolling `weekly` release. Manual workflow dispatch can enable `include_skus` when a deeper file is needed and the extra API time is acceptable.

## License

MIT. See [LICENSE](LICENSE).
