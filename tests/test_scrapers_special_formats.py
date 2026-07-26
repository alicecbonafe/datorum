import pytest

from datorum.scrapers import (
    MDXScraper,
    QMDScraper,
)


def test_mdx_scraper(httpserver):

    toctree_yaml = """
- title: Getting Started
  local: index
- title: Guides
  sections:
    - title: Advanced Usage
      local: guides/advanced
    - title: Redundant Reference
      local: guides/advanced
    - title: Broken Link
      local: guides/notfound
"""

    index_md = (
        "<!-- Copyright 2026 -->\n"
        "Welcome to the docs.\n\n"
        "<Tip>\n"
        "Remember to save your work.\n"
        "</Tip>\n"
    )

    advanced_md = (
        'See the <a href="https://example.com/ref">reference</a> for details.\n'
    )

    httpserver.expect_request("/folder/_toctree.yml").respond_with_data(toctree_yaml)
    httpserver.expect_request("/folder/index.md").respond_with_data(index_md)
    httpserver.expect_request("/folder/guides/advanced.md").respond_with_data(advanced_md)

    scraper = MDXScraper()
    document = scraper.extract(
        httpserver.url_for("/folder"),
        title="Test Docs",
        license="Apache-2.0",
    )

    # section/page headings, at the levels implied by toctree nesting
    assert "# Getting Started" in document.body
    assert "# Guides" in document.body
    assert "## Advanced Usage" in document.body

    # plain content survives
    assert "Welcome to the docs." in document.body

    # leading copyright comment is stripped
    assert "Copyright 2026" not in document.body

    # <Tip> becomes a blockquote-style note
    assert "> **Note:** Remember to save your work." in document.body

    # raw <a href> is converted to a markdown link
    assert "[reference](https://example.com/ref)" in document.body


def test_qmd_scraper(httpserver):

    quarto_yaml = """
website:
  sidebar:
    contents:
      - text: Introduction
        href: intro.qmd
      - section: Guides
        contents:
          - guides/setup.qmd
"""

    intro_qmd = (
        "---\n"
        "title: Intro\n"
        "---\n\n"
        "Welcome! {{< video https://example.com/vid >}}\n\n"
        "::: {.callout-note}\n"
        "Keep this in mind.\n"
        ":::\n\n"
        "See [setup](guides/setup.qmd) for more. {#sec-intro}\n"
    )

    setup_qmd = "Follow these steps.\n"

    httpserver.expect_request("/_quarto.yml").respond_with_data(quarto_yaml)
    httpserver.expect_request("/intro.qmd").respond_with_data(intro_qmd)
    httpserver.expect_request("/guides/setup.qmd").respond_with_data(setup_qmd)

    scraper = QMDScraper()
    document = scraper.extract(
        httpserver.url_for("/"),
        title="Test Project",
        license="Apache-2.0",
    )

    # QMDScraper is domain independent: with no owner/repo given, the
    # source is the base url itself rather than a github.com link
    assert document.source == httpserver.url_for("/")

    # section/page headings, at the levels implied by sidebar nesting
    assert "# Introduction" in document.body
    assert "# Guides" in document.body
    assert "## Setup" in document.body

    # plain content survives
    assert "Welcome!" in document.body
    assert "Follow these steps." in document.body

    # YAML front matter is stripped
    assert "title: Intro" not in document.body

    # video shortcode is dropped
    assert "{{<" not in document.body

    # callout div becomes a blockquote-style note
    assert "> **Note:** Keep this in mind." in document.body

    # cross-ref to another .qmd file keeps link text, drops the path
    assert "See setup for more." in document.body
    assert "guides/setup.qmd" not in document.body

    # section anchor is dropped
    assert "{#sec-intro}" not in document.body


def test_qmd_scraper_github_source(httpserver):
    """owner/repo/branch still work as a GitHub-specific convenience: the
    base url they build from is ignored, and `source` becomes a github.com
    link instead of the base url."""

    quarto_yaml = """
website:
  sidebar:
    contents:
      - text: Readme
        href: README.qmd
"""

    httpserver.expect_request("/acme/docs/main/_quarto.yml").respond_with_data(quarto_yaml)
    httpserver.expect_request("/acme/docs/main/README.qmd").respond_with_data(
        "Hello.\n"
    )

    scraper = QMDScraper()
    scraper.GITHUB_RAW_BASE = httpserver.url_for("/")[:-1]  # strip trailing slash

    document = scraper.extract(
        "https://ignored.example/",
        title="Test Project",
        license="Apache-2.0",
        owner="acme",
        repo="docs",
        branch="main",
    )

    assert document.source == "https://github.com/acme/docs"
    assert "Hello." in document.body


