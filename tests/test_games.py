from tcgjson.games import default_enabled_product_line_ids, default_enabled_product_line_names, discover_game_support, game_support_markdown


class FakeGamesClient:
    def get_popular_games(self):
        return [{"full-title": "Popular Game"}]

    def get_product_lines(self):
        return [
            {"productLineId": 1, "productLineName": "Popular Game", "productLineUrlName": "popular"},
            {"productLineId": 2, "productLineName": "YuGiOh", "productLineUrlName": "yugioh"},
            {"productLineId": 3, "productLineName": "Pokemon", "productLineUrlName": "pokemon"},
            {"productLineId": 63, "productLineName": "Digimon Card Game", "productLineUrlName": "digimon-card-game"},
            {"productLineId": 68, "productLineName": "One Piece Card Game", "productLineUrlName": "one-piece-card-game"},
            {"productLineId": 71, "productLineName": "Disney Lorcana", "productLineUrlName": "lorcana-tcg"},
            {"productLineId": 79, "productLineName": "Star Wars: Unlimited", "productLineUrlName": "star-wars-unlimited"},
            {
                "productLineId": 89,
                "productLineName": "Riftbound: League of Legends Trading Card Game",
                "productLineUrlName": "riftbound-league-of-legends-trading-card-game",
            },
            {"productLineId": 81, "productLineName": "Union Arena", "productLineUrlName": "union-arena"},
            {"productLineId": 100, "productLineName": "Other Game", "productLineUrlName": "other"},
        ]

    def get_latest_sets(self, product_line_id):
        return [
            {
                "categoryId": product_line_id,
                "latestSets": [
                    {
                        "setName": "Sample Set",
                        "setNameId": 123,
                        "cleanSetName": "Sample Set",
                        "releaseDate": "2026-01-01",
                        "isFeaturedSet": True,
                        "isPreOrder": False,
                    }
                ],
            }
        ]


def test_default_enabled_product_lines_include_popular_and_manual() -> None:
    ids = default_enabled_product_line_ids(FakeGamesClient())
    names = default_enabled_product_line_names(FakeGamesClient())

    assert ids == [1, 2, 3, 63, 68, 71, 79, 89, 81]
    assert names == [
        "Popular Game",
        "YuGiOh",
        "Pokemon",
        "Digimon Card Game",
        "One Piece Card Game",
        "Disney Lorcana",
        "Star Wars: Unlimited",
        "Riftbound: League of Legends Trading Card Game",
        "Union Arena",
    ]


def test_game_support_report_uses_checkbox_rows() -> None:
    report = discover_game_support(FakeGamesClient())
    rows = {row["name"]: row for row in report["games"]}
    markdown = game_support_markdown(report)

    assert rows["Riftbound: League of Legends Trading Card Game"]["enabled"] is True
    assert rows["Riftbound: League of Legends Trading Card Game"]["manualInclude"] is True
    assert rows["Digimon Card Game"]["enabled"] is True
    assert rows["Digimon Card Game"]["popular"] is False
    assert rows["Digimon Card Game"]["manualInclude"] is True
    assert rows["Popular Game"]["resources"]["tcgplayer"]["searchUrl"] == "https://www.tcgplayer.com/search/popular/product?productLineName=popular&page=1"
    assert rows["Popular Game"]["resources"]["tcgplayer"]["latestSets"] == [123]
    assert rows["Other Game"]["enabled"] is False
    assert "| [x] | Riftbound: League of Legends Trading Card Game |" in markdown
    assert "| [ ] | Other Game |" in markdown