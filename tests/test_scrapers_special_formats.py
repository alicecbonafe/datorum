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

    httpserver.expect_request("/_toctree.yml").respond_with_data(toctree_yaml)
    httpserver.expect_request("/index.md").respond_with_data(index_md)
    httpserver.expect_request("/guides/advanced.md").respond_with_data(advanced_md)

    scraper = MDXScraper()
    document = scraper.extract(
        httpserver.url_for("/"),
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