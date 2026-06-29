from tcgjson.games import default_enabled_product_line_names, discover_game_support, game_support_markdown


class FakeGamesClient:
    def get_popular_games(self):
        return [{"full-title": "Popular Game"}]

    def get_product_lines(self):
        return [
            {"productLineId": 1, "productLineName": "Popular Game", "productLineUrlName": "popular"},
            {
                "productLineId": 89,
                "productLineName": "Riftbound: League of Legends Trading Card Game",
                "productLineUrlName": "riftbound-league-of-legends-trading-card-game",
            },
            {"productLineId": 81, "productLineName": "Union Arena", "productLineUrlName": "union-arena"},
            {"productLineId": 100, "productLineName": "Other Game", "productLineUrlName": "other"},
        ]


def test_default_enabled_product_lines_include_popular_and_manual() -> None:
    names = default_enabled_product_line_names(FakeGamesClient())

    assert names == [
        "Popular Game",
        "Riftbound: League of Legends Trading Card Game",
        "Union Arena",
    ]


def test_game_support_report_uses_checkbox_rows() -> None:
    report = discover_game_support(FakeGamesClient())
    rows = {row["name"]: row for row in report["games"]}
    markdown = game_support_markdown(report)

    assert rows["Riftbound: League of Legends Trading Card Game"]["enabled"] is True
    assert rows["Riftbound: League of Legends Trading Card Game"]["manualInclude"] is True
    assert rows["Other Game"]["enabled"] is False
    assert "| [x] | Riftbound: League of Legends Trading Card Game |" in markdown
    assert "| [ ] | Other Game |" in markdown