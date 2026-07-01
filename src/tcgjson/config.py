"""Product-line defaults for weekly builds."""
from __future__ import annotations

from dataclasses import dataclass
import unicodedata


@dataclass(frozen=True, slots=True)
class ProductLine:
    name: str
    slug: str
    tcgplayer_id: int | None = None
    aliases: tuple[str, ...] = ()


KNOWN_PRODUCT_LINES: tuple[ProductLine, ...] = (
    ProductLine("Magic: The Gathering", "magic-the-gathering", 1, ("magic", "mtg")),
    ProductLine("YuGiOh", "yugioh", 2, ("yu-gi-oh", "yugioh")),
    ProductLine("Pokemon", "pokemon", 3, ("pokemon", "pokemon-tcg")),
    ProductLine("Flesh and Blood TCG", "flesh-and-blood", 62, ("flesh and blood", "fab")),
    ProductLine("Digimon Card Game", "digimon-card-game", 63, ("digimon",)),
    ProductLine("One Piece Card Game", "one-piece", 68, ("one-piece", "one piece")),
    ProductLine("Disney Lorcana", "lorcana", 71, ("lorcana", "disney lorcana")),
    ProductLine("Star Wars: Unlimited", "star-wars-unlimited", 79, ("star wars unlimited",)),
    ProductLine(
        "Riftbound: League of Legends Trading Card Game",
        "riftbound",
        89,
        ("riftbound", "riftbound league of legends"),
    ),
    ProductLine("Union Arena", "union-arena", 81, ("union arena",)),
)

MANUAL_INCLUDED_PRODUCT_LINES: tuple[ProductLine, ...] = (
    ProductLine("Magic: The Gathering", "magic-the-gathering", 1, ("magic", "mtg")),
    ProductLine("YuGiOh", "yugioh", 2, ("yu-gi-oh", "yugioh")),
    ProductLine("Pokemon", "pokemon", 3, ("pokemon", "pokemon-tcg")),
    ProductLine("Digimon Card Game", "digimon-card-game", 63, ("digimon",)),
    ProductLine("One Piece Card Game", "one-piece", 68, ("one-piece", "one piece")),
    ProductLine("Disney Lorcana", "lorcana", 71, ("lorcana", "disney lorcana")),
    ProductLine("Star Wars: Unlimited", "star-wars-unlimited", 79, ("star wars unlimited",)),
    ProductLine(
        "Riftbound: League of Legends Trading Card Game",
        "riftbound",
        89,
        ("riftbound", "riftbound league of legends"),
    ),
    ProductLine("Union Arena", "union-arena", 81, ("union arena",)),
)

MANUAL_EXCLUDED_PRODUCT_LINES: tuple[ProductLine, ...] = ()


def slugify(value: str) -> str:
    out = []
    previous_dash = False
    for char in _ascii_fold(value).replace("&", " and "):
        if char.isalnum():
            out.append(char)
            previous_dash = False
        elif not previous_dash:
            out.append("-")
            previous_dash = True
    return "".join(out).strip("-") or "unknown"


def _ascii_fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_key(value: str) -> str:
    return "".join(char for char in _ascii_fold(value) if char.isalnum())


def default_product_line_names() -> list[str]:
    return [line.name for line in KNOWN_PRODUCT_LINES]


def default_product_line_ids() -> list[int]:
    return [line.tcgplayer_id for line in KNOWN_PRODUCT_LINES if line.tcgplayer_id is not None]


def product_line_for_id(product_line_id: int, fallback_name: str = "") -> ProductLine:
    for line in KNOWN_PRODUCT_LINES:
        if line.tcgplayer_id == product_line_id:
            return line
    name = fallback_name or str(product_line_id)
    return ProductLine(name, slugify(name), product_line_id)


def product_line_for_name(name: str) -> ProductLine:
    wanted = normalize_key(name)
    for line in KNOWN_PRODUCT_LINES:
        candidates = (line.name, line.slug, *line.aliases)
        for candidate in candidates:
            key = normalize_key(candidate)
            if key == wanted or key in wanted or wanted in key:
                return line
    return ProductLine(name, slugify(name))
