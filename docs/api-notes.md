# TCGplayer API Notes

These notes capture observed behavior from the public TCGplayer endpoints used by
`tcgjson`. They are implementation notes, not an official API contract.

## Product Lines

Endpoint:

```text
GET https://mp-search-api.tcgplayer.com/v1/search/productLines
```

Use this to resolve product-line IDs, display names, and URL names. Build
configuration should prefer product-line IDs because display names and URL names
can vary.

## Popular Games

Endpoint:

```text
GET https://marketplace-navigation.tcgplayer.com/marketplace-navigation-search-feature.json
```

The navigation payload exposes product lines TCGplayer currently treats as
popular. `tcgjson` uses this as the default product-line source, then applies
manual includes and excludes from `src/tcgjson/config.py`.

## Set Names

Endpoint:

```text
GET https://mpapi.tcgplayer.com/v2/Catalog/SetNames?categoryId=<productLineId>&active=true
```

Useful fields include `setNameId`, `name`, `urlName`, `abbreviation`,
`releaseDate`, and `isSupplemental`. Set names are the best deterministic unit
for incremental work: sort sets by `releaseDate`, refresh the newest sets, and
reuse cached data for older sets.

Observed caveat: this endpoint does not expose product counts.

## Price Guide Set Cards

Endpoint:

```text
GET https://infinite-api.tcgplayer.com/priceguide/set/<setId>/cards/?rows=5000&productTypeID=1
```

This is the fast path for many established games. It provides card products,
collector numbers, rarity, printings, conditions, and price rows. It does not
provide rich card metadata such as rules text for every game, SKU lists, formatted
attributes, or multi-image counts.

Observed caveat: newer product lines can return an empty payload here even when
the same set has searchable card products. In those cases, use search fallback.

## Search Request

Endpoint:

```text
POST https://mp-search-api.tcgplayer.com/v1/search/request
```

The search endpoint is the most useful lean metadata source. It can return card
metadata in `customAttributes` without a per-product detail request.

Current catalog search payload shape:

```json
{
  "algorithm": "sales_exp_fields_synonym",
  "from": 0,
  "size": 50,
  "filters": {
    "term": {
      "productLineName": ["Star Wars: Unlimited"],
      "setName": ["Spark of Rebellion"],
      "productTypeName": ["Cards"]
    },
    "range": {},
    "match": {}
  },
  "context": {"cart": {}, "shippingCountry": "US", "userProfile": {}},
  "settings": {"useFuzzySearch": false, "didYouMean": {}},
  "sort": {}
}
```

Observed behavior:

- `size=50` works and appears to be the practical page limit.
- `size=500` returns HTTP 400.
- A 50-row page usually took about 0.6-0.9 seconds in local probes.
- Search rows include `customAttributes` for the configured card-game product
  lines we sampled.
- Search rows do not include `skus`, `formattedAttributes`, or `imageCount`.
- Search rows can include listing-shaped fields. Do not persist raw search
  responses as durable catalog cache; normalize and keep only catalog fields.

Useful metadata fields observed in `customAttributes` include:

- Magic: `description`, `flavorText`, `fullType`, `color`, `cardType`,
  `convertedCost`, `power`, `toughness`, `number`, `rarityDbName`, `releaseDate`
- Pokemon: `attack1`, `attack2`, `description`, `energyType`, `hp`, `weakness`,
  `resistance`, `retreatCost`, `stage`, `number`, `rarityDbName`, `releaseDate`
- YuGiOh: `description`, `attack`, `defense`, `attribute`, `monsterType`,
  `level`, `linkRating`, `linkArrows`, `number`, `rarityDbName`, `releaseDate`
- Lorcana: `description`, `flavorText`, `inkType`, `costInk`, `strength`,
  `willpower`, `loreValue`, `classification`, `property`, `number`
- Star Wars Unlimited: `description`, `aspect`, `traits`, `arenaType`, `cost`,
  `power`, `hp`, `epicAction`, `number`, `rarityDbName`, `releaseDate`
- Digimon: `description`, `inheritedEffect`, `securityEffect`, `playCost`,
  `levelLv`, `digivolve*`, `digimonType`, `digimonForm`, `number`
