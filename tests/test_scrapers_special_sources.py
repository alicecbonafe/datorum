import pytest

from datorum.scrapers import (
    ArxivHTMLScraper,
    ArxivTeXScraper,
    ArchiveOrgScraper,
    PlanaltoBRScraper,
)


def test_arxiv_html_scraper(httpserver):

    arxiv_id = '0000.00000'

    html_content =  f"""
        <!DOCTYPE html>
        <html>
        <head><title>Test Article</title></head>
        <body>
            <header><h1>Index Page</h1></header>
            <main>
                <p>This is a test introduction for arXiv HTML scraper.</p>
            </main>
            <footer>
                <div class="ltx_authors">
                    <span class="ltx_personname">author_1</span>
                    <span class="ltx_personname">author_2</span>
                </div>
            </footer>
        </body>
        </html>
    """

    httpserver.expect_request(f"/html/{arxiv_id}v1").respond_with_data(
        html_content)

    scraper = ArxivHTMLScraper()
    document1 = scraper.extract(httpserver.url_for(f'/abs/{arxiv_id}'))
    document2 = scraper.extract(httpserver.url_for(f'/html/{arxiv_id}v1'))

    assert document1.title == document2.title
    assert document1.metadata == document2.metadata
    assert "arXiv HTML scraper" in document1.body
    assert "author_1" in document1.metadata['authors']


def test_arxiv_tex_scraper(httpserver):

    arxiv_id = '0000.00000'

    tex_content = r"""
    \documentclass{article}
    \title{Sample LaTeX Document}
    \author{Author Name}
    \begin{document}
    \maketitle
    \section{Introduction}
    This is a test introduction for arXiv TeX scraper.
    \end{document}
    """

    httpserver.expect_request(f"/e-print/{arxiv_id}").respond_with_data(
        tex_content)

    scraper = ArxivTeXScraper()
    result = scraper.extract(httpserver.url_for(f"/abs/{arxiv_id}")).body
    assert "arXiv TeX scraper" in result


def test_archive_org_scraper(httpserver):

    identifier = 'article-identifier'
    filename = 'Article-File-Name'

    metadata = {
        "files": [
            { "name": f"{filename}.pdf" },
            { "name": f"{filename}.epub" },
            { "name": f"{filename}_djvu.txt" },
        ]
    }

    djvu =  (
        "Test djvu string for ArchiveOrgScraper"
        "page\x0cbreak"
        "nobre-\nak"
    )

    httpserver.expect_request(f"/metadata/{identifier}").respond_with_json(
        metadata)
    httpserver.expect_request(f"/download/{identifier}/{filename}_djvu.txt").respond_with_data(
        djvu
    )

    scraper = ArchiveOrgScraper()
    result = scraper.extract(httpserver.url_for(f'/details/{identifier}/{filename}/')).body

    assert "djvu string for Arch" in result
    assert "page\n\nbreak" in result
    assert "nobreak" in result
    assert "LLL" not in result


def test_planalto_br_scraper(httpserver):

    html_content =  f"""
        <!DOCTYPE html>
        <html>
        <head><title>Lei n° 0.000 - Estatuto dos Testes Unitários</title></head>
        <body>
            <header><h1>Lei n° 0.000 - Estatuto dos Testes Unitários</h1></header>
            <main>
                <p>Capítulo I - Primeiro Capítulo</p>
                <p>Art. 1º. Todos os testes são iguais perante a Lei, mas os unitários vem primeiro.</p>
                <p>Parágrafo único: Lá, lá, lá</p>
                <p>I - Este inciso deve estar aninhado</p>
            </main>
        </body>
        </html>
    """
    httpserver.expect_request("/planalto").respond_with_data(
        html_content
    )

    scraper = PlanaltoBRScraper()
    result = scraper.extract(httpserver.url_for('/planalto')).body
    assert "## Capítulo I" in result
    assert "**Art. 1º" in result
    assert "  **Parágrafo único" in result
    assert "    - **I" in result

