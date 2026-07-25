import json
import re
from collections import Counter

from .base import BaseScraper, ScrapedDocument


class ArchiveOrgScraper(BaseScraper):
    """Scrapes a text-bearing archive.org item using its OCR'd plain-text
    derivative (`<identifier>_djvu.txt`), which is the same text you'd get
    from extracting the PDF but without the extra hop.

    On top of the raw OCR text, this runs a handful of cleanup passes
    aimed squarely at the artifacts scanned books produce, so the
    chunk-generation step downstream isn't burning context tokens on
    running headers, page-number lines, and hyphen-split words:

    - Running headers/footers: djvu.txt is page-delimited by a form-feed
      character (\\x0c). We use that to look at the first/last line of
      every page; any line that repeats near-identically across many
      pages (a title running head, "CHAPTER I", etc.) is almost
      certainly page furniture, not content, and gets dropped.
    - Standalone page-number lines (arabic or roman numerals alone on
      a line) are dropped.
    - Common scan-boilerplate lines ("Digitized by ...", "Original
      from ...") are dropped.
    - Words hyphenated across a line-wrap ("exam-\\nple") are rejoined.
    - Remaining single line-wraps (not blank-line paragraph breaks) are
      collapsed into spaces, so OCR's ~80-char hard wrap doesn't survive
      into the text as fake line breaks.
    """

    METADATA_URL = "https://archive.org/metadata/{identifier}"
    DOWNLOAD_URL = "https://archive.org/download/{identifier}/{filename}"

    IDENTIFIER_RE = re.compile(r"archive\.org/(?:details|download)/([^/]+)")

    _PAGE_NUMBER_RE = re.compile(r"^\s*[\divxlcdm]{1,6}\s*$", re.IGNORECASE)
    _BOILERPLATE_RE = re.compile(
        r"^(digitized by|generated for|original from|scanned by|"
        r"public domain[,.]?\s*google)",
        re.IGNORECASE,
    )
    _HEADER_FOOTER_MIN_REPEATS = 3

    
    def extract(self, url: str, **kwargs) -> ScrapedDocument:
        identifier = self._extract_identifier(url)
        print(f"Item identifier: {identifier}")

        item = {}
        try:
            print("  Fetching metadata...")
            item = self._fetch_item_metadata(identifier)
        except Exception as e:
            print(f"  (metadata fetch skipped: {e})")

        item_meta = item.get("metadata", {})
        metadata = kwargs.get("metadata", {})
        for key in ("creator", "date", "publisher", "language"):
            if key in item_meta and key not in metadata:
                value = item_meta[key]
                metadata[key] = ", ".join(value) if isinstance(value, list) else str(value)

        txt_filename = kwargs.get("txt_filename") or self._find_djvu_txt_filename(
            item.get("files", []), identifier
        )
        txt_url = self.DOWNLOAD_URL.format(identifier=identifier, filename=txt_filename)
        print(f"  Fetching OCR text ({txt_filename})...")
        raw_text = self._fetch(txt_url)

        print("  Cleaning OCR noise...")
        body = self._clean(raw_text)

        title = kwargs.get("title") or item_meta.get("title") or identifier

        return ScrapedDocument(
            title=title,
            license=kwargs.get("license", "Unknown"),
            source=f"https://archive.org/details/{identifier}",
            metadata=metadata,
            body=body,
        )


    # ---- fetching ----------------------------------------------------

    def _extract_identifier(self, url: str) -> str:
        m = self.IDENTIFIER_RE.search(url)
        if not m:
            raise ValueError(f"Could not find an archive.org item identifier in: {url}")
        return m.group(1)

    def _fetch_item_metadata(self, identifier: str) -> dict:
        raw = self._fetch(self.METADATA_URL.format(identifier=identifier))
        return json.loads(raw)

    def _find_djvu_txt_filename(self, files: list[dict], identifier: str) -> str:
        """The OCR-text derivative is usually named `<identifier>_djvu.txt`,
        but archive.org actually derives it from the item's uploaded source
        filename -- which only matches the identifier by convention, not by
        guarantee. When they differ (e.g. a human-readable title uploaded
        under a different identifier, as with the Gramsci item), the guessed
        pattern 404s. Look the real filename up in the item's file listing
        instead of assuming the pattern holds.
        """
        for f in files:
            name = f.get("name", "")
            if name.endswith("_djvu.txt"):
                return name
        # Metadata fetch failed, or (rarely) no djvu.txt is listed -- fall
        # back to the old guess so behavior degrades gracefully rather than
        # raising here; a bad guess will still 404 with a clear error.
        return f"{identifier}_djvu.txt"


    # ---- cleaning ------------------------------------------------------

    def _clean(self, raw_text: str) -> str:
        pages = raw_text.split("\x0c") if "\x0c" in raw_text else [raw_text]
        page_lines = [p.strip("\n").split("\n") for p in pages]

        running_lines = self._detect_running_lines(page_lines)

        cleaned_pages = []
        for lines in page_lines:
            kept = []
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    kept.append("")
                    continue
                if stripped in running_lines:
                    continue
                if self._PAGE_NUMBER_RE.match(stripped):
                    continue
                if self._BOILERPLATE_RE.match(stripped):
                    continue
                kept.append(line)
            cleaned_pages.append("\n".join(kept))

        text = "\n\n".join(cleaned_pages)

        # Rejoin words hyphenated across a line-wrap
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

        # Collapse single line-wraps into spaces, keep blank-line paragraph breaks
        text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)

        # Normalize whitespace
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()

    def _detect_running_lines(self, page_lines: list[list[str]]) -> set[str]:
        """Find lines that show up as the first or last non-empty line on
        many pages -- running headers/footers repeat, real content doesn't
        (a book's actual first/last sentence per page changes every page)."""
        header_counts: Counter = Counter()
        footer_counts: Counter = Counter()

        for lines in page_lines:
            non_empty = [l.strip() for l in lines if l.strip()]
            if not non_empty:
                continue
            header_counts[non_empty[0]] += 1
            footer_counts[non_empty[-1]] += 1

        threshold = max(self._HEADER_FOOTER_MIN_REPEATS, len(page_lines) // 4)

        running = {
            line for line, count in header_counts.items()
            if count >= threshold and len(line) < 80
        }
        running |= {
            line for line, count in footer_counts.items()
            if count >= threshold and len(line) < 80
        }
        return running