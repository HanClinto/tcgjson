#!/usr/bin/env python3
"""Build a styled GitHub Pages site from docs/catalog Markdown."""
from __future__ import annotations

import argparse
import html
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


@dataclass(frozen=True)
class Page:
    source: Path
    output: Path
    title: str
    href: str
    nav_title: str
    section: str


INLINE_CODE_RE = re.compile(r"`([^`]+)`")
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
CARD_LINK_RE = re.compile(r'<a class="tcg-card-link" href="[^"]+" data-card-preview="[^"]+">.*?</a>')
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
PROJECT_URL = "https://github.com/HanClinto/tcgjson"


STYLE = """
:root {
  --bg: #cdbda6;
  --paper: #f0e5d4;
  --ink: #2d2922;
  --muted: #756c5e;
  --line: #c7b9a5;
  --line-strong: #ac987a;
  --accent: #3b6b5e;
  --accent-dark: #2c5348;
  --accent-soft: #cddbd2;
  --gold: #80653a;
  --code-bg: #ded2bf;
  --shadow: 0 10px 24px rgba(58, 43, 24, 0.07);
  color-scheme: light;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background:
    linear-gradient(180deg, rgba(224, 211, 191, 0.82), rgba(205, 189, 166, 0.98)),
    radial-gradient(circle at top left, rgba(59, 107, 94, 0.055), transparent 34rem),
    var(--bg);
  color: var(--ink);
  font-family: Charter, "Bitstream Charter", "Sitka Text", Cambria, Georgia, serif;
  line-height: 1.6;
}

.site-shell {
  display: grid;
  grid-template-columns: 18rem minmax(0, 1fr);
  min-height: 100vh;
}

.sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  overflow: auto;
  padding: 1.25rem 1rem 2rem;
  border-right: 1px solid var(--line);
  background: rgba(240, 229, 212, 0.92);
  backdrop-filter: blur(12px);
}

.brand {
  display: block;
  margin: 0 0 1.25rem;
  color: var(--ink);
  text-decoration: none;
}

.brand-title {
  display: block;
  font-size: 1.45rem;
  font-weight: 700;
  letter-spacing: 0;
}

.brand-subtitle {
  display: block;
  margin-top: 0.15rem;
  color: var(--muted);
  font-size: 0.9rem;
}

.project-link {
  display: inline-flex;
  margin: 0 0 0.65rem;
  color: var(--accent-dark);
  font-family: Avenir Next, Avenir, Segoe UI, sans-serif;
  font-size: 0.88rem;
  font-weight: 600;
  text-decoration-color: rgba(47, 125, 103, 0.35);
  text-underline-offset: 0.16em;
}

.project-link:hover {
  color: var(--accent);
  text-decoration-color: currentColor;
}

.nav-section {
  margin: 1.15rem 0;
}

.nav-heading {
  margin: 0 0 0.4rem;
  color: var(--gold);
  font-family: Avenir Next, Avenir, Segoe UI, sans-serif;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.nav-link {
  display: block;
  padding: 0.34rem 0.45rem;
  border-radius: 0.4rem;
  color: var(--accent-dark);
  font-family: Avenir Next, Avenir, Segoe UI, sans-serif;
  font-size: 0.92rem;
  text-decoration: none;
}

.nav-link:hover,
.nav-link[aria-current="page"] {
  background: var(--accent-soft);
  color: var(--accent-dark);
}

.content-wrap {
  padding: 3rem clamp(1rem, 4vw, 4rem) 5rem;
}

.page {
  max-width: 72rem;
  margin: 0 auto;
}

.doc-card {
  padding: clamp(1.25rem, 3vw, 2.5rem);
  border: 1px solid var(--line);
  border-radius: 0.5rem;
  background: rgba(240, 229, 212, 0.95);
  box-shadow: var(--shadow);
}

h1,
h2,
h3,
h4 {
  line-height: 1.18;
}

h1 {
  margin: 0 0 1rem;
  color: #2a261f;
  font-size: clamp(2.2rem, 5vw, 4.4rem);
  letter-spacing: 0;
}

h2 {
  margin-top: 2.3rem;
  padding-top: 1.2rem;
  border-top: 1px solid var(--line);
  color: var(--accent-dark);
  font-size: clamp(1.45rem, 2.5vw, 2.05rem);
}

h3 {
  margin-top: 1.75rem;
  color: #544735;
  font-size: 1.25rem;
}

p,
li {
  font-size: 1.02rem;
}

p:first-of-type {
  color: #51493d;
}

a {
  color: var(--accent-dark);
  text-decoration-color: rgba(47, 125, 103, 0.35);
  text-underline-offset: 0.16em;
}

a:hover {
  color: var(--accent);
  text-decoration-color: currentColor;
}

code {
  padding: 0.12rem 0.28rem;
  border-radius: 0.28rem;
  background: var(--code-bg);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.9em;
}

pre {
  overflow-x: auto;
  padding: 0.85rem 1rem;
  border: 1px solid var(--line);
  border-radius: 0.4rem;
  background: var(--code-bg);
}

pre code {
  padding: 0;
  background: transparent;
}

details {
  margin: 0.75rem 0;
  border: 1px solid var(--line);
  border-radius: 0.45rem;
  background: rgba(222, 210, 191, 0.35);
}

summary {
  cursor: pointer;
  padding: 0.62rem 0.78rem;
  color: var(--accent-dark);
  font-family: Avenir Next, Avenir, Segoe UI, sans-serif;
  font-weight: 700;
}

details pre {
  margin: 0 0.78rem 0.78rem;
}

.tcg-card-link {
  font-weight: 700;
  text-decoration-style: dotted;
}

.tcg-card-popover {
  position: fixed;
  z-index: 20;
  display: grid;
  grid-template-columns: minmax(8rem, 12rem) minmax(18rem, 28rem);
  max-width: min(42rem, calc(100vw - 1.5rem));
  max-height: calc(100vh - 1.5rem);
  overflow: hidden;
  border: 1px solid rgba(48, 39, 28, 0.18);
  border-radius: 0.55rem;
  background: #fffaf0;
  box-shadow: 0 22px 48px rgba(58, 43, 24, 0.24);
  color: #201d18;
  font-family: Avenir Next, Avenir, Segoe UI, sans-serif;
}

.tcg-card-popover[hidden] {
  display: none;
}

.tcg-card-popover::before {
  content: "";
  position: absolute;
  inset: -0.75rem;
  z-index: -1;
}

.tcg-card-popover img {
  display: block;
  width: 100%;
  height: auto;
  max-height: calc(100vh - 1.5rem);
  object-fit: contain;
  background: #211a14;
}

.tcg-card-popover-body {
  max-height: calc(100vh - 1.5rem);
  overflow: auto;
  padding: 0.82rem 0.95rem;
}

.tcg-card-popover-title {
  margin: 0;
  color: #17130f;
  font-size: 1rem;
  font-weight: 800;
  line-height: 1.22;
}

.tcg-card-popover-subtitle {
  margin: 0.18rem 0 0.7rem;
  color: #676056;
  font-size: 0.82rem;
}

.tcg-card-popover dl {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 0.24rem 0.7rem;
  margin: 0;
  font-size: 0.8rem;
}

.tcg-card-popover dt {
  color: #514838;
  font-weight: 800;
}

.tcg-card-popover dd {
  margin: 0;
  min-width: 0;
  overflow-wrap: anywhere;
}

.tcg-card-popover-list {
  margin: 0.08rem 0 0;
  padding-left: 1rem;
}

.tcg-card-popover-list li {
  font-size: inherit;
  line-height: 1.35;
}

.tcg-card-popover-list strong {
  color: #514838;
}

.tcg-card-popover-text {
  margin-top: 0.45rem;
  padding-top: 0.45rem;
  border-top: 1px solid #e0d7c8;
  color: #2f2a23;
  font-size: 0.8rem;
  line-height: 1.35;
  white-space: pre-line;
}

.table-wrap {
  overflow: auto;
  margin: 1rem 0 1.5rem;
  border: 1px solid var(--line);
  border-radius: 0.45rem;
  background: #f0e5d4;
}

table {
  width: 100%;
  border-collapse: collapse;
  min-width: 42rem;
}

.banner-table table {
  min-width: 48rem;
}

th,
td {
  padding: 0.65rem 0.78rem;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}

th {
  background: #ded0b9;
  color: #554833;
  font-family: Avenir Next, Avenir, Segoe UI, sans-serif;
  font-size: 0.78rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

tr:last-child td {
  border-bottom: 0;
}

td:nth-child(n + 2):not(:last-child),
th:nth-child(n + 2):not(:last-child) {
  text-align: right;
}

td:nth-child(2),
th:nth-child(2) {
  text-align: left;
}

.banner-table tbody tr {
  background-image:
    linear-gradient(90deg, rgba(45, 41, 34, 0.58), rgba(45, 41, 34, 0.2) 10rem, rgba(240, 229, 212, 0.38) 17rem, #f0e5d4 25rem),
    var(--banner-image, none);
  background-position: left center, left center;
  background-repeat: no-repeat;
  background-size: 100% 100%, 26rem auto;
}

.banner-table tbody td {
  background: transparent;
}

.banner-table tbody td:first-child {
  width: 28%;
  min-width: 14rem;
  color: #fff7e8;
  font-weight: 700;
  text-align: left;
  text-shadow: 0 1px 3px rgba(45, 41, 34, 0.75);
}

.banner-table tbody td:first-child a {
  color: #fff7e8;
  text-decoration-color: rgba(255, 247, 232, 0.55);
  text-shadow: inherit;
}

.banner-table tbody td:first-child a:hover {
  color: #fffef7;
  text-decoration-color: currentColor;
}

td img {
  display: block;
  width: 11rem;
  max-width: 100%;
  aspect-ratio: 3 / 1;
  object-fit: cover;
  opacity: 0;
}

td img[data-loaded="true"] {
  border: 1px solid rgba(128, 101, 58, 0.18);
  border-radius: 0.35rem;
  box-shadow: 0 3px 10px rgba(58, 43, 24, 0.1);
  opacity: 1;
}

ul {
  padding-left: 1.25rem;
}

blockquote,
.generated-note {
  margin: 1rem 0;
  padding: 0.75rem 1rem;
  border-left: 0.25rem solid var(--accent);
  background: var(--accent-soft);
  color: #3e5b51;
}

.footer {
  max-width: 72rem;
  margin: 1.5rem auto 0;
  color: var(--muted);
  font-family: Avenir Next, Avenir, Segoe UI, sans-serif;
  font-size: 0.85rem;
}

@media (max-width: 860px) {
  .site-shell {
    display: block;
  }

  .sidebar {
    position: relative;
    height: auto;
    overflow: visible;
    padding: 0.75rem 0.72rem 0.55rem;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .brand {
    margin-bottom: 0.65rem;
  }

  .brand-title {
    font-size: 1.18rem;
  }

  .brand-subtitle {
    font-size: 0.78rem;
  }

  .project-link {
    margin-bottom: 0.25rem;
    font-size: 0.78rem;
  }

  .nav-section {
    display: block;
    width: 100%;
    margin: 0.55rem 0 0;
    overflow-x: auto;
    padding-bottom: 0.15rem;
    scroll-snap-type: x proximity;
    white-space: nowrap;
  }

  .nav-heading {
    margin-bottom: 0.3rem;
    font-size: 0.66rem;
  }

  .nav-link {
    display: inline-flex;
    align-items: center;
    min-height: 2rem;
    margin: 0 0.35rem 0.35rem 0;
    max-width: 17rem;
    overflow: hidden;
    padding: 0.28rem 0.5rem;
    border: 1px solid var(--line);
    background: rgba(240, 229, 212, 0.82);
    font-size: 0.84rem;
    line-height: 1.25;
    scroll-snap-align: start;
    text-overflow: ellipsis;
  }

  .content-wrap {
    padding: 0.85rem 0.72rem 3rem;
  }

  .doc-card {
    padding: 0.95rem;
  }

  .tcg-card-popover {
    grid-template-columns: minmax(5.8rem, 7.5rem) minmax(0, 1fr);
    max-width: calc(100vw - 1rem);
  }

  h1 {
    font-size: 2rem;
  }

  h2 {
    font-size: 1.35rem;
  }

  p,
  li {
    font-size: 0.98rem;
  }
}
""".strip()


