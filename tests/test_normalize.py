from tcgjson.config import product_line_for_name, slugify
from tcgjson.normalize import (
    apply_product_details,
    apply_search_product_metadata,
    extract_metadata,
    extract_skus,
)


def test_slugify_keeps_stable_ascii_slugs() -> None:
    assert slugify("Star Wars Unlimited") == "star-wars-unlimited"
    assert product_line_for_name("fab").slug == "flesh-and-blood"


def test_extract_skus_accepts_common_detail_shapes() -> None:
    assert extract_skus({"skus": [{"sku": 5, "condition": "NM", "variant": "Foil"}]}) == [
        {"sku": 5, "condition": "NM", "printing": "Foil", "language": ""}
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
    product = {"productId": 540376, "name": "Director Krennic"}

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


def test_apply_product_details_adds_skus_and_multiple_images() -> None:
    product = {
        "productId": 100191,
        "name": "Jace, Vryn's Prodigy",
        "setId": 1512,
        "imageUrls": ["https://tcgplayer-cdn.tcgplayer.com/product/100191_in_1000x1000.jpg"],
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
    assert product["skus"][0]["sku"] == 10
