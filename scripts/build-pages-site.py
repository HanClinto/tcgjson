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
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


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
      {nav}
    </aside>
    <main class=\"content-wrap\">
      <article class=\"page doc-card\">
        {content}
      </article>
      <footer class=\"footer\">Generated from source-controlled Markdown. JSON catalog files are published through GitHub Releases.</footer>
    </main>
  </div>
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
    html_rows = ["<div class=\"table-wrap\"><table>", "<thead><tr>"]
    html_rows.extend(f"<th>{render_inline(cell, Path('.'))}</th>" for cell in header)
    html_rows.append("</tr></thead><tbody>")
    for row in body:
        html_rows.append("<tr>")
        html_rows.extend(f"<td>{render_inline(cell, Path('.'))}</td>" for cell in row)
        html_rows.append("</tr>")
    html_rows.append("</tbody></table></div>")
    return "".join(html_rows)


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def render_inline(text: str, source_dir: Path) -> str:
    code_values: list[str] = []

    def store_code(match: re.Match[str]) -> str:
        code_values.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\u0000CODE{len(code_values) - 1}\u0000"

    text = INLINE_CODE_RE.sub(store_code, text)
    text = html.escape(text)
    text = text.replace("_Generated by", "<em>Generated by").replace("._", ".</em>")

    def link(match: re.Match[str]) -> str:
        label = match.group(1)
        target = html.unescape(match.group(2))
        href = convert_link(target, source_dir)
        return f'<a href="{html.escape(href, quote=True)}">{label}</a>'

    text = LINK_RE.sub(link, text)
    for index, value in enumerate(code_values):
        text = text.replace(f"\u0000CODE{index}\u0000", value)
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
