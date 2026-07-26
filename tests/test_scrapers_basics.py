import pytest

from datorum.scrapers import (
    ScrapedDocument,
    BaseScraper,
    BasicHTMLScraper,
    IndexedHTMLScraper,
)


class ConcreteScraper(BaseScraper):
    def extract(self, url: str) -> ScrapedDocument:
        return ScrapedDocument(
            title = f"Scraped: {url}",
            license = 'Apache-2.0',
            source = url,
            body = 'Mocked response.'
        )


def test_base_scraper_interface():
    scraper = ConcreteScraper()
    result = scraper.extract("https://example.com")
    assert result.title == "Scraped: https://example.com"


@pytest.fixture
def sample_contents():
    signature = 'findme'
    return {
        'signature': signature,
        'index': f"""
            <!DOCTYPE html>
            <html>
            <head><title>Test Article</title></head>
            <body>
                <header><h1>Index Page</h1></header>
                <main>
                    <p><a href="contents.htm">{signature}_index</a></p>
                </main>
                <footer>Copyright 2026</footer>
            </body>
            </html>
        """,
        'contents': f"""
            <!DOCTYPE html>
            <html>
            <head><title>Test Article</title></head>
            <body>
                <header><h1>Contents Page</h1></header>
                <main>
                    <p>This is paragraph 1 with details.</p>
                    <p>This is paragraph 2 with data.</p>
                    <p><i>{signature}_contents</i></p>
                </main>
                <footer>Copyright 2026</footer>
            </body>
            </html>
        """
    }


def test_basic_html_scraper(httpserver, sample_contents):

    httpserver.expect_request("/index").respond_with_data(
        sample_contents['index'])

    scraper = BasicHTMLScraper()
    document = scraper.extract(httpserver.url_for('/index')).body

    assert f"{sample_contents['signature']}_index" in document
    assert f"{sample_contents['signature']}_contents" not in document


def test_indexed_html_scraper(httpserver, sample_contents):

    httpserver.expect_request("/index").respond_with_data(
        sample_contents['index'])

    httpserver.expect_request("/contents.htm").respond_with_data(
        sample_contents['contents'])

    scraper = IndexedHTMLScraper()
    document = scraper.extract(httpserver.url_for('/index')).body

    assert f"{sample_contents['signature']}_index" in document
    assert f"{sample_contents['signature']}_contents" in document
