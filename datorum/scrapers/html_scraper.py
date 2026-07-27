import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, NavigableString

from .base import BaseScraper, ScrapedDocument


class BasicHTMLScraper(BaseScraper):
    """
    Generic HTML scraper that extracts the main textual content.
    Uses a chain of heuristics to find the content container:
    1. <article> or <main>
    2. div with id/class containing 'content', 'main', 'body', 'article'
    3. fallback to <body>
    """

    def extract(self, url: str, **kwargs) -> ScrapedDocument:
        raw = self._fetch(url)
        soup = BeautifulSoup(raw, "html.parser")
        return self._extract_document(soup, url, **kwargs)

    def _extract_document(
        self, soup: BeautifulSoup, url: str, **kwargs
    ) -> ScrapedDocument:
        """Runs the extraction heuristics against an already-parsed soup.
        Split out from extract() so callers that already have a soup in
        hand (e.g. MultiHTMLScraper reusing its index page) don't have to
        refetch the same URL to process it."""

        # 1. Remove script, style, noscript, nav, footer, header (common noise)
        for tag in soup.find_all(
            ["script", "style", "noscript", "nav", "footer", "header"]
        ):
            tag.decompose()

        # 2. Find main content container
        content = self._find_content(soup)

        # 3. Clean up links: keep href as markdown if external, else just text
        for a in content.find_all("a"):
            href = a.get("href", "")
            text = a.get_text(" ", strip=True)
            if href and not href.startswith("#"):
                a.replace_with(f"[{text}]({href})")
            else:
                a.replace_with(text)

        # 4. Convert headings (h1–h6) to markdown # style
        for i in range(1, 7):
            for h in content.find_all(f"h{i}"):
                heading_text = h.get_text(strip=True)
                h.replace_with(f"\n\n{'#' * i} {heading_text}\n\n")

        # 5. Insert paragraph breaks after block tags
        for tag in content.find_all(["p", "div", "section", "li", "blockquote"]):
            tag.insert_after(NavigableString("\n\n"))

        # 6. Get plain text and clean up whitespace
        body = content.get_text()
        body = re.sub(r"[ \t]+", " ", body)
        body = re.sub(r"\n[ \t]+", "\n", body)
        body = re.sub(r"\n{3,}", "\n\n", body).strip()

        # 7. Metadata extraction (if not provided)
        metadata = kwargs.get("metadata", {})
        if "authors" not in metadata:
            # naive author extraction: look for "by Author Name" or meta tags
            meta_author = soup.find("meta", {"name": "author"})
            if meta_author and meta_author.get("content"):
                metadata["authors"] = meta_author["content"]
            else:
                # fallback: first <p> containing "by " might work
                byline = soup.find("p", string=re.compile(r"\bby\b", re.IGNORECASE))
                if byline:
                    metadata["authors"] = byline.get_text(strip=True).replace("by ", "")

        title = kwargs.get("title")
        if not title:
            title_tag = soup.find("title")
            title = title_tag.get_text(strip=True) if title_tag else url.split("/")[-1]

        return ScrapedDocument(
            title=title,
            license=kwargs.get("license", "Unknown"),
            source=url,
            metadata=metadata,
            body=body,
        )

    def _find_content(self, soup: BeautifulSoup):
        """Heuristic chain to select the main content container."""
        # Try <article> or <main>
        for tag in ["article", "main"]:
            elem = soup.find(tag)
            if elem:
                return elem

        # Try common id/class patterns
        selectors = [
            "#content",
            "#main",
            "#body",
            "#article",
            ".content",
            ".main",
            ".body",
            ".article",
            ".post",
            ".entry",
        ]
        for sel in selectors:
            elem = soup.select_one(sel)
            if elem:
                return elem

        # Fallback: <body> or whole soup
        return soup.find("body") or soup


class IndexedHTMLScraper(BasicHTMLScraper):
    """
    Scrapes a whole work spread across multiple HTML pages, starting from
    a single index/contents page.

    Discovery rule: any <a href="..."> on the index page that points to
    another file in the *same folder* -- a bare relative link with no `/`
    in it (so no absolute URLs, no `../` or `sub/` paths, no `mailto:`,
    `javascript:`, etc.) -- is treated as a page of the same work. The
    `#fragment` part of an href (e.g. `preface.htm#c1`) is stripped
    before the same-folder check and before dedup, so multiple anchors
    into the same file only trigger one fetch of that file.

    The index page's own content is preserved: since it's already
    fetched and parsed to find the links, it's run through the same
    extraction pipeline via `_extract_document()` instead of being
    refetched, and placed first in the output. Each linked page is then
    fetched and extracted at most once, in the order its link first
    appears on the index page.
    """

    def extract(self, url: str, **kwargs) -> ScrapedDocument:
        raw = self._fetch(url)
        index_soup = BeautifulSoup(raw, "html.parser")

        seen = {url}
        page_urls = []
        for a in index_soup.find_all("a", href=True):
            href = a["href"].split("#", 1)[0]  # drop in-page anchor targets
            if not self._is_same_folder_link(href):
                continue
            page_url = urljoin(url, href)
            if page_url in seen:
                continue
            seen.add(page_url)
            page_urls.append(page_url)

        # Extract the index page's own content -- reuse the soup we
        # already have, no second fetch of `url`.
        index_doc = self._extract_document(index_soup, url, **kwargs)

        title = kwargs.get("title") or index_doc.title

        chunks = [index_doc.body]
        for page_url in page_urls:
            try:
                page_doc = super().extract(page_url, **kwargs)
            except requests.HTTPError as e:
                print(f"  skip({e.response.status_code}): {page_url}")
                continue
            chunks.append(page_doc.body)
            print(f"  fetched: {page_url}")

        return ScrapedDocument(
            title=title,
            license=kwargs.get("license", "Unknown"),
            source=url,
            metadata=kwargs.get("metadata", {}),
            body="\n\n".join(chunks),
        )

    def _is_same_folder_link(self, href: str) -> bool:
        """True for a bare same-folder filename like 'ch01.htm' (fragment
        already stripped by the caller), false for '' (was anchor-only),
        'mailto:...', '../works/', 'https://...', etc."""
        href = href.strip()
        if not href or ":" in href or "/" in href:
            return False
        return True
