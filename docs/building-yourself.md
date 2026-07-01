# Building tcgjson Yourself

These notes are for contributors and operators who want to run the catalog build pipeline, change supported product lines, or inspect operational behavior. If you only want to use the data, start with the main [README](../README.md) or the catalog docs site at <https://hanclinto.github.io/tcgjson/>.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Local Build Commands

```bash
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

# Generate human-readable docs from a completed release directory.
tcgjson docs generate --release-dir release --output docs/catalog

# Build the styled GitHub Pages site from the generated Markdown docs.
python scripts/build-pages-site.py --input docs/catalog --output _site
```

## Product-Line Support

When `tcgjson build` is run without `--product-line`, it includes every product line TCGplayer currently reports as popular, then adds manual inclusions from [src/tcgjson/config.py](../src/tcgjson/config.py). Configuration is keyed by TCGplayer product-line IDs so catalog downloads are not brittle when display names change. Names and aliases are kept only for readable output, stable slugs, and explicit CLI fallbacks.

Current manual inclusions:

- `89`: Riftbound: League of Legends Trading Card Game
- `81`: Union Arena

Run `tcgjson games` to generate a checkbox-style report:

```markdown
| Enabled | Product line | Popular | Manual include | Manual exclude | TCGplayer ID |
| --- | --- | --- | --- | --- | --- |
| [x] | Riftbound: League of Legends Trading Card Game |  | yes |  | 89 |
| [x] | Union Arena |  | yes |  | 81 |
```

To turn support on or off, edit `MANUAL_INCLUDED_PRODUCT_LINES` or `MANUAL_EXCLUDED_PRODUCT_LINES` in [src/tcgjson/config.py](../src/tcgjson/config.py) using TCGplayer product-line IDs. Popular games are included automatically unless manually excluded.

## Efficient Weekly Updates

The first full export can take longer than is comfortable for GitHub-hosted runners, especially once SKU-level enrichment is enabled. The intended operating model is:

1. Prime the catalog locally with a full read.
2. Upload that local output as the first GitHub Release.
3. Let scheduled GitHub Actions runs reuse the prior release and only refresh missing sets plus a small number of recent sets per product line.

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

The scheduled workflow downloads the latest release into `release-cache` before building. Cached full catalogs are reused set-by-set; any missing sets are fetched, and the `--refresh-recent-sets` newest sets are refetched so new release activity stays fresh without recrawling entire back catalogs. A manual full refresh can still be run locally whenever older price-guide rows need a complete rebake.

Builds also write per-set checkpoint files under `.tcgjson-cache/set-checkpoints` by default. Checkpoints are separated by product-line slug and source (`priceguide` versus `search`) so a search-fallback set cannot overwrite a richer price-guide set. They are useful for resuming interrupted local runs, but they duplicate normalized product rows and can be regenerated from TCGplayer set data plus any local product-detail cache. For that reason, set checkpoints are ignored by git unless you explicitly place them elsewhere with `--checkpoint-dir`. Use `--no-checkpoints` to disable them entirely.

The durable weekly cache is the previous release's JSON, not a git-tracked data cache. Lean builds reuse previous release JSON files downloaded into `release-cache`; each `<slug>.full.json` catalog is loaded one product line at a time and reused set-by-set. Product-detail responses for `--with-details` builds may still be cached locally under `data-cache/product-details`, but `data-cache/` is ignored by git and is not part of the release workflow's checkout or commit path.

Use `--detail-cache-dir` to place product-detail cache files directly, or `--no-detail-cache` to force detail refetches during `--with-details` builds.

Local builds also use a short-lived HTTP response cache by default under `.tcgjson-cache/http/<UTC date>`. This cache is ignored by git and is meant to avoid hammering TCGplayer during active development reruns, not to become a published or long-term data source. Use `--request-cache-dir` to place it elsewhere, `--request-cache-ttl-hours` to adjust the TTL, or `--no-request-cache` to disable it.

## Operational Constraints

Scheduled update jobs are designed around GitHub-hosted Actions and a durable release JSON cache. The target constraints are recorded in [operations-constraints.json](../operations-constraints.json) so they can be reviewed and evaluated by automation instead of living only in prose.

Current targets:

- Job timeout: 300 minutes, leaving a 15 minute reserve for final cache flushes.
- Cache flush cadence for future resumable jobs: every 15 minutes or before job shutdown, if a future tracked cache is reintroduced.
- Intermediate cache push size: keep any future routine cache pushes under 100 MiB.
- Data-cache size watchpoint: 2 GiB before reconsidering local storage strategy.
- Directory fanout: warn above 500 files in a directory; fail above 1000.
- Concurrency: one release workflow at a time, using `tcgjson-weekly-release`.
- Public release artifacts are only published after a complete build validates.

The workflow still uses [scripts/run-build-with-cache-flush.sh](../scripts/run-build-with-cache-flush.sh), but scheduled lean releases leave cache writes disabled. The wrapper remains useful if a future resumable tracked cache is reintroduced or for local experiments with `CACHE_WRITES_ENABLED=true`.

Evaluate current metrics and cache shape with:

```bash
tcgjson ops evaluate \
  --metrics release/metrics.json \
  --data-cache-dir data-cache
```

These targets are soft operating agreements by default. `tcgjson ops evaluate` prints exceeded targets but exits successfully so scheduled builds do not abort after already producing useful cache or release artifacts. Use `--strict` only when an intentionally hard gate is useful, such as a local policy check or a separate CI job that should fail on drift.

The weekly workflow runs this evaluation after `python -m tcgjson.validate release` and before publishing a release.

## GitHub Actions

The weekly workflow runs on Monday, builds the catalog, validates the generated manifest, commits generated Markdown docs under [docs/catalog](catalog/README.md), and publishes a GitHub Release named `weekly-<YYYYMMDD>` using the UTC release date. It can also be started manually from the Actions tab.

GitHub Releases publish JSON files only. Markdown docs are committed to source control and deployed through GitHub Pages.
