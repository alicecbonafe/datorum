import re
import io
import gzip
import tarfile
from pathlib import Path

from .base import BaseScraper, ScrapedDocument


class ArxivTeXScraper(BaseScraper):
    """Scrapes an arXiv paper from its LaTeX source instead of the HTML
    rendering, for papers that don't have an HTML version available.
    """

    ARXIV_ID_RE = re.compile(r"arxiv\.org/(?:abs|pdf|e-print)/([\w.\-/]+?)(?:v\d+)?(?:\.pdf)?/?$")

    def extract(self, url: str, **kwargs) -> ScrapedDocument:
        arxiv_id = self._extract_arxiv_id(url)
        source_url = f"https://arxiv.org/e-print/{arxiv_id}"
        print(f'Article ID: {arxiv_id}')

        print('  Fetching...')
        raw_bytes = self._fetch_bytes(source_url)
        print('  Unpacking...')
        tex_source = self._unpack(raw_bytes)

        print('  Extracting...')
        tex_source = self._strip_comments(tex_source)

        title = kwargs.get("title") or self._extract_command(tex_source, "title") or arxiv_id
        author_raw = self._extract_command(tex_source, "author")
        metadata = kwargs.get("metadata", {})
        if author_raw and "authors" not in metadata:
            metadata["authors"] = self._clean_authors(author_raw)

        body_match = re.search(r"\\begin\{document\}(.*)\\end\{document\}", tex_source, re.DOTALL)
        body = body_match.group(1) if body_match else tex_source

        body = self._strip_bibliography(body)
        for env in ("figure", "figure*", "table", "table*"):
            body = self._strip_environment(body, env)
        body = self._convert_sections(body)
        body = self._convert_formatting(body)
        body = self._convert_citations_refs(body)
        body = self._strip_remaining_commands(body)
        body = self._clean_whitespace(body)

        return ScrapedDocument(
            title=self._strip_remaining_commands(title).strip(),
            license=kwargs.get("license", "Unknown"),
            source=url,
            metadata=metadata,
            body=body,
        )

    # ---- fetching / unpacking ----------------------------------------

    def _fetch_bytes(self, url: str) -> bytes:
        resp = self.session.get(url, timeout=self.REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.content

    def _extract_arxiv_id(self, url: str) -> str:
        m = self.ARXIV_ID_RE.search(url)
        if m:
            return m.group(1)
        return url.rstrip("/").split("/")[-1].replace(".pdf", "")

    def _unpack(self, raw_bytes: bytes) -> str:
        """arXiv's e-print endpoint returns a gzip tarball for multi-file
        submissions, or a single gzipped .tex file for simple ones."""
        tex_files: dict[str, str] = {}

        if raw_bytes[:2] == b"\x1f\x8b":  # gzip magic number
            try:
                with tarfile.open(fileobj=io.BytesIO(raw_bytes), mode="r:gz") as tar:
                    for member in tar.getmembers():
                        if member.isfile() and member.name.endswith(".tex"):
                            f = tar.extractfile(member)
                            if f:
                                tex_files[member.name] = f.read().decode("utf-8", errors="replace")
            except tarfile.ReadError:
                text = gzip.decompress(raw_bytes).decode("utf-8", errors="replace")
                tex_files["main.tex"] = text
        else:
            tex_files["main.tex"] = raw_bytes.decode("utf-8", errors="replace")

        if not tex_files:
            raise ValueError("No .tex files found in arXiv source archive")

        main_name = self._find_main_tex(tex_files)
        return self._resolve_inputs(tex_files[main_name], tex_files)

    def _find_main_tex(self, tex_files: dict[str, str]) -> str:
        candidates = [n for n, c in tex_files.items() if "\\documentclass" in c]
        if not candidates:
            return max(tex_files, key=lambda n: len(tex_files[n]))
        if len(candidates) == 1:
            return candidates[0]
        included: set[str] = set()
        for c in candidates:
            included.update(re.findall(r"\\(?:input|include)\{([^}]+)\}", tex_files[c]))
        for c in candidates:
            stem = Path(c).stem
            if stem not in included and c not in included:
                return c
        return candidates[0]

    def _resolve_inputs(self, text: str, tex_files: dict[str, str], depth: int = 0) -> str:
        if depth > 10:
            return text

        def replace(match: re.Match) -> str:
            name = match.group(1)
            for candidate in (name, f"{name}.tex"):
                if candidate in tex_files:
                    return self._resolve_inputs(tex_files[candidate], tex_files, depth + 1)
            return ""

        return re.sub(r"\\(?:input|include)\{([^}]+)\}", replace, text)

    # ---- cleaning passes -----------------------------------------------

    def _strip_comments(self, text: str) -> str:
        return re.sub(r"(?<!\\)%.*", "", text)

    def _extract_command(self, text: str, command: str) -> str:
        m = re.search(rf"\\{command}(?:\[[^\]]*\])?\{{", text)
        if not m:
            return ""
        return self._extract_braced(text, m.end() - 1)

    def _extract_braced(self, text: str, brace_start: int) -> str:
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[brace_start + 1:i]
        return text[brace_start + 1:]

    def _braced_end(self, text: str, brace_start: int) -> int:
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        return len(text)

    def _clean_authors(self, raw: str) -> str:
        raw = re.sub(r"\\thanks\{.*?\}", "", raw, flags=re.DOTALL)
        raw = re.sub(r"\\(and|AND)", ",", raw)
        raw = self._strip_remaining_commands(raw)
        names = [n.strip() for n in raw.split(",") if n.strip()]
        return ", ".join(names)

    def _strip_bibliography(self, text: str) -> str:
        text = re.sub(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", "", text, flags=re.DOTALL)
        text = re.sub(r"\\bibliography\{[^}]*\}", "", text)
        text = re.sub(r"\\bibliographystyle\{[^}]*\}", "", text)
        return text

    def _strip_environment(self, text: str, env: str) -> str:
        pattern = rf"\\begin\{{{re.escape(env)}\}}.*?\\end\{{{re.escape(env)}\}}"
        return re.sub(pattern, "", text, flags=re.DOTALL)

    def _convert_sections(self, text: str) -> str:
        levels = {
            "section": 1, "section*": 1,
            "subsection": 2, "subsection*": 2,
            "subsubsection": 3, "subsubsection*": 3,
            "paragraph": 4,
        }
        for command, level in levels.items():
            pattern = re.compile(r"\\" + re.escape(command) + r"\{")
            while True:
                m = pattern.search(text)
                if not m:
                    break
                brace_start = m.end() - 1
                title = self._extract_braced(text, brace_start)
                braced_end = self._braced_end(text, brace_start)
                heading = f"\n\n{'#' * level} {title}\n\n"
                text = text[:m.start()] + heading + text[braced_end:]
        return text

    def _convert_formatting(self, text: str) -> str:
        text = re.sub(r"\\textbf\{([^{}]*)\}", r"**\1**", text)
        text = re.sub(r"\\textit\{([^{}]*)\}", r"*\1*", text)
        text = re.sub(r"\\emph\{([^{}]*)\}", r"*\1*", text)
        return text

    def _convert_citations_refs(self, text: str) -> str:
        text = re.sub(r"\\cite[tp]?\{([^}]*)\}", lambda m: f"[{m.group(1)}]", text)
        text = re.sub(r"\\[a-zA-Z]*ref\{([^}]*)\}", lambda m: f"[ref:{m.group(1)}]", text)
        text = re.sub(r"\\label\{[^}]*\}", "", text)
        return text

    def _strip_remaining_commands(self, text: str) -> str:
        # Math is left untouched: $...$, $$...$$, \[...\], equation/align
        # environments are already valid, self-contained LaTeX, exactly like
        # the alttext the HTML scraper pulls out of MathML.
        math_spans = []
        for pattern in (
            r"\$\$.*?\$\$", r"(?<!\$)\$[^$]*\$(?!\$)",
            r"\\\[.*?\\\]", r"\\\(.*?\\\)",
            r"\\begin\{equation\*?\}.*?\\end\{equation\*?\}",
            r"\\begin\{align\*?\}.*?\\end\{align\*?\}",
        ):
            for m in re.finditer(pattern, text, flags=re.DOTALL):
                math_spans.append((m.start(), m.end()))
        math_spans.sort()

        out = []
        cursor = 0
        for start, end in math_spans:
            if start < cursor:
                continue
            out.append(self._strip_commands_only(text[cursor:start]))
            out.append(text[start:end])
            cursor = end
        out.append(self._strip_commands_only(text[cursor:]))
        return "".join(out)

    def _strip_commands_only(self, text: str) -> str:
        for _ in range(3):
            text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}", r"\1", text)
        text = re.sub(r"\\[a-zA-Z]+\*?", "", text)
        text = text.replace("{", "").replace("}", "")
        return text

    def _clean_whitespace(self, text: str) -> str:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()