# tcgjson

`tcgjson` builds weekly bulk JSON catalog exports from TCGplayer catalog data.
It is intentionally narrow: reliable consolidated singles downloads by product
line, not sealed products, not storefront inventory, not image datasets, and
not marketplace listing archives.

The shape is inspired by Scryfall bulk data and MTGJSON:

- a machine-readable manifest describing every generated file;
- stable file types and filenames;
- per-product-line JSON files;
- compact files for common catalog use;
- full files that keep product, price-guide, and optional SKU-level identifiers.

## Current Scope

The default build targets singles from popular card-game product lines that
TCGplayer exposes through its catalog and price-guide endpoints:

- Pokemon
- YuGiOh
- One Piece Card Game
- Flesh and Blood TCG
- Star Wars Unlimited
- Disney Lorcana

Each product line produces at least two files:

- `<slug>.json`: compact catalog metadata for products and sets.
- `<slug>.full.json`: full normalized catalog data, including price-guide rows
  and optional SKU IDs/card metadata when `--with-details` is enabled.
- `<slug>.schema.json`: observed full-product schema and field population stats.
- `<slug>.schema.md`: Markdown schema guide for people reading the catalog.

The build also writes `bulk-data.json`, a Scryfall-style manifest with file
types, descriptions, timestamps, sizes, SHA-256 digests, and relative download
paths. GitHub Releases attach all generated JSON and Markdown files weekly.

Each build also writes `metrics.json`, which records total duration, per-product
line duration, request counts, cache reuse, fetched set counts, and product/set
throughput. This file is intended to be easy to ingest into later graphs so we
can track whether incremental updates are saving enough runner time.

Explicitly out of scope for now:

- sealed products, booster boxes, accessories, supplies, and other non-single
  catalog products;
- building historical back catalogs of Listos, meaning TCGplayer listings with
  seller photos;
- downloading or republishing card images;
- marketplace inventory, seller data, or live pricing guarantees;
- nightly updates. Weekly is enough for catalog use.

## Data Sources

The first implementation uses the fast path from `ccg_card_id` where TCGplayer's
price-guide set IDs line up with catalog set IDs:

- `https://mp-search-api.tcgplayer.com/v1/search/productLines`
- `https://mpapi.tcgplayer.com/v2/Catalog/SetNames`
- `https://infinite-api.tcgplayer.com/priceguide/set/{setId}/cards/?rows=5000&productTypeID=1`

See [docs/api-notes.md](docs/api-notes.md) for observed endpoint behavior,
search payloads, sort caveats, metadata coverage, and caching notes.

`productTypeID=1` is treated as the singles price-guide product type. The bulk
catalog intentionally does not fetch sealed products or other non-single product
types yet.

Default builds preserve card metadata from TCGplayer search rows when available.
Search `customAttributes` are stored under each product's `metadata`, and common
fields such as rules text, type line, colors, power/toughness, and converted cost
are promoted when they use shared names. Product-line-specific fields remain in
`metadata.customAttributes` so games like Pokemon, Lorcana, Digimon, One Piece,
Star Wars Unlimited, Riftbound, Union Arena, and Flesh and Blood can keep their
native catalog fields without forcing a single cross-game schema.

Weekly builds use JSON from the previous release as the durable cache. Full
catalog files remain the public starting point, and each release also emits
set-level cache shards named `<slug>.set.<tcgplayerSetId>.json`. The set shards
let builds reuse or inspect one set at a time without loading a whole game file;
only recent or missing sets are refetched from TCGplayer. The project
intentionally does not publish an internal SQLite search cache today. A
JSON-to-SQLite importer may become useful later for low-memory runtime querying,
but the release contract remains JSON.

Optional SKU, formatted-attribute, and extra-image enrichment uses:

- `https://mp-search-api.tcgplayer.com/v2/product/{productId}/details`

When `--with-details` is enabled, the full catalog also preserves SKU IDs,
formatted attributes such as artist, and `imageCount`-derived multi-image URLs
from product details. The available fields vary by product line, so the generated
schema files should be treated as the field guide for each catalog.

Some newer product lines expose card products through search, but return empty
payloads from the `infinite-api` price-guide path for their catalog set IDs. For
those sets, `tcgjson` falls back to TCGplayer search:

- `https://mp-search-api.tcgplayer.com/v1/search/request`

Search fallback exports product identity, set, collector number, rarity, image
URL, and aggregate price fields. It does not provide the same per-condition
price-guide rows as the fast price-guide path.

Default product-line selection also uses TCGplayer's popular-game navigation
endpoint:

- `https://marketplace-navigation.tcgplayer.com/marketplace-navigation-search-feature.json`

The singles price-guide path is much faster than crawling search results and,
where available, contains the core product, set, collector number, rarity,
print/condition, and price fields needed for bulk catalog delivery. Search
fallback is slower and less price-rich, but keeps newer games from producing
empty catalog files. SKU details are an explicit enrichment pass because they
require one request per product.

## Future Work: Listos And Non-Singles

Building historical back catalogs of Listos, TCGplayer listings with seller
photos, is explicitly future work and is not implemented here. The Listos work
belongs in a later dataset/archive track because it has different size, rate,
retention, image, and privacy considerations than catalog bulk JSON delivery.
Sealed products and other non-single catalog surfaces are also future work.

## Local Usage

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

# Build the default weekly export set. Per-set checkpoints are written under
# .tcgjson-cache/set-checkpoints, so interrupted local runs can resume.
tcgjson build --output release

# Add SKU IDs, formatted attributes, and multi-image URLs. This is slower because
# it fetches per-product details.
tcgjson build --output release --with-details

# Faster smoke build for development. Product-line IDs are preferred.
tcgjson build --output release --product-line 3 --max-sets 2