CARD_PREVIEW_SCRIPT = r"""
(() => {
  const links = document.querySelectorAll(".tcg-card-link[data-card-preview]");
  if (!links.length) return;

  const popover = document.createElement("aside");
  popover.className = "tcg-card-popover";
  popover.hidden = true;
  document.body.appendChild(popover);
  let activeLink = null;
  let hideTimer = 0;

  const decodePayload = (value) => {
    try {
      return JSON.parse(decodeURIComponent(value));
    } catch {
      return null;
    }
  };

  const labelFor = (key) => key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/^./, (letter) => letter.toUpperCase());

  const textValue = (value) => {
    if (Array.isArray(value)) return value.map(textValue).filter(Boolean).join(", ");
    if (value && typeof value === "object") {
      return Object.entries(value)
        .map(([key, nestedValue]) => `${labelFor(key)}: ${textValue(nestedValue)}`)
        .filter((line) => !line.endsWith(": "))
        .join(", ");
    }
    if (value == null) return "";
    return String(value)
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<[^>]*>/g, "")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  };

  const renderValue = (value, depth = 0) => {
    if (Array.isArray(value)) {
      const nested = value.map((item) => renderValue(item, depth + 1)).filter(Boolean);
      if (!nested.length) return "";
      if (nested.every((item) => !item.startsWith("<"))) return escapeHtml(nested.join(", "));
      return `<ul class="tcg-card-popover-list">${nested.map((item) => `<li>${item}</li>`).join("")}</ul>`;
    }
    if (value && typeof value === "object") {
      const items = Object.entries(value)
        .map(([key, nestedValue]) => {
          const rendered = renderValue(nestedValue, depth + 1);
          return rendered ? `<li><strong>${escapeHtml(labelFor(key))}:</strong> ${rendered}</li>` : "";
        })
        .filter(Boolean)
        .join("");
      return items ? `<ul class="tcg-card-popover-list">${items}</ul>` : "";
    }
    return escapeHtml(textValue(value));
  };

  const detailRows = (card) => {
    const metadata = card.metadata && typeof card.metadata === "object" ? card.metadata : {};
    const rows = [
      ["Product ID", card.tcgplayerProductId],
      ["Set", card.setName],
      ["Collector #", card.collectorNumber],
      ["Rarity", card.rarity],
      ["Foilings", card.foilings],
    ];
    const metadataRows = Object.entries(metadata)
      .filter(([key, value]) => !["description", "flavorText", "oracleText", "rulesText", "text"].includes(key) && textValue(value))
      .slice(0, 6)
      .map(([key, value]) => [labelFor(key), value]);
    return rows.concat(metadataRows).filter(([, value]) => textValue(value));
  };

  const rulesText = (card) => {
    const metadata = card.metadata && typeof card.metadata === "object" ? card.metadata : {};
    return textValue(metadata.oracleText || metadata.rulesText || metadata.description || metadata.text);
  };

  const render = (card) => {
    const image = card.imageUrl
      ? `<img src="${escapeHtml(card.imageUrl)}" alt="" referrerpolicy="no-referrer">`
      : "";
    const subtitle = [card.productLine, card.rarity].filter(Boolean).join(" - ");
    const rows = detailRows(card)
      .map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${renderValue(value)}</dd>`)
      .join("");
    const text = rulesText(card);
    popover.innerHTML = `${image}<div class="tcg-card-popover-body"><h3 class="tcg-card-popover-title">${escapeHtml(card.name || "Card")}</h3><p class="tcg-card-popover-subtitle">${escapeHtml(subtitle)}</p><dl>${rows}</dl>${text ? `<p class="tcg-card-popover-text">${escapeHtml(text)}</p>` : ""}</div>`;
  };

  const escapeHtml = (value) => String(value).replace(/[&<>"]/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
  }[char]));

  const position = (link) => {
    const rect = link.getBoundingClientRect();
    const gap = 12;
    const width = popover.offsetWidth;
    const height = popover.offsetHeight;
    let left = rect.right + gap;
    if (left + width > window.innerWidth - gap) left = rect.left - width - gap;
    left = Math.max(gap, Math.min(left, window.innerWidth - width - gap));
    let top = rect.top - 18;
    if (top + height > window.innerHeight - gap) top = window.innerHeight - height - gap;
    top = Math.max(gap, top);
    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;
  };

  const show = (link) => {
    const card = decodePayload(link.dataset.cardPreview || "");
    if (!card) return;
    window.clearTimeout(hideTimer);
    activeLink = link;
    render(card);
    popover.hidden = false;
    position(link);
  };

  const hide = (force = false) => {
    window.clearTimeout(hideTimer);
    if (!force && (popover.matches(":hover") || activeLink?.matches(":hover") || activeLink === document.activeElement)) {
      return;
    }
    popover.hidden = true;
    activeLink = null;
  };

  const scheduleHide = () => {
    window.clearTimeout(hideTimer);
    hideTimer = window.setTimeout(() => hide(), 180);
  };

  links.forEach((link) => {
    link.addEventListener("mouseenter", () => show(link));
    link.addEventListener("focus", () => show(link));
    link.addEventListener("mouseleave", scheduleHide);
    link.addEventListener("blur", scheduleHide);
  });
  popover.addEventListener("mouseenter", () => window.clearTimeout(hideTimer));
  popover.addEventListener("mouseleave", scheduleHide);
  popover.addEventListener("focusin", () => window.clearTimeout(hideTimer));
  popover.addEventListener("focusout", scheduleHide);
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hide(true);
  });
  window.addEventListener("scroll", () => {
    if (activeLink && !popover.hidden) position(activeLink);
  }, { passive: true });
  window.addEventListener("resize", () => {
    if (activeLink && !popover.hidden) position(activeLink);
  });
})();
""".strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build styled GitHub Pages HTML from docs/catalog Markdown."
    )
    parser.add_argument("--input", type=Path, default=Path("docs/catalog"))
    parser.add_argument("--output", type=Path, default=Path("_site"))
    args = parser.parse_args()

    pages = discover_pages(args.input, args.output)
    if args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "assets").mkdir(parents=True, exist_ok=True)
    (args.output / "assets" / "site.css").write_text(STYLE + "\n", encoding="utf-8")
    (args.output / "assets" / "card-preview.js").write_text(CARD_PREVIEW_SCRIPT + "\n", encoding="utf-8")

    for page in pages:
        page.output.parent.mkdir(parents=True, exist_ok=True)
        markdown = page.source.read_text(encoding="utf-8")
        page.output.write_text(render_page(page, markdown, pages), encoding="utf-8")

    (args.output / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Built {len(pages)} pages in {args.output}")
    return 0


def discover_pages(input_dir: Path, output_dir: Path) -> list[Page]:
    pages = []
    for source in sorted(input_dir.rglob("*.md")):
        relative = source.relative_to(input_dir)
        output_relative = relative.with_suffix(".html")
        if relative.name == "README.md":
            output_relative = relative.with_name("index.html")
        title = extract_title(source)
        section = (
            "Games"
            if relative.parts[0] == "games" and relative.name != "games.md"
            else "Core Docs"
        )
        nav_title = title.replace("tcgjson Catalog Docs", "Overview")
        pages.append(
            Page(
                source=source,
                output=output_dir / output_relative,
                title=title,
                href=output_relative.as_posix(),
                nav_title=nav_title,
                section=section,
            )
        )
    return sorted(pages, key=page_sort_key)


def page_sort_key(page: Page) -> tuple[int, str]:
    core_order = {"index.html": 0, "objects.html": 1, "games.html": 2, "release-history.html": 3}
    if page.section == "Core Docs":
        return (core_order.get(page.href, 50), page.title)
    return (100, page.title)


def extract_title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ").title()


def render_page(page: Page, markdown: str, pages: list[Page]) -> str:
    content = markdown_to_html(markdown, page.source.parent)
    nav = render_nav(page, pages)
    css_path = "../assets/site.css" if "/" in page.href else "assets/site.css"
    script_path = "../assets/card-preview.js" if "/" in page.href else "assets/card-preview.js"
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{html.escape(page.title)} - tcgjson</title>
  <link rel=\"stylesheet\" href=\"{css_path}\">
</head>
<body>
  <div class=\"site-shell\">
    <aside class=\"sidebar\">
      <a class=\"brand\" href=\"{root_href(page)}index.html\">
        <span class=\"brand-title\">tcgjson</span>
        <span class=\"brand-subtitle\">Bulk TCGplayer catalog docs</span>
      </a>
      <a class=\"project-link\" href=\"{PROJECT_URL}\">View project on GitHub</a>
      {nav}
    </aside>
    <main class=\"content-wrap\">
      <article class=\"page doc-card\">
        {content}
      </article>
      <footer class=\"footer\">Generated from source-controlled Markdown. JSON catalog files are published through GitHub Releases. <a href=\"{PROJECT_URL}\">View the project on GitHub</a>.</footer>
    </main>
  </div>
  <script src="{script_path}" defer></script>
</body>
</html>
"""


def render_nav(current: Page, pages: list[Page]) -> str:
    sections = []
    for section in ["Core Docs", "Games"]:
        links = [page for page in pages if page.section == section]
        if not links:
            continue
        lines = [
            f'<nav class="nav-section" aria-label="{html.escape(section)}">',
            f'<div class="nav-heading">{html.escape(section)}</div>',
        ]
        for page in links:
            href = relative_output_href(current, page)
            active = ' aria-current="page"' if page.href == current.href else ""
            lines.append(
                f'<a class="nav-link" href="{href}"{active}>'
                f"{html.escape(page.nav_title)}</a>"
            )
        lines.append("</nav>")
        sections.append("\n".join(lines))
    return "\n".join(sections)


def markdown_to_html(markdown: str, source_dir: Path) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    paragraph: list[str] = []
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            text = " ".join(part.strip() for part in paragraph).strip()
            cls = ' class="generated-note"' if text.startswith("<em>Generated by") else ""
            output.append(f"<p{cls}>{text}</p>")
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            index += 1
            continue
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        separator_chars = set(
            next_line.replace("|", "").replace(":", "").replace("-", "").strip()
        )
        if stripped.startswith("| ") and index + 1 < len(lines) and not separator_chars:
            flush_paragraph()
            table_lines = []
            while index < len(lines) and lines[index].strip().startswith("| "):
                table_lines.append(lines[index].strip())
                index += 1
            output.append(render_table(table_lines))
            continue
        if stripped.startswith("<details>"):
            flush_paragraph()
            html_lines = []
            while index < len(lines):
                html_lines.append(render_html_line(lines[index], source_dir))
                if lines[index].strip() == "</details>":
                    index += 1
                    break
                index += 1
            output.append("\n".join(html_lines))
            continue
        heading = HEADING_RE.match(stripped)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            text = render_inline(heading.group(2), source_dir)
            plain = strip_tags(text)
            output.append(f'<h{level} id="{slugify(plain)}">{text}</h{level}>')
            index += 1
            continue
        if stripped.startswith("- "):
            flush_paragraph()
            items = []
            while index < len(lines) and lines[index].strip().startswith("- "):
                items.append(f"<li>{render_inline(lines[index].strip()[2:], source_dir)}</li>")
                index += 1
            output.append("<ul>" + "".join(items) + "</ul>")
            continue
        paragraph.append(render_inline(stripped, source_dir))
        index += 1
    flush_paragraph()
    return "\n".join(output)


def render_table(lines: list[str]) -> str:
    rows = [split_table_row(line) for line in lines]
    header = rows[0]
    body = rows[2:]
    banner_table = bool(header) and header[0].lower() == "banner"
    visible_header = header[1:] if banner_table else header
    table_class = "table-wrap banner-table" if banner_table else "table-wrap"
    html_rows = [f"<div class=\"{table_class}\"><table>", "<thead><tr>"]
    html_rows.extend(f"<th>{render_inline(cell, Path('.'))}</th>" for cell in visible_header)
    html_rows.append("</tr></thead><tbody>")
    for row in body:
        banner_url = image_src_from_markdown(row[0]) if banner_table and row else ""
        visible_row = row[1:] if banner_table else row
        row_style = f' style="--banner-image: url(&quot;{html.escape(banner_url, quote=True)}&quot;)"' if banner_url else ""
        html_rows.append(f"<tr{row_style}>")
        html_rows.extend(f"<td>{render_inline(cell, Path('.'))}</td>" for cell in visible_row)
        html_rows.append("</tr>")
    html_rows.append("</tbody></table></div>")
    return "".join(html_rows)


def render_html_line(line: str, source_dir: Path) -> str:
    stripped = line.strip()
    if stripped == "```json":
        return '<pre><code class="language-json">'
    if stripped == "```":
        return "</code></pre>"
    if line.startswith("<"):
        return line
    return html.escape(line)


def image_src_from_markdown(value: str) -> str:
    match = IMAGE_RE.search(value)
    if not match:
        return ""
    return convert_link(html.unescape(match.group(2)), Path('.'))


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def render_inline(text: str, source_dir: Path) -> str:
  card_link_values: list[str] = []
  code_values: list[str] = []
  image_values: list[str] = []

  def store_card_link(match: re.Match[str]) -> str:
    card_link_values.append(match.group(0))
    return f"\u0000CARD{len(card_link_values) - 1}\u0000"

  def store_code(match: re.Match[str]) -> str:
    code_values.append(f"<code>{html.escape(match.group(1))}</code>")
    return f"\u0000CODE{len(code_values) - 1}\u0000"

  def store_image(match: re.Match[str]) -> str:
    target = html.unescape(match.group(2))
    src = convert_link(target, source_dir)
    image_values.append(
      f'<img src="{html.escape(src, quote=True)}" alt="" loading="lazy" referrerpolicy="no-referrer" onload="this.dataset.loaded=\'true\'" onerror="this.remove()">'
    )
    return f"\u0000IMAGE{len(image_values) - 1}\u0000"

  text = CARD_LINK_RE.sub(store_card_link, text)
  text = INLINE_CODE_RE.sub(store_code, text)
  text = IMAGE_RE.sub(store_image, text)
  text = html.escape(text)
  text = text.replace("_Generated by", "<em>Generated by").replace("._", ".</em>")

  def link(match: re.Match[str]) -> str:
    label = match.group(1)
    target = html.unescape(match.group(2))
    href = convert_link(target, source_dir)
    return f'<a href="{html.escape(href, quote=True)}">{label}</a>'

  text = LINK_RE.sub(link, text)
  for index, value in enumerate(image_values):
    text = text.replace(f"\u0000IMAGE{index}\u0000", value)
  for index, value in enumerate(code_values):
    text = text.replace(f"\u0000CODE{index}\u0000", value)
  for index, value in enumerate(card_link_values):
    text = text.replace(f"\u0000CARD{index}\u0000", value)
  return text


def convert_link(target: str, source_dir: Path) -> str:
    if target.startswith(("http://", "https://", "#", "mailto:")):
        return target
    if target.endswith(".md"):
        target = target[:-3] + ".html"
    if target.endswith("README.html"):
        target = target[: -len("README.html")] + "index.html"
    return quote(target, safe="/:#.?=&%")


def relative_output_href(current: Page, target: Page) -> str:
    current_dir = Path(current.href).parent
    if str(current_dir) == ".":
        return target.href
    return Path("..").joinpath(target.href).as_posix()


def root_href(page: Page) -> str:
    return "../" if "/" in page.href else ""


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


if __name__ == "__main__":
    raise SystemExit(main())
