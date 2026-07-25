import re
from bs4 import BeautifulSoup, NavigableString

from .base import BaseScraper, ScrapedDocument


class ArxivHTMLScraper(BaseScraper):

    def extract(self, url: str, **kwargs) -> ScrapedDocument:
        raw_html = self._fetch(url)
        soup = BeautifulSoup(raw_html, "html.parser")

        # arXiv HTML uses latexml; the main content is typically inside ltx_page_main or ltx_document
        main_content = soup.find(class_="ltx_page_main") or soup.find(class_="ltx_document")
        if not main_content:
            main_content = soup.find("body") or soup

        # 1. Strip non-content tags
        for tag in main_content.find_all(["script", "style", "noscript", "svg"]):
            tag.decompose()

        # Drop images, but keep any captions (which are usually sibling elements or in <figcaption>)
        for img in main_content.find_all("img"):
            img.decompose()

        # 2. Restore LaTeX from MathML
        # LaTeXML typically leaves the raw TeX in the 'alttext' attribute of <math> tags
        for math in main_content.find_all("math"):
            alttext = math.get("alttext", "")
            if alttext:
                display = math.get("display", "inline")
                # Block equations
                if display == "block":
                    math.replace_with(f"\n\n$$\n{alttext.strip()}\n$$\n\n")
                # Inline equations
                else:
                    math.replace_with(f"${alttext.strip()}$")
            else:
                math.replace_with(math.get_text())

        # 3. Format Links (keeping text and href)
        for a in main_content.find_all("a"):
            href = a.get("href", "")
            link_text = a.get_text(" ", strip=True)
            # Optionally skip internal page anchors (e.g., "#S1") if you only want external links
            # For comprehensive RAG text, keeping the text without the anchor link is usually cleaner
            if href.startswith("#"):
                a.replace_with(link_text)
            elif href:
                a.replace_with(f"[{link_text}]({href})")
            else:
                a.replace_with(link_text)

        # 4. Format Headings
        for i in range(1, 7):
            for h in main_content.find_all(f"h{i}"):
                heading_text = h.get_text(strip=True)
                h.replace_with(f"\n\n{'#' * i} {heading_text}\n\n")

        # 5. Ensure block spacing for paragraphs and sections
        for tag in main_content.find_all(["p", "div", "section", "li"]):
            tag.insert_after(NavigableString("\n\n"))

        # Extract metadata and title
        title_tag = soup.find("title")
        title = kwargs.get('title')
        if not title:
            # Fallback to HTML title or URL ending
            title = title_tag.get_text(strip=True) if title_tag else url.split("/")[-1]

        metadata = kwargs.get('metadata', {})
        
        # Try to extract authors from the latexml author block if not provided
        authors_div = soup.find(class_="ltx_authors")
        if authors_div and "authors" not in metadata:
            authors = [a.get_text(strip=True) for a in authors_div.find_all(class_="ltx_personname")]
            if authors:
                metadata["authors"] = ", ".join(authors)

        # 6. Extract the flattened text
        body_text = main_content.get_text()

        # 7. Clean up excessive whitespace
        # Collapse horizontal spaces
        body_text = re.sub(r"[ \t]+", " ", body_text)
        # Clean up leading spaces on new lines
        body_text = re.sub(r"\n[ \t]+", "\n", body_text)
        # Collapse multiple newlines into double newlines
        body_text = re.sub(r"\n{3,}", "\n\n", body_text).strip()

        return ScrapedDocument(
            title=title,
            license=kwargs.get('license', 'Unknown'),
            source=url,
            metadata=metadata,
            body=body_text
        )