# Disable progress bars, set checkpoints, detail caching, or the day-scoped
# request cache.
tcgjson build --output release --no-progress --no-checkpoints --no-request-cache

# Report all TCGplayer product lines and default support status.
tcgjson games --output games.md --json-output games.json
```

## Product-Line Support

When `tcgjson build` is run without `--product-line`, it includes every product
line TCGplayer currently reports as popular, then adds manual inclusions from
[src/tcgjson/config.py](src/tcgjson/config.py). Configuration is keyed by
TCGplayer product-line IDs so catalog downloads are not brittle when display
names change. Names and aliases are kept only for readable output, stable slugs,
and explicit CLI fallbacks. Right now the manual inclusions are:

- `89`: Riftbound: League of Legends Trading Card Game
- `81`: Union Arena

Run `tcgjson games` to generate a checkbox-style report:

```markdown
| Enabled | Product line | Popular | Manual include | Manual exclude | TCGplayer ID |
| --- | --- | --- | --- | --- | --- |
| [x] | Riftbound: League of Legends Trading Card Game |  | yes |  | 89 |
| [x] | Union Arena |  | yes |  | 81 |
```

To turn support on or off, edit `MANUAL_INCLUDED_PRODUCT_LINES` or
`MANUAL_EXCLUDED_PRODUCT_LINES` in [src/tcgjson/config.py](src/tcgjson/config.py)
using TCGplayer product-line IDs. Popular games are included automatically
unless manually excluded.

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

Builds also write per-set checkpoint files under `.tcgjson-cache/set-checkpoints`
by default. Checkpoints are separated by product-line slug and source
(`priceguide` versus `search`) so a search-fallback set cannot overwrite a richer
price-guide set. They are useful for resuming interrupted local runs, but they
duplicate normalized product rows and can be regenerated from TCGplayer set data
plus the durable product-detail cache. For that reason, set checkpoints are
ignored by git unless you explicitly place them elsewhere with `--checkpoint-dir`.
Use `--no-checkpoints` to disable them entirely.

The data cache is intended to be tracked in git, but only for expensive durable
inputs that fit normal git hosting limits. Product-detail responses are cached
under `data-cache/product-details` by product ID, which preserves SKU IDs,
metadata, and multi-image information across weekly runs. Lean builds primarily
reuse previous release JSON files downloaded into `release-cache`; set-level
cache shards are preferred when present, with `<slug>.full.json` retained as a
fallback for older releases. Git then transfers changed tracked cache data
instead of re-uploading a full cache archive every week.

Use `--detail-cache-dir` to place product-detail cache files directly, or
`--no-detail-cache` to force detail refetches during `--with-details` builds.

Local builds also use a short-lived HTTP response cache by default under
`.tcgjson-cache/http/<UTC date>`. This cache is ignored by git and is meant to
avoid hammering TCGplayer during active development reruns, not to become a
published or long-term data source. Use `--request-cache-dir` to place it
elsewhere, `--request-cache-ttl-hours` to adjust the TTL, or
`--no-request-cache` to disable it.

`metrics.json` makes the full-vs-incremental comparison explicit. Key fields for
graphing are:

- `durationSeconds`
- `mode`
- `productLines[].durationSeconds`
- `productLines[].cache.reusedSetCount`
- `productLines[].cache.reusedSetCheckpointCount`
- `productLines[].cache.fetchedSetCount`
- `productLines[].requests.requests`
- `productLines[].requests.cacheHits`
- `productLines[].productCount`

## Operational Constraints

Scheduled update jobs are designed around GitHub-hosted Actions and a durable
git-tracked `data-cache`. The target constraints are recorded in
[`operations-constraints.json`](operations-constraints.json) so they can be
reviewed and evaluated by automation instead of living only in prose.

Current targets:

- Job timeout: 300 minutes, leaving a 15 minute reserve for final cache flushes.
- Cache flush cadence for future resumable jobs: every 15 minutes or before job
  shutdown.
- Intermediate cache push size: keep routine pushes under 100 MiB.
- Data-cache size watchpoint: 2 GiB before reconsidering storage strategy.
- Directory fanout: warn above 500 files in a directory; fail above 1000.
- Concurrency: one cache-writing workflow at a time, using
  `tcgjson-data-cache`.
- Partial progress may update `data-cache`; public release artifacts are only
  published after a complete build validates.

During scheduled builds, the workflow checks the uncommitted `data-cache` delta
on the configured flush cadence. If that delta is at or above
`maxIntermediatePushMegabytes`, the runner commits and pushes `data-cache` while
the build keeps running. It also performs a final cache flush after the build
process exits, even when the build fails, so useful partial progress survives a
timeout or transient API failure.

The workflow uses `scripts/run-build-with-cache-flush.sh` for this behavior. For
local testing, set `CACHE_WRITES_ENABLED=true`; cache checkpoint pushes are
enabled by default when cache writes are enabled. Set `CACHE_PUSH_ENABLED=false`
to create local checkpoint commits without pushing them.

Evaluate current metrics and cache shape with:

```bash
tcgjson ops evaluate \
  --metrics release/metrics.json \
  --data-cache-dir data-cache
```

These targets are soft operating agreements by default. `tcgjson ops evaluate`
prints exceeded targets but exits successfully so scheduled builds do not abort
after already producing useful cache or release artifacts. Use `--strict` only
when an intentionally hard gate is useful, such as a local policy check or a
separate CI job that should fail on drift.

The weekly workflow runs this evaluation after `python -m tcgjson.validate
release` and before committing cache changes or publishing a release.

## Release Layout

```text
release/
  bulk-data.json
  metrics.json
  games.md
  games.json
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
