"""Product-line defaults for weekly builds."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProductLine:
    name: str
    slug: str
    aliases: tuple[str, ...] = ()


DEFAULT_PRODUCT_LINES: tuple[ProductLine, ...] = (
    ProductLine("Pokemon", "pokemon", ("pokemon", "pokemon-tcg")),
    ProductLine("YuGiOh", "yugioh", ("yu-gi-oh", "yugioh")),
    ProductLine("One Piece Card Game", "one-piece", ("one-piece", "one piece")),
    ProductLine("Flesh and Blood TCG", "flesh-and-blood", ("flesh and blood", "fab")),
    ProductLine("Star Wars Unlimited", "star-wars-unlimited", ("star wars unlimited",)),
    ProductLine("Disney Lorcana", "lorcana", ("lorcana", "disney lorcana")),
)


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
    return [line.name for line in DEFAULT_PRODUCT_LINES]


def product_line_for_name(name: str) -> ProductLine:
    wanted = normalize_key(name)
    for line in DEFAULT_PRODUCT_LINES:
        candidates = (line.name, line.slug, *line.aliases)
        if any(normalize_key(candidate) == wanted for candidate in candidates):
            return line
    return ProductLine(name, slugify(name))
