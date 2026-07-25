import re
from pathlib import Path

import requests
import yaml

from .base import BaseScraper, ScrapedDocument


class QMDScraper(BaseScraper):
    """Scraper for Quarto-based documentation repos (any project with a
    `_quarto.yml` book/website config), reading directly from GitHub source
    rather than the rendered HTML site.

    Unlike MDXScraper, there's no single doc-server base URL to resolve
    relative paths against -- Quarto docs are plain files in a GitHub repo,
    fetched via raw.githubusercontent.com. So `extract()` takes `owner`/
    `repo`/`branch` kwargs instead of relying purely on `url`.
    """

    RAW_BASE = "https://raw.githubusercontent.com"
    API_CONTENTS = "https://api.github.com/repos/{owner}/{repo}/contents/{path}"

    def extract(self, url: str, **kwargs) -> ScrapedDocument:
        self._owner = kwargs['owner']
        self._repo = kwargs['repo']
        self._branch = kwargs.get('branch', 'main')
        github_token = kwargs.get('github_token')
        if github_token:
            self.session.headers['Authorization'] = f"Bearer {github_token}"

        quarto_path = kwargs.get('quarto_path', '_quarto.yml')

        result = ScrapedDocument(
            title = kwargs['title'],
            license = kwargs['license'],
            source = f"https://github.com/{self._owner}/{self._repo}",
        )

        quarto = yaml.safe_load(self._fetch(self._raw_url(quarto_path)))
        entries = self._sidebar_entries(quarto)

        seen = set()
        chunks = []
        for depth, title, local in self._flatten_sidebar(entries):
            heading_level = min(depth + 1, 6)

            if local is None:
                chunks.append(f"\n{'#' * heading_level} {title}\n")
                continue

            local = local.lstrip('/')
            if local in seen:
                continue
            seen.add(local)

            try:
                raw = self._fetch(self._raw_url(local))
            except requests.HTTPError as e:
                print(f"  skip({e.response.status_code}): {local}")
                continue

            chunks.append(f"\n{'#' * heading_level} {title}\n")
            chunks.append(self._clean_qmd(raw, base_dir=str(Path(local).parent)))
            print(f"  fetched: {local}")

        result.body = '\n'.join(chunks)
        return result

    # ---- fetching --------------------------------------------------------

    def _raw_url(self, path: str) -> str:
        path = path.lstrip('/')
        return f"{self.RAW_BASE}/{self._owner}/{self._repo}/{self._branch}/{path}"

    def _list_dir(self, path: str) -> list[str]:
        """List `.qmd` file paths in a repo directory, via the GitHub
        contents API. Needed to resolve glob sidebar entries like
        `docs/dataset-formats/*`, which the YAML alone can't tell us."""
        api_url = self.API_CONTENTS.format(
            owner = self._owner, repo = self._repo, path = path.strip('/'),
        )
        resp = self.session.get(
            api_url, params = {'ref': self._branch}, timeout = self.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return sorted(
            item['path'] for item in resp.json()
            if item['type'] == 'file' and item['name'].endswith('.qmd')
        )

    # ---- sidebar parsing ---------------------------------------------------

    def _sidebar_entries(self, quarto: dict) -> list:
        """_quarto.yml nests navigation under `website.sidebar` for website
        projects or `book.chapters` for book projects."""
        website = quarto.get('website')
        if website and 'sidebar' in website:
            sidebar = website['sidebar']
            if isinstance(sidebar, list):  # multiple named sidebars
                sidebar = sidebar[0] if sidebar else {}
            return sidebar.get('contents', [])

        book = quarto.get('book')
        if book and 'chapters' in book:
            return book['chapters']

        raise ValueError(
            "No website.sidebar or book.chapters found in _quarto.yml -- "
            "this repo's nav structure isn't one QMDScraper recognizes."
        )

    def _flatten_sidebar(self, entries, depth=0):
        """Yield (depth, title, local_path_or_None) in document order,
        resolving section headers, plain path strings, {text/href} dicts,
        and glob entries such as 'docs/dataset-formats/*'."""
        for entry in entries:
            if isinstance(entry, str):
                if entry.endswith('/*'):
                    for path in self._list_dir(entry[:-2]):
                        yield depth, self._title_from_path(path), path
                else:
                    yield depth, self._title_from_path(entry), entry
                continue

            title = entry.get('text') or entry.get('section') \
                or self._title_from_path(entry.get('href', ''))
            local = entry.get('href')
            sections = entry.get('contents')

            if local and not sections:
                yield depth, title, local
                continue

            yield depth, title, local  # section header (local may be None)
            if sections:
                if isinstance(sections, str):
                    sections = [sections]
                yield from self._flatten_sidebar(sections, depth + 1)

    def _title_from_path(self, path: str) -> str:
        stem = Path(path).stem.replace('-', ' ').replace('_', ' ')
        return stem.title()

    # ---- content cleaning ---------------------------------------------------

    def _clean_qmd(self, text: str, base_dir: str = '') -> str:
        """Strip Quarto-only constructs while preserving the markdown content."""

        # YAML front matter
        text = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.DOTALL)

        # {{< include path/to/_partial.qmd >}} -> inline the partial, cleaned
        def include_repl(m):
            rel = m.group(1).strip()
            path = rel.lstrip('/') if rel.startswith('/') else str(Path(base_dir) / rel)
            try:
                partial = self._fetch(self._raw_url(path))
            except requests.HTTPError:
                return f"\n> (missing include: `{rel}`)\n"
            return "\n" + self._clean_qmd(partial, base_dir=str(Path(path).parent)) + "\n"

        text = re.sub(r"\{\{<\s*include\s+([^\s>]+)\s*>\}\}", include_repl, text)

        # Video/tweet/embed shortcodes -> drop, not useful for a text RAG store
        text = re.sub(r"\{\{<\s*(video|youtube|tweet|embed)\b.*?>\}\}", "", text)

        # Callout divs: ::: {.callout-note} ... ::: -> a blockquote-style note
        def callout_repl(m):
            label = m.group(1).replace('-', ' ').title()
            inner = m.group(2).strip()
            return "\n> **" + label + ":** " + inner.replace("\n", "\n> ") + "\n"

        text = re.sub(
            r":::+\s*\{\.callout-(\w+)[^\}]*\}\s*\n(.*?)\n:::+",
            callout_repl, text, flags=re.DOTALL,
        )

        # Remaining generic ::: fenced divs (tabsets, panel-layouts, etc.)
        # -> unwrap, keep the content, drop the div markers themselves
        text = re.sub(r":::+\s*\{[^\}]*\}\s*\n", "", text)
        text = re.sub(r"^:::+\s*$", "", text, flags=re.MULTILINE)

        # Cross-refs to other .qmd files -> keep link text, drop the
        # doc-relative path/anchor since it won't resolve outside the site
        text = re.sub(r"\[([^\]]+)\]\([^)]*\.qmd(?:#[^)]*)?\)", r"\1", text)

        # Section anchors like {#sec-fsdp} -> drop
        text = re.sub(r"\{#[\w-]+\}", "", text)

        # Collapse excess blank lines / trailing whitespace per line
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()