- One Piece: `description`, `attribute`, `color`, `cost`, `counter`, `power`,
  `life`, `subtypes`, `number`
- Flesh and Blood: `description`, `class`, `talent`, `pitchValue`, `cost`,
  `power`, `defenseValue`, `cardSubType`, `number`
- Riftbound: `description`, `domain`, `energyCost`, `powerCost`, `might`, `tag`,
  `number`
- Union Arena: `description`, `seriesName`, `trigger`, `requiredEnergy`,
  `generatedEnergy`, `battlePointBp`, `activationEnergy`, `number`

### Website Search Payloads

TCGplayer's website uses several algorithms and sort payloads. These are useful
for exploration, but `tcgjson` should keep the `productTypeName: ["Cards"]`
filter for singles-only output.

Best match observed on the website:

```json
{
  "algorithm": "sales_dismax",
  "from": 0,
  "size": 24,
  "filters": {
    "term": {"productLineName": ["star-wars-unlimited"], "setName": ["any"]},
    "range": {},
    "match": {}
  },
  "listingSearch": {
    "context": {"cart": {"packages": {}}},
    "filters": {
      "term": {"sellerStatus": "Live", "channelId": 0},
      "range": {"quantity": {"gte": 1}},
      "exclude": {"channelExclusion": 0}
    }
  },
  "context": {
    "cart": {"packages": {}},
    "shippingCountry": "US",
    "userProfile": {"productLineAffinity": "Magic: The Gathering", "priceAffinity": 57}
  },
  "settings": {"useFuzzySearch": true, "didYouMean": {}},
  "sort": {}
}
```

Best selling uses `algorithm: "revenue_dismax"` with an empty `sort` object.

Alphabetical sort uses:

```json
"algorithm": "sales_exp_fields_experiment",
"sort": {"field": "product-sorting-name", "order": "asc"}
```

Price sort uses:

```json
"algorithm": "sales_exp_fields_experiment",
"sort": {"field": "market-price", "order": "desc"}
```

Observed probe results: `product-sorting-name` and `market-price` sort fields
worked with website-style payloads. Ad hoc sort keys such as `releaseDate`,
`createdAt`, `updatedAt`, `productId`, `marketPrice`, `score`, and `setName`
returned server errors when sent as direct field names.

Website-style payload caveat: if `productTypeName: ["Cards"]` is omitted, results
can include sealed products such as booster displays and booster cases.

## Product Details

Endpoint:

```text
GET https://mp-search-api.tcgplayer.com/v2/product/<productId>/details
```

This is the only direct source found so far for:

- complete SKU lists;
- condition, printing, and language combinations independent of active listings;
- `formattedAttributes`, such as Magic artist;
- `imageCount`, used for multi-image URLs.

Details are expensive because they require one request per product. Use them for
explicit full-detail builds, not the default lean weekly path.

## Images

Base image URL pattern:

```text
https://tcgplayer-cdn.tcgplayer.com/product/<productId>_in_1000x1000.jpg
```

For detail payloads with `imageCount > 1`, observed URL pattern is base image plus
numbered extras:

```text
https://tcgplayer-cdn.tcgplayer.com/product/<productId>_in_1000x1000.jpg
https://tcgplayer-cdn.tcgplayer.com/product/<productId>_1_in_1000x1000.jpg
```

Do not discover extra images by probing missing CDN URLs in automated runs; that
would intentionally generate CDN misses. The lean path should emit the base image
only. Multi-image URLs require product details.

## Caching Strategy

Recommended durable caches:

- product details by product ID for explicit full-detail/SKU builds;
- normalized search metadata by product line and set ID for lean builds.

Avoid durable raw HTTP search cache. Raw search responses contain facets,
aggregations, listing-shaped fields, and seller/listing data that are larger and
broader than the catalog data `tcgjson` needs.

Recommended incremental lean behavior:

1. Use release-cache full catalogs to reuse older sets.
2. Refresh the newest sets by `SetNames.releaseDate`.
3. For refreshed or missing sets, fetch priceguide/search and normalized search
   metadata.
4. Store normalized metadata only, not raw search responses.

No reliable `updatedAt` field or sort has been found in search responses yet.