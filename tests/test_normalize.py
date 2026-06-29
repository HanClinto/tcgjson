from tcgjson.config import product_line_for_name, slugify
from tcgjson.normalize import (
    apply_product_details,
    apply_search_product_metadata,
    compact_product,
    extract_metadata,
    extract_skus,
    group_priceguide_products,
)


def test_slugify_keeps_stable_ascii_slugs() -> None:
    assert slugify("Star Wars Unlimited") == "star-wars-unlimited"
    assert product_line_for_name("fab").slug == "flesh-and-blood"


def test_group_priceguide_products_merges_printings() -> None:
    products = group_priceguide_products(
        [
            {
                "productID": 123,
                "productName": "Example Card",
                "number": "001",
                "rarity": "Rare",
                "printing": "Normal",
                "condition": "Near Mint",
                "lowPrice": 1.0,
                "marketPrice": 1.5,
                "sales": 4,
                "productConditionID": 456,
            },
            {
                "productID": 123,
                "productName": "Example Card",
                "number": "001",
                "rarity": "Rare",
                "printing": "Foil",
                "condition": "Near Mint",
                "lowPrice": 2.0,
                "marketPrice": 2.5,
                "sales": 1,
                "productConditionID": 789,
            },
        ],
        product_line_name="Pokemon",
        product_line_id=3,
        product_line_url_name="pokemon",
        set_row={"setNameId": 99, "name": "Example Set", "urlName": "example-set"},
    )

    assert len(products) == 1
    assert products[0]["foilings"] == ["Foil", "Normal"]
    assert len(products[0]["priceGuide"]) == 2
    assert products[0]["productLineId"] == 3
    assert products[0]["setId"] == 99
    assert "imageUrl" not in products[0]
    assert "sales" not in products[0]["priceGuide"][0]
    assert "tcgplayerProductConditionId" not in products[0]["priceGuide"][0]
    compact = compact_product(products[0])
    assert compact["tcgplayerProductId"] == 123
    assert "imageUrl" not in compact
    assert compact["imageUrls"] == ["https://tcgplayer-cdn.tcgplayer.com/product/123_in_1000x1000.jpg"]


def test_extract_skus_accepts_common_detail_shapes() -> None:
    assert extract_skus({"skus": [{"sku": 5, "condition": "NM", "variant": "Foil"}]}) == [
        {"tcgplayerSkuId": 5, "condition": "NM", "printing": "Foil", "language": ""}
    ]


def test_extract_metadata_promotes_common_card_fields() -> None:
    metadata = extract_metadata(
        {
            "customAttributes": {
                "description": "Draw a card.",
                "color": ["Blue"],
                "fullType": "Instant",
                "convertedCost": "2",
                "power": None,
                "number": "001",
            },
            "formattedAttributes": {"Artist": "Example Artist", "Rarity": "C"},
        }
    )

    assert metadata["rulesText"] == "Draw a card."
    assert metadata["colors"] == ["Blue"]
    assert metadata["typeLine"] == "Instant"
    assert metadata["convertedCost"] == "2"
    assert metadata["artist"] == "Example Artist"
    assert metadata["customAttributes"]["number"] == "001"


def test_apply_search_product_metadata_preserves_custom_attributes() -> None:
    product = {"tcgplayerProductId": 540376, "name": "Director Krennic"}

    apply_search_product_metadata(
        product,
        {
            "customAttributes": {
                "description": "When Played: Create a token.",
                "aspect": "Vigilance;Villainy",
                "traits": "Official;Imperial",
                "number": "001/252",
            }
        },
    )

    assert product["metadata"]["rulesText"] == "When Played: Create a token."
    assert product["metadata"]["customAttributes"]["aspect"] == "Vigilance;Villainy"
    assert product["metadata"]["customAttributes"]["traits"] == "Official;Imperial"


def test_apply_product_details_adds_skus_to_matching_priceguide_rows_and_multiple_images() -> None:
    product = {
        "tcgplayerProductId": 100191,
        "name": "Jace, Vryn's Prodigy",
        "productLineId": 1,
        "setId": 1512,
        "imageUrls": ["https://tcgplayer-cdn.tcgplayer.com/product/100191_in_1000x1000.jpg"],
        "priceGuide": [
            {"condition": "Near Mint Foil", "printing": "Foil", "lowPrice": 1.0, "marketPrice": 2.0}
        ],
    }

    apply_product_details(
        product,
        {
            "imageCount": 2,
            "skus": [
                {"sku": 10, "condition": "Near Mint", "variant": "Foil", "language": "English"},
                {"sku": 11, "condition": "Near Mint", "variant": "Normal", "language": "English"},
            ],
        },
    )

    assert product["imageUrls"] == [
        "https://tcgplayer-cdn.tcgplayer.com/product/100191_in_1000x1000.jpg",
        "https://tcgplayer-cdn.tcgplayer.com/product/100191_1_in_1000x1000.jpg",
    ]
    assert product["priceGuide"][0]["tcgplayerSkuIds"] == [10]
