# tcgjson

`tcgjson` publishes reliable, regularly updated bulk catalog JSON for trading
card games listed on TCGplayer.

## Project Goals

- **Reliable bulk data:** dependable card, set, and metadata snapshots that other
  sites and applications can build on.
- **Automatic updates:** catalog refreshes run on
  [GitHub Actions](https://github.com/HanClinto/tcgjson/actions/workflows/weekly-release.yml)
  so future updates are not dependent on manual releases or human follow-through.
- **Broad TCGplayer coverage:** weekly catalog files for multiple card games listed
  on TCGplayer, not just one product line.
- **Practical downloads:** inspired by [mtgjson](https://mtgjson.com/) and
  [Scryfall bulk data](https://scryfall.com/docs/api/bulk-data), with release
  files published through
  [GitHub Releases](https://github.com/HanClinto/tcgjson/releases).
- **Reviewable formats:** docs are generated from source each release to document
  the format of game-specific information available for each card.

## Start Here

- Browse the friendly docs site: <https://hanclinto.github.io/tcgjson/>
- Download JSON files from the latest release: <https://github.com/HanClinto/tcgjson/releases/latest>
- Use `bulk-data.json` first. It is the manifest that lists every generated file,
  file type, size, hash, update timestamp, and download path.

## What You Get

Each weekly release publishes JSON files only:

```text
bulk-data.json
metrics.json
games.json
pokemon.json
pokemon.full.json
pokemon.schema.json
yugioh.json
yugioh.full.json
yugioh.schema.json
...
```

For each supported game/product line:

- `<slug>.json`: compact catalog data for common product and set lookups.
- `<slug>.full.json`: metadata-rich normalized catalog data with deeper fields
  when available, but no pricing fields.
- `<slug>.schema.json`: observed product-field coverage for that game, including
  field paths, types, populated counts, percentages, and examples.

Human-readable docs are published on GitHub Pages and checked into
[docs/catalog](docs/catalog/README.md). Game pages include product field coverage
and game-specific metadata coverage generated from the schema files.

## Supported Catalogs

The weekly build currently targets singles from popular card-game product lines
that TCGplayer exposes through catalog, price-guide, and search endpoints:

- Pokemon
- YuGiOh
- One Piece Card Game
- Star Wars: Unlimited
- Disney Lorcana
- Digimon Card Game
- Riftbound: League of Legends Trading Card Game
- Union Arena

The dataset is intentionally narrow. It does not publish sealed products,
storefront inventory, seller data, downloaded image files, marketplace listing
archives, or pricing data.

## Publishing Schedule

Catalogs are rebuilt automatically on GitHub Actions once per week. The goal is
to scrape TCGplayer's public catalog endpoints once, package the results into a
small set of bulk downloads, and reduce repeated API traffic from people who only
need semi-regular catalog snapshots.

As long as GitHub Actions and TCGplayer's public catalog endpoints remain broadly
compatible with the current workflow, these releases are expected to keep
updating weekly without manual intervention.

This is intentionally not an hourly or daily scraper. If you need card pricing
or near-real-time market data, `tcgjson` is not the right source.

## Using The Data

Start by fetching the latest `bulk-data.json` manifest:

```bash
curl -L -o bulk-data.json \
  https://github.com/HanClinto/tcgjson/releases/latest/download/bulk-data.json
```

Then choose the game files you need. For example, to download Pokemon compact,
full, and schema files from the latest release:

```bash
curl -L -O https://github.com/HanClinto/tcgjson/releases/latest/download/pokemon.json
curl -L -O https://github.com/HanClinto/tcgjson/releases/latest/download/pokemon.full.json
curl -L -O https://github.com/HanClinto/tcgjson/releases/latest/download/pokemon.schema.json
```

Use the compact file when you need a smaller product/set catalog. Use the full
file when you need richer metadata. Use the schema file to understand which
fields are present for that game and how complete they are.

Pricing is intentionally not published. The build may use TCGplayer priceguide
endpoints as a catalog discovery path, but price values are stripped from release
files because weekly bulk catalog snapshots are a poor fit for current market
data.

Minimal Python example:

```python
import json
from pathlib import Path

catalog = json.loads(Path("pokemon.full.json").read_text())
sets_by_id = {item["tcgplayerSetId"]: item for item in catalog["sets"]}

for product in catalog["products"][:5]:
    set_row = sets_by_id.get(product.get("setId"), {})
    print(product["tcgplayerProductId"], product["name"], set_row.get("name"))
```

## Understanding Schema Coverage

Schema files are generated from the products observed in each release. They are
not hand-written promises that every product line has the same shape.

Each field entry includes:

- `path`: dotted field path, such as `metadata.customAttributes.stage`.
- `types`: observed JSON value types.
- `populatedCount`: number of products with a non-empty value.
- `populatedPercent`: percentage of products with a non-empty value.
- `example`: one observed example value.

The generated web docs turn this into friendly per-game tables. For example,
the Pokemon page shows which product fields are universal, which metadata fields
are sparse, and examples of game-specific attributes like HP, stage, attacks, and
weakness.

## Caveats

- TCGplayer catalog fields vary by game, but refreshed product rows are sourced
  from search so normalized objects stay consistent between releases.
- Published catalogs do not include price fields. Pricing changes faster than
  weekly catalog snapshots and should be fetched from an appropriate pricing
  source instead.
- Search exports product identity, set, collector number, rarity, image URLs, and
  metadata when available.
- Image URLs point at TCGplayer CDN assets. This project does not download or
  republish card images.
- Catalog information is informational and may become stale between weekly
  releases.

See [docs/api-notes.md](docs/api-notes.md) for endpoint behavior, metadata notes,
and implementation caveats.

## For Contributors

Most users do not need to build the project locally. If you want to run the
pipeline yourself, change product-line support, evaluate cache behavior, or work
on the GitHub Actions release flow, see [docs/building-yourself.md](docs/building-yourself.md).

## Legal Notes

This project is not produced by or endorsed by TCGplayer or any game publisher.
TCGplayer and product-line names are trademarks of their respective owners.
Catalog information should be treated as informational and may become stale.
