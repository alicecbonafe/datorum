import re
from typing import Optional, List, Tuple
import random

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, ScrapedDocument


class PlanaltoBRScraper(BaseScraper):
    """
    Scraper para leis do Planalto (planalto.gov.br).
    Detecta estrutura jurídica por classes CSS ou regex.
    """

    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
    ]

    PATTERNS: dict[str, re.Pattern] = {
        "titulo":    re.compile(r"^TÍTULO\s+[IVXLCDM]+", re.IGNORECASE),
        "capitulo":  re.compile(r"^CAPÍTULO\s+[IVXLCDM]+", re.IGNORECASE),
        "secao":     re.compile(r"^Seção\s+[IVXLCDM]+", re.IGNORECASE),
        "artigo":    re.compile(r"^(Art\.\s*\d+[º°]?(?:-[A-Z])?)", re.IGNORECASE),
        "paragrafo": re.compile(r"^(§\s*\d+[º°]?|Parágrafo\s+único)", re.IGNORECASE),
        "inciso":    re.compile(r"^([IVXLCDM]+\s*[-–]\s*)", re.IGNORECASE),
        "alinea":    re.compile(r"^([a-z]\)\s*)", re.IGNORECASE),
    }

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            'User-Agent': random.choice(self.USER_AGENTS)
        })

    def extract(self, url: str, **kwargs) -> ScrapedDocument:
        raw = self._fetch(url)
        soup = BeautifulSoup(raw, "html.parser")

        container = soup.find("div", class_="texto-lei")
        if not container:
            container = soup.find("body") or soup

        for tag in container.find_all(["script", "style", "noscript"]):
            tag.decompose()

        elements = self._collect_text_elements(container)
        markdown_lines = self._process_elements(elements)

        title = kwargs.get("title") or self._extract_title(soup, url)

        return ScrapedDocument(
            title=title,
            license=kwargs.get("license", "Public Domain (Lei Federal)"),
            source=url,
            metadata=kwargs.get("metadata", {}),
            body="\n\n".join(markdown_lines).strip(),
        )

    def _collect_text_elements(self, container: Tag) -> List[Tag]:
        """Coleta elementos de texto (p e div) sem duplicação."""
        elements = []
        for tag in container.find_all(["p", "div"]):
            if tag.name == "div" and tag.find(["p", "div"]):
                continue
            if tag.get_text(strip=True):
                elements.append(tag)
        return elements

    def _process_elements(self, elements: List[Tag]) -> List[str]:
        output = []

        first_heading_level = 2
        current_heading_branch = []
        current_heading_level = first_heading_level

        current_list_branch = []

        for el in elements:
            text = self._clean_text(el.get_text())
            if not text:
                continue

            dtype = None
            for _dtype, pattern in self.PATTERNS.items():
                if pattern.match(text):
                    dtype = _dtype
                    break

            if dtype:
                if dtype in ("titulo", "capitulo", "secao"):
                    if dtype not in current_heading_branch:
                        current_heading_branch.append(dtype)
                        current_heading_level = current_heading_level + 1 if len(current_heading_branch) > 1 else first_heading_level
                    elif dtype != current_heading_branch[len(current_heading_branch)-1]:
                        current_heading_level = first_heading_level
                        old_heading_branch = current_heading_branch
                        current_heading_branch = []
                        for _level in old_heading_branch:
                            current_heading_branch.append(_level)
                            if _level == dtype:
                                break
                            current_heading_level += 1
                    line = self._format_heading(text, current_heading_level)
                    output.append(line)

                elif dtype in ("artigo", "paragrafo", "inciso", "alinea"):
                    if dtype == "artigo":
                        current_list_branch = ["artigo"]
                    elif dtype == "paragrafo":
                        current_list_branch = ["artigo", "paragrafo"]
                    elif dtype not in current_list_branch:
                        current_list_branch.append(dtype)
                    elif dtype != current_list_branch[len(current_list_branch)-1]:
                        old_list_branch = current_list_branch
                        current_list_branch = []
                        for _level in old_list_branch:
                            current_list_branch.append(_level)
                            if _level == dtype:
                                break
                    line = self._format_device(text, dtype, len(current_list_branch)-1)
                    output.append(line)
                continue

            output.append(text)

        return output

    def _format_heading(self, text: str, level: int) -> str:
        """Formata headings com nível ajustado: # para o documento (não usado aqui),
        ## para Título, ### para Capítulo, #### para Seção, ##### para Artigo."""
        return f"{'#' * level} {text}"

    def _format_device(self, text: str, dtype: str, level: int) -> str:
        """Formata dispositivo: marcador em negrito, conteúdo em texto normal."""
        pattern = self.PATTERNS[dtype]
        match = pattern.match(text)
        if match:
            marker = match.group(1)
            rest = text[len(marker):].strip()
            bullet = '- ' if dtype in ("inciso", "alinea") else ''
            return f"{'  '*level}{bullet}**{marker}** {rest}"
        return f"{'  '*level}- {text}"

    def _clean_text(self, text: str) -> str:
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _extract_title(self, soup: BeautifulSoup, url: str) -> str:
        title_tag = soup.find("title")
        if title_tag:
            return title_tag.get_text(strip=True)
        return url.split("/")[-1].replace(".html", "").replace(".htm", "")