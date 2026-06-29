"""Product-line defaults for weekly builds."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProductLine:
    name: str
    slug: str
    aliases: tuple[str, ...] = ()


KNOWN_PRODUCT_LINES: tuple[ProductLine, ...] = (
    ProductLine("Pokemon", "pokemon", ("pokemon", "pokemon-tcg")),
    ProductLine("YuGiOh", "yugioh", ("yu-gi-oh", "yugioh")),
    ProductLine("One Piece Card Game", "one-piece", ("one-piece", "one piece")),
    ProductLine("Flesh and Blood TCG", "flesh-and-blood", ("flesh and blood", "fab")),
    ProductLine("Star Wars Unlimited", "star-wars-unlimited", ("star wars unlimited",)),
    ProductLine("Disney Lorcana", "lorcana", ("lorcana", "disney lorcana")),
    ProductLine(
        "Riftbound: League of Legends Trading Card Game",
        "riftbound",
        ("riftbound", "riftbound league of legends"),
    ),
    ProductLine("Union Arena", "union-arena", ("union arena",)),
)

MANUAL_INCLUDED_PRODUCT_LINES: tuple[ProductLine, ...] = (
    ProductLine(
        "Riftbound: League of Legends Trading Card Game",
        "riftbound",
        ("riftbound", "riftbound league of legends"),
    ),
    ProductLine("Union Arena", "union-arena", ("union arena",)),
)

MANUAL_EXCLUDED_PRODUCT_LINES: tuple[ProductLine, ...] = ()


def slugify(value: str) -> str:
    out = []
    previous_dash = False
    for char in value.casefold().replace("&", " and "):
        if char.isalnum():
            out.append(char)
            previous_dash = False
        elif not previous_dash:
            out.append("-")
            previous_dash = True
    return "".join(out).strip("-") or "unknown"


def normalize_key(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def default_product_line_names() -> list[str]:
    return [line.name for line in KNOWN_PRODUCT_LINES]


def product_line_for_name(name: str) -> ProductLine:
    wanted = normalize_key(name)
    for line in KNOWN_PRODUCT_LINES:
        candidates = (line.name, line.slug, *line.aliases)
        for candidate in candidates:
            key = normalize_key(candidate)
            if key == wanted or key in wanted or wanted in key:
                return line
    return ProductLine(name, slugify(name))
