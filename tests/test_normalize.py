from tcgjson.config import product_line_for_name, slugify
from tcgjson.normalize import compact_product, extract_skus, group_priceguide_products


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
    assert compact_product(products[0])["tcgplayerProductId"] == 123


def test_extract_skus_accepts_common_detail_shapes() -> None:
    assert extract_skus({"skus": [{"skuId": 5, "condition": "NM", "printing": "Foil"}]}) == [
        {"tcgplayerSkuId": 5, "condition": "NM", "printing": "Foil", "language": ""}
    ]
