from abc import ABC, abstractmethod
from pathlib import Path
import requests
import unicodedata
from urllib.parse import urlparse

from pydantic import BaseModel, Field


class ScrapedDocument(BaseModel):
    title: str
    license: str
    source: str

    metadata: dict[str, str] = Field(default_factory=dict)
    body: str = Field(default='')


class BaseScraper(ABC):

    REQUEST_TIMEOUT: int = 30

    # Characters that are invisible/normalized away entirely
    _STRIP_CHARS = (
        "\ufeff"   # BOM
        "\u200b"   # zero-width space
        "\u200c"   # zero-width non-joiner
        "\u200d"   # zero-width joiner
        "\u00ad"   # soft hyphen
    )

    # Characters that are semantically "a line break" but not literally \n
    _LINEBREAK_CHARS = "\u2028\u2029\u0085"  # LS, PS, NEL


    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                'Datorum - Context Engineering AI Agent'
            )
        })

    @abstractmethod
    def extract(self, url: str, **kwargs) -> ScrapedDocument:
        pass

    def scrap_from(
        self,
        url: str,
        target: Path,
        **kwargs,
    ) -> ScrapedDocument:
        document = self.extract(url, **kwargs)
        self._write(document, target)
        return document

    def _fetch(self, url: str) -> str:
        resp = self.session.get(url, timeout = self.REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.text

    def _render(self, doc: ScrapedDocument) -> str:
        lines = [
            f"# {doc.title}\n",
            f"- **Source**: {doc.source}",
            f"- **License**: {doc.license}",
        ]
        if doc.metadata:
            lines.append("- **Metadata**:")
            for key, val in doc.metadata.items():
                lines.append(f"  - **{key}**: {val}")
        lines.extend(['', doc.body])
        return '\n'.join(lines)

    def _sanitize(self, text: str) -> str:
        # Normalize CRLF/CR -> LF first
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Treat LS/PS/NEL as line breaks, not literal characters
        for ch in self._LINEBREAK_CHARS:
            text = text.replace(ch, "\n")

        # Drop invisible formatting characters
        for ch in self._STRIP_CHARS:
            text = text.replace(ch, "")

        # Non-breaking space -> regular space (keeps word-wrapping sane)
        text = text.replace("\u00a0", " ")

        # Strip remaining C0/C1 control chars except \n and \t
        text = "".join(
            c for c in text
            if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf")
        )

        return text

    def _write(self, document: ScrapedDocument, target: Path):
        markdown = self._sanitize(self._render(document))
        with target.open('w', encoding='utf-8') as f:
            f.write(markdown)

    def _origin(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"