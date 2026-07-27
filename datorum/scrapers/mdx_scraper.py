import re

import requests
import yaml
from bs4 import BeautifulSoup, NavigableString

from .base import BaseScraper, ScrapedDocument


class MDXScraper(BaseScraper):
    _BLOCK_TAGS = ("div", "p", "li", "tr", "section", "table", "ul", "ol")

    def extract(self, url: str, **kwargs) -> ScrapedDocument:
        if not url.endswith("/"):
            url += "/"

        result = ScrapedDocument(
            title=kwargs["title"],
            license=kwargs["license"],
            source=url,
        )

        toctree = yaml.safe_load(self._fetch(url + "_toctree.yml"))

        seen = set()
        chunks = []
        for _depth, _title, _local in self._flatten_toctree(toctree):
            heading_level = min(_depth + 1, 6)

            if _local is None:
                chunks.append(f"\n{'#' * heading_level} {_title}\n")
                continue

            if _local in seen:
                continue
            seen.add(_local)

            _url = url + _local + ".md"
            try:
                raw = self._fetch(_url)
            except requests.HTTPError as e:
                print(f"  skip({e.response.status_code}): {_local}")
                continue

            chunks.append(f"\n{'#' * heading_level} {_title}\n")
            chunks.append(self._clean_mdx(raw))
            print(f"  fetched: {_local}")

        result.body = "\n".join(chunks)
        return result

    def _flatten_toctree(self, entries, depth=0):
        """Yield (depth, title, local_path_or_None) in document order."""
        for entry in entries:
            title = entry.get("title", "")
            local = entry.get("local")
            sections = entry.get("sections")

            if local and not sections:
                yield depth, title, local
            else:
                # Section header (may or may not also have its own landing page)
                yield depth, title, local  # local may be None or a landing page
                if sections:
                    yield from self._flatten_toctree(sections, depth + 1)

    def _clean_mdx(self, text: str) -> str:
        """Strip MDX/JSX-only constructs while preserving the markdown content."""

        # Leading HTML comment (license/copyright header)
        text = re.sub(r"^\s*<!--.*?-->\s*", "", text, count=1, flags=re.DOTALL)

        # MDX comments: {/* ... */}
        text = re.sub(r"\{/\*.*?\*/\}", "", text, flags=re.DOTALL)

        # <Tip>...</Tip>, <Tip warning={true}>...</Tip> -> keep content as a blockquote-ish note
        def tip_repl(m):
            inner = m.group(1).strip()
            return "\n> **Note:** " + inner.replace("\n", "\n> ") + "\n"

        text = re.sub(r"<Tip[^>]*>(.*?)</Tip>", tip_repl, text, flags=re.DOTALL)

        # Video/iframe embeds -> drop entirely (not useful for a text RAG store)
        text = re.sub(r"<Youtube[^/]*/?>", "", text)
        text = re.sub(r"<iframe.*?</iframe>", "", text, flags=re.DOTALL)
        text = re.sub(r"<iframe[^>]*/?>", "", text)

        # <hfoptions id="..."><hfoption id="pytorch"> ... </hfoption></hfoptions>
        # Keep the content, turn each option id into a small heading so context isn't lost
        text = re.sub(r"</?hfoptions[^>]*>", "", text)
        text = re.sub(r'<hfoption id="([^"]*)">', r"\n**Option: \1**\n", text)
        text = re.sub(r"</hfoption>", "", text)

        # [[autodoc]] Some.Class.Path  (and any indented "- all" / "- method" lines under it)
        # These pull docstrings from the Python source at build time; they aren't
        # present in this file, so leave a clear pointer instead of silently
        # dropping the reference.
        def autodoc_repl(m):
            target = m.group(1).strip()
            return f"\n> API reference: `{target}` — see docstrings in the PEFT source code.\n"

        text = re.sub(r"\[\[autodoc\]\]\s*(\S+)", autodoc_repl, text)
        # Drop the "    - all" / "    - method_name" lines that follow autodoc blocks
        text = re.sub(r"^\s*-\s+(all|[\w\.]+)\s*$", "", text, flags=re.MULTILINE)

        # Strip remaining raw HTML/JSX layout tags (div, i, span, img, a, ...),
        # protecting code blocks first so things like `<model_name>` or
        # `<|endoftext|>` inside backticks aren't mistaken for tags.
        text, placeholders = self._protect_code(text)
        text = self._strip_html(text)
        text = self._restore_code(text, placeholders)

        # Collapse excess blank lines / trailing whitespace per line
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()

    def _protect_code(self, text: str):
        """Swap fenced/inline code out for placeholders so the HTML parser below
        can't mistake things like `<|endoftext|>` or `<model_name>` inside code
        for real tags and eat them."""
        placeholders = {}
        counter = [0]

        def repl(m):
            key = f"\x00CODE{counter[0]}\x00"
            placeholders[key] = m.group(0)
            counter[0] += 1
            return key

        text = re.sub(r"```.*?```", repl, text, flags=re.DOTALL)
        text = re.sub(r"`[^`\n]+`", repl, text)
        return text, placeholders

    def _strip_html(self, text: str) -> str:
        """Strip the raw HTML/JSX layout wrappers (div, i, span, img, a, ...)
        that doc-builder uses for styling on the rendered site, keeping the
        actual text content (and turning <a href> into a markdown link)."""
        soup = BeautifulSoup(text, "html.parser")

        # Images are decorative screenshots/diagrams on these pages — not useful
        # for a text RAG index, so drop them rather than emitting a broken
        # markdown image reference.
        for img in soup.find_all("img"):
            img.decompose()

        for tag in soup.find_all(["iframe", "youtube"]):
            tag.decompose()

        # Turn links into markdown links before unwrapping their parent divs,
        # so we still capture where an internal doc link pointed.
        for a in soup.find_all("a"):
            href = a.get("href", "")
            link_text = a.get_text(" ", strip=True)
            a.replace_with(f"[{link_text}]({href})" if href else link_text)

        for br in soup.find_all("br"):
            br.replace_with("\n")

        # Insert paragraph breaks after block-level containers before flattening,
        # so content that was visually separated doesn't run together.
        for tag in soup.find_all(self._BLOCK_TAGS):
            tag.insert_after(NavigableString("\n\n"))

        return soup.get_text()

    def _restore_code(self, text: str, placeholders: dict) -> str:
        for key, val in placeholders.items():
            text = text.replace(key, val)
        return text
