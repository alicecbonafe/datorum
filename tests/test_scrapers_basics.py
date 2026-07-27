from typing import Any

import pytest

from datorum.scrapers import (
    BaseScraper,
    BasicHTMLScraper,
    IndexedHTMLScraper,
    ScrapedDocument,
)


class ConcreteScraper(BaseScraper):
    def extract(self, url: str, **kwargs: Any) -> ScrapedDocument:
        return ScrapedDocument(
            title=f"Scraped: {url}",
            license="Apache-2.0",
            source=url,
            metadata={"authors": "Person, Mocked at al."},
            body="Mocked response.",
        )


def test_base_scraper_interface():
    scraper = ConcreteScraper()
    result = scraper.extract("https://example.com")
    assert result.title == "Scraped: https://example.com"


def test_base_scraper_scrape_from(tmp_path):
    scraper = ConcreteScraper()
    target_file = tmp_path / "output.md"

    # Test scrap_from which calls _write and _render
    doc = scraper.scrape_from("https://example.com", target_file)

    assert doc.title == "Scraped: https://example.com"
    assert target_file.exists()
    content = target_file.read_text(encoding="utf-8")
    assert "# Scraped: https://example.com" in content
    assert "Mocked response." in content


def test_base_scraper_sanitize():
    scraper = ConcreteScraper()

    # Inject invisible characters, weird linebreaks, and non-breaking spaces
    dirty_text = "Line 1\r\nLine 2\u2028Line 3\ufeff\u00a0Space"
    clean_text = scraper._sanitize(dirty_text)

    assert "\r" not in clean_text
    assert "\u2028" not in clean_text
    assert "\ufeff" not in clean_text
    assert "\u00a0" not in clean_text
    assert "Line 1\nLine 2\nLine 3 Space" in clean_text


@pytest.fixture
def sample_contents():
    signature = "findme"
    return {
        "signature": signature,
        "index": f"""
            <!DOCTYPE html>
            <html>
            <head><title>Test Article</title></head>
            <body>
                <header><h1>Index Page</h1></header>
                <main>
                    <p><a href="contents.htm">{signature}_index</a></p>
                    <p><a href="contents2.htm">nomain</a></p>
                    <p><a href="../otherfolder/mustignore.htm">Don't scrape me!</a></p>
                    <p><a href="contents2.htm">You again?!?</a></p>
                    <p>Created by Mocked Person</p>
                </main>
                <footer>Copyright 2026</footer>
            </body>
            </html>
        """,
        "contents": f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Test Article</title>
                <meta name="author" content="Mocked Person">
            </head>
            <body>
                <header><h1>Contents Page</h1></header>
                <p id="main">
                    <h2>The Article</h2>
                    <p>This is paragraph 1 with details.</p>
                    <p>This is paragraph 2 with data.</p>
                    <p><a name="sig"><i>{signature}_contents</i></a></p>
                </p>
                <footer>Copyright 2026</footer>
            </body>
            </html>
        """,
        "contents-2": f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Test Article (no main)</title>
                <meta name="author" content="Mocked Person">
            </head>
            <body>
                <h1>Contents Page</h1>
                <p>This is paragraph 1 with details.</p>
                <p>This is paragraph 2 with data.</p>
                <p><a name="sig"><i>{signature}_contents</i></a></p>
            </body>
            </html>
        """,
    }


def test_basic_html_scraper(httpserver, sample_contents):

    httpserver.expect_request("/index").respond_with_data(sample_contents["index"])

    scraper = BasicHTMLScraper()
    document = scraper.extract(httpserver.url_for("/index")).body

    assert f"{sample_contents['signature']}_index" in document
    assert f"{sample_contents['signature']}_contents" not in document


def test_indexed_html_scraper(httpserver, sample_contents):

    httpserver.expect_request("/index").respond_with_data(sample_contents["index"])

    httpserver.expect_request("/contents.htm").respond_with_data(
        sample_contents["contents"]
    )

    httpserver.expect_request("/contents2.htm").respond_with_data(
        sample_contents["contents-2"]
    )

    scraper = IndexedHTMLScraper()
    document = scraper.extract(httpserver.url_for("/index")).body

    assert f"{sample_contents['signature']}_index" in document
    assert f"{sample_contents['signature']}_contents" in document


def test_indexed_html_scraper_http_error(httpserver, sample_contents):
    httpserver.expect_request("/index").respond_with_data(sample_contents["index"])
    httpserver.expect_request("/contents.htm").respond_with_data(
        "Not Found", status=404
    )

    scraper = IndexedHTMLScraper()
    document = scraper.extract(httpserver.url_for("/index")).body

    # The index should be parsed, but the contents skipped without crashing
    assert f"{sample_contents['signature']}_index" in document
