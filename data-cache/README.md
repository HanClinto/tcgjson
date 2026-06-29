# tcgjson data cache

This directory stores durable build cache files that are useful for future catalog runs but are not part of the public release artifact set.

The default build writes per-set checkpoints under `set-checkpoints/`.
Details-enriched builds also write per-product TCGplayer detail responses under
`product-details/<previous-three-product-id-digits>/<last-three-product-id-digits>/`
so SKU IDs, metadata, and multi-image lookups can be reused by product ID even
when a recent set is refreshed.
