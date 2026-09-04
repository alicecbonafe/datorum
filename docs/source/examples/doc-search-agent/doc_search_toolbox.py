"""Toolbox for the "Doc Search Agent" tutorial."""

from pathlib import Path
import re
from typing import Any

import datorum

@datorum.toolbox(name="doc_search")
class DocSearchToolbox:
    """Search tools for agent use.

    This toolbox is part of "Doc Search Agent" tutorial. It's meant to be
    called by the searcher agent to prepare context to the answerer agent.

    Bindable fields
    ---------------

    * ``domain``: Points at a folder of documents to search.
    * ``interactive``: Contains HITL interaction, with a user-facing
      selection checklist, represented by the ``files`` key in the
      frontmatter, and the user question, within the markdown body.
    """

    domain: Path | None = datorum.ContextField(
        context_bind_type="domain-path",
        required=True,
    )
    interactive: datorum.MarkdownDocument | None = datorum.ContextField(
        context_bind_type="model",
        required=True,
    )

    def _enabled_files(self) -> list[str]:
        files = self.interactive.frontmatter.get("files", {}) \
            if self.interactive.frontmatter else {}
        return [name for name, selected in files.items() if selected]

    def _scan(self, matcher, max_results: int = 5, chunk_size: int = 512) -> dict[str, Any]:
        enabled = self._enabled_files()
        if not enabled:
            return {
                "total_matches": 0,
                "files_matched": [],
                "results": {},
                "hint": "No files are enabled for search. Ask the user to select files first."
            }
        
        results: dict[str, list[str]] = {}
        total = 0
        for name in enabled:
            path = self.domain / name
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            n = len(content)
            for start, end in matcher(content):
                if 0 < max_results <= total:
                    break
                query_len = end - start
                effective = max(chunk_size, query_len)
                pad = effective - query_len
                left, right = pad // 2, pad - pad // 2
                c_start, c_end = start - left, end + right
                if c_start < 0:
                    c_end, c_start = min(n, c_end - c_start), 0
                if c_end > n:
                    c_start, c_end = max(0, c_start - (c_end - n)), n
                results.setdefault(name, []).append(content[c_start:c_end])
                total += 1

            if 0 < max_results <= total:
                break

        if total == 0:
            return {
                "total_matches": 0,
                "files_matched": [],
                "results": {},
                "hint": "No matches. Try a broader or different terms."
            }

        return {
            "total_matches": total,
            "files_matched": [*results.keys()],
            "results": results,
        }

    @datorum.tool()
    def keyword_search(self, keywords: list[str], case_sensitive: bool = False) -> dict[str, Any]:
        """Find text containing any of the given plain-text keywords or phrases.

        Use this for most searches. Pass whole or short phrases exactly as
        they're expected to appear in the text. Since regex and wildcards are
        not recognized, nothing needs escaping.

        Example: keyword_search(keywords=["refund policy", "return window"])

        :param keywords: A list with one or more literal words/phrases to look for.
            Only files containing at least one of these keywords will be included in
            the results.
        :type keywords: list[str]
        :param case_sensitive: If False (default), matching ignores case.
        :type case_sensitive: bool
        """
        if not keywords:
            return {
                "total_matches": 0,
                "files_matched": [],
                "results": {},
                "hint": "Please provide at least one keyword",
            }

        def matcher(content: str):
            haystack = content if case_sensitive else content.lower()
            for needle in (keywords if case_sensitive else [k.lower() for k in keywords]):
                if not needle:
                    continue
                start = 0
                idx = haystack.find(needle, start)
                while idx != -1:
                    yield idx, idx + len(needle)
                    start = idx + len(needle)
                    idx = haystack.find(needle, start)

        response = self._scan(matcher)
        response["query"] = keywords
        return response
    
    @datorum.tool()
    def regex_search(self, patterns: list[str], case_sensitive: bool = False) -> dict[str, Any]:
        """Find text matching any of the given regular expressions.

        Only use this when keyword_search isn't precise enough -- e.g. to
        match a numeric range or a word boundary.

        Example: regex_search(patterns=["error code \\d+", "failed with status"])

        :param patterns: A list with one or more regex patterns to look for.
            Only files matching at least one of these patterns will be included
            in the results.
        :type patterns: list[str]
        :param case_sensitive: If False (default), matching ignores case.
        :type case_sensitive: bool
        """
        if not patterns:
            return {
                "total_matches": 0,
                "files_matched": [],
                "results": {},
                "hint": "Please provide at least one pattern."
            }

        flags = 0 if case_sensitive else re.IGNORECASE
        compiled = []
        for p in patterns:
            try:
                compiled.append(re.compile(p, flags))
            except re.error as e:
                return {
                    "total_matches": 0,
                    "files_matched": [],
                    "results": {},
                    "hint": f"Invalid pattern '{p}': {e}",
                }

        def matcher(content: str):
            for regex in compiled:
                for m in regex.finditer(content):
                    yield m.start(), m.end()

        response = self._scan(matcher)
        response["query"] = patterns
        return response
