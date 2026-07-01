import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        values = dict(attrs)
        href = values.get("href")
        if href:
            self.links.append(href)


def test_build_pages_site_renders_docs_and_internal_links(tmp_path) -> None:
    docs_dir = tmp_path / "docs"
    games_dir = docs_dir / "games"
    games_dir.mkdir(parents=True)
    (docs_dir / "README.md").write_text(
        "# tcgjson Catalog Docs\n\nWelcome to [objects](objects.md).\n\n"
        "| Banner | Game | Products |\n"
        "| --- | --- | ---: |\n"
        "| ![Pokemon](https://tcgplayer-cdn.tcgplayer.com/set_icon/604BaseSet.png) | [Pokemon](games/pokemon.md) | 1 |\n",
        encoding="utf-8",
    )
    (docs_dir / "objects.md").write_text("# Object Guide\n\nSee [home](README.md).\n", encoding="utf-8")
    (docs_dir / "games.md").write_text("# Game Index\n\n- [Pokemon](games/pokemon.md)\n", encoding="utf-8")
    (docs_dir / "release-history.md").write_text("# Release History\n\nNothing yet.\n", encoding="utf-8")
    (games_dir / "pokemon.md").write_text(
        "# Pokemon\n\n- Compact catalog: [pokemon.json](https://example.test/pokemon.json)\n\n"
        "<details>\n<summary>Example compact product object</summary>\n\n```json\n{\n  \"name\": \"Alakazam\"\n}\n```\n\n</details>\n\n"
        "![Base Set](https://tcgplayer-cdn.tcgplayer.com/set_icon/604BaseSet.png)\n\n"
        "| Card | Set | Rarity |\n"
        "| --- | --- | --- |\n"
        "| <a class=\"tcg-card-link\" href=\"https://www.tcgplayer.com/product/42382\" data-card-preview=\"%7B%22name%22%3A%22Alakazam%22%2C%22imageUrl%22%3A%22https%3A%2F%2Ftcgplayer-cdn.tcgplayer.com%2Fproduct%2F42382_in_1000x1000.jpg%22%7D\">Alakazam</a> | Base Set | Holo Rare |\n\n"
        "| Banner | Set | Products | TCGplayer |\n"
        "| --- | --- | ---: | --- |\n"
        "| ![Base Set](https://tcgplayer-cdn.tcgplayer.com/set_icon/604BaseSet.png) | Base Set | [1](https://www.tcgplayer.com/search/all/product?q=Pokemon+Base+Set) | [Search](https://www.tcgplayer.com/search/all/product?q=Pokemon+Base+Set) |\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "site"
    subprocess.run(
        [
            sys.executable,
            "scripts/build-pages-site.py",
            "--input",
            str(docs_dir),
            "--output",
            str(output_dir),
        ],
        check=True,
    )

    index = (output_dir / "index.html").read_text(encoding="utf-8")
    game = (output_dir / "games" / "pokemon.html").read_text(encoding="utf-8")
    styles = (output_dir / "assets" / "site.css").read_text(encoding="utf-8")

    assert "tcgjson Catalog Docs" in index
    assert '<link rel="stylesheet" href="assets/site.css">' in index
    assert '<link rel="stylesheet" href="../assets/site.css">' in game
    assert '<script src="assets/card-preview.js" defer></script>' in index
    assert '<script src="../assets/card-preview.js" defer></script>' in game
    assert '<a class="project-link" href="https://github.com/HanClinto/tcgjson">View project on GitHub</a>' in index
    assert '<details>' in game
    assert '<summary>Example compact product object</summary>' in game
    assert '<pre><code class="language-json">' in game
    assert '&quot;name&quot;: &quot;Alakazam&quot;' in game
    assert '<img src="https://tcgplayer-cdn.tcgplayer.com/set_icon/604BaseSet.png" alt="" loading="lazy" referrerpolicy="no-referrer" onload="this.dataset.loaded=\'true\'" onerror="this.remove()">' in game
    assert '<a class="tcg-card-link" href="https://www.tcgplayer.com/product/42382" data-card-preview="%7B%22name%22%3A%22Alakazam%22%2C%22imageUrl%22%3A%22https%3A%2F%2Ftcgplayer-cdn.tcgplayer.com%2Fproduct%2F42382_in_1000x1000.jpg%22%7D">Alakazam</a>' in game
    assert (output_dir / "assets" / "card-preview.js").exists()
    assert '<div class="table-wrap banner-table"><table>' in index
    assert '<th>Banner</th>' not in index
    assert 'style="--banner-image: url(&quot;https://tcgplayer-cdn.tcgplayer.com/set_icon/604BaseSet.png&quot;)"' in index
    assert '<div class="table-wrap banner-table"><table>' in game
    assert '<th>Banner</th>' not in game
    assert 'style="--banner-image: url(&quot;https://tcgplayer-cdn.tcgplayer.com/set_icon/604BaseSet.png&quot;)"' in game
    assert '<td><a href="https://www.tcgplayer.com/search/all/product?q=Pokemon+Base+Set">1</a></td>' in game
    assert ".banner-table tbody td:first-child a" in styles
    assert "background: rgba(35, 31, 25, 0.62);" in styles
    assert ".banner-table tbody td:not(:first-child)" in styles
    assert "0 0 5px #f0e5d4" in styles
    assert '<a class="nav-link" href="games/pokemon.html">Pokemon</a>' in index
    assert '<a class="nav-link" href="../index.html">Overview</a>' in game
    assert (output_dir / ".nojekyll").exists()

    missing = internal_missing_links(output_dir)
    assert missing == []


def internal_missing_links(root: Path) -> list[tuple[str, str]]:
    missing = []
    for page in root.rglob("*.html"):
        parser = LinkParser()
        parser.feed(page.read_text(encoding="utf-8"))
        for href in parser.links:
            parsed = urlparse(href)
            if parsed.scheme or href.startswith("#"):
                continue
            target = (page.parent / href.split("#", 1)[0]).resolve()
            if not target.exists():
                missing.append((page.relative_to(root).as_posix(), href))
    return missing