def test_mdx_scraper_clean_mdx_edge_cases():
    """Targets MDX code protection, HTML stripping, and autodoc replacements."""
    scraper = MDXScraper()
    raw_text = (
        "[[autodoc]] datorum.models.Document\n"
        "    - all\n"
        "    - method\n"
        "`<|endoftext|>`\n"
        "```python\n<code>\n```\n"
        "<div><img src='decorative.png'/></div>\n"
        "<iframe src='embed'></iframe>\n"
        "<youtube src='vid'></youtube>\n"
        "Line<br/>Break\n"
        "<p>Paragraph Container</p>\n"
        "<p>Other Paragraph</p>\n"
    )
    
    cleaned = scraper._clean_mdx(raw_text)
    
    # 1. Autodoc replacements (Lines 105-106)
    assert "API reference: `datorum.models.Document`" in cleaned
    assert "- all" not in cleaned
    assert "- method" not in cleaned
    
    # 2. Code protection & restore (Lines 134-137, 179)
    assert "`<|endoftext|>`" in cleaned
    assert "<code>" in cleaned
    
    # 3. HTML stripping (Lines 154, 157, 167, 172)
    assert "img" not in cleaned
    assert "iframe" not in cleaned
    assert "youtube" not in cleaned
    assert "Line\nBreak" in cleaned
    assert "Paragraph Container\n\n" in cleaned


def test_qmd_scraper_edge_cases(httpserver):
    """Targets book configuration, GitHub token, duplicated files, HTTP errors, and trailing slashes."""
    quarto_yaml = """
book:
  chapters:
    - part: Part 1
      contents:
        - ch1.qmd
        - ch1.qmd
        - ch2.qmd
    """
    ch1_qmd = "Chapter 1\n{{< include _partial.qmd >}}\n{{< include _missing.qmd >}}"
    partial_qmd = "Partial content"
    
    httpserver.expect_request("/project/_quarto.yml").respond_with_data(quarto_yaml)
    httpserver.expect_request("/project/ch1.qmd").respond_with_data(ch1_qmd)
    httpserver.expect_request("/project/_partial.qmd").respond_with_data(partial_qmd)
    # HTTP Error endpoints (Lines 72-74, 196-202)
    httpserver.expect_request("/project/_missing.qmd").respond_with_data("Not found", status=404)
    httpserver.expect_request("/project/ch2.qmd").respond_with_data("Not found", status=404)

    scraper = QMDScraper()
    doc = scraper.extract(
        httpserver.url_for("/project"),  # No trailing slash (Line 95)
        title="Book",
        license="MIT",
        github_token="secret-token" # Token authorization (Line 41)
    )

    assert scraper.session.headers['Authorization'] == "Bearer secret-token"
    assert doc.body.count("Chapter 1") == 1  # Duplicates skipped (Line 67)
    assert "Partial content" in doc.body
    assert "(missing include: `_missing.qmd`)" in doc.body
    assert "ch2.qmd" not in doc.body


def test_qmd_scraper_validation_errors():
    """Targets structural validation errors when parsing."""
    scraper = QMDScraper()
    
    # Missing website/book config (Lines 142, 145-149)
    with pytest.raises(ValueError, match="No website.sidebar or book.chapters"):
        scraper._sidebar_entries({"other_config": "values"})
        
    # Glob pattern without owner/repo (Lines 114-128)
    with pytest.raises(ValueError, match="listing is only available for GitHub repos"):
        list(scraper._flatten_sidebar(["docs/*"]))


def test_qmd_scraper_github_glob(httpserver):
    """Targets GitHub API directory listing and glob expansion."""
    quarto_yaml = """
website:
  sidebar:
    contents:
      - section: Docs
        contents: docs/*
    """
    
    api_resp = [
        {"type": "file", "name": "a.qmd", "path": "docs/a.qmd"},
        {"type": "dir", "name": "skip", "path": "docs/skip"},
        {"type": "file", "name": "b.txt", "path": "docs/b.txt"}
    ]
    
    # Configure exact mock paths for glob fetching (Lines 161-162, 179)
    httpserver.expect_request("/acme/repo/main/_quarto.yml").respond_with_data(quarto_yaml)
    httpserver.expect_request("/api.github.com/repos/acme/repo/contents/docs").respond_with_json(api_resp)
    httpserver.expect_request("/acme/repo/main/docs/a.qmd").respond_with_data("Glob content loaded.")
    
    scraper = QMDScraper()
    scraper.GITHUB_RAW_BASE = httpserver.url_for("/")[:-1]
    scraper.GITHUB_API_CONTENTS = httpserver.url_for("/api.github.com/repos/{owner}/{repo}/contents/{path}")
    
    doc = scraper.extract(
        "https://ignored",
        title="Test",
        license="MIT",
        owner="acme",
        repo="repo",
        branch="main"
    )
    
    assert "Glob content loaded." in doc.body


def test_qmd_scraper_sidebar_list():
    """Website sidebar provided as a list instead of a dict."""
    scraper = QMDScraper()
    
    # Test when sidebar is a populated list
    quarto_yaml_list = {
        "website": {
            "sidebar": [
                {"contents": ["intro.qmd"]}
            ]
        }
    }
    entries = scraper._sidebar_entries(quarto_yaml_list)
    assert entries == ["intro.qmd"]

    # Test when sidebar is an empty list
    quarto_yaml_empty = {
        "website": {
            "sidebar": []
        }
    }
    entries_empty = scraper._sidebar_entries(quarto_yaml_empty)
    assert entries_empty == []
