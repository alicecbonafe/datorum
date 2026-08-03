import gzip
import io
import tarfile

import pytest
from bs4 import BeautifulSoup

from datorum.exceptions import ScraperException
from datorum.scrapers import (
    ArchiveOrgScraper,
    ArxivHTMLScraper,
    ArxivTeXScraper,
    PlanaltoBRScraper,
)


def test_arxiv_html_scraper(httpserver):

    arxiv_id = "0000.00000"

    html_content = """
        <!DOCTYPE html>
        <html>
        <head><title>Test Article</title></head>
        <body>
            <header><h1>Index Page</h1></header>
            <main>
                <p>This is a test introduction for arXiv HTML scraper.</p>
                <script>var x = "dummyscript"</script>
                <img />
                <math alttext="Delta W" display="inline"><mi mathvariant="normal">Δ</mi></math>
                <math alttext="Delta W" display="block"><mi mathvariant="normal">Δ</mi></math>
                <math><mi mathvariant="normal">Δ</mi></math>
                <a href="#test">link test 1</a>
                <a href="test.html">link test 2</a>
                <a>link test 3</a>
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

    httpserver.expect_request(f"/html/{arxiv_id}v1").respond_with_data(html_content)

    scraper = ArxivHTMLScraper()
    document1 = scraper.extract(httpserver.url_for(f"/abs/{arxiv_id}"))
    document2 = scraper.extract(httpserver.url_for(f"/html/{arxiv_id}v1"))

    assert document1.title == document2.title
    assert document1.metadata == document2.metadata
    assert "arXiv HTML scraper" in document1.body
    assert "author_1" in document1.metadata["authors"]


def test_arxiv_tex_scraper(httpserver):

    arxiv_id = "0000.00000"

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

    httpserver.expect_request(f"/e-print/{arxiv_id}").respond_with_data(tex_content)

    scraper = ArxivTeXScraper()
    result = scraper.extract(httpserver.url_for(f"/abs/{arxiv_id}")).body
    assert "arXiv TeX scraper" in result


def test_arxiv_tex_gzip_fallback(httpserver):
    arxiv_id = "9999.99999"
    raw_tex = b"\\documentclass{article}\\begin{document}Gzipped content\\end{document}"
    gzipped_content = gzip.compress(raw_tex)

    httpserver.expect_request(f"/e-print/{arxiv_id}").respond_with_data(gzipped_content)

    scraper = ArxivTeXScraper()
    doc = scraper.extract(httpserver.url_for(f"/abs/{arxiv_id}"))
    assert "Gzipped content" in doc.body


def test_arxiv_id_fallback():
    arxiv_id = "9999.99999"

    scraper = ArxivHTMLScraper()
    new_arxiv_id = scraper._extract_arxiv_id(f"/dummyurl/{arxiv_id}.pdf/")
    assert new_arxiv_id == arxiv_id


def test_arxiv_tex_unpack_uncompressed_tar():
    # Raw bytes that don't start with the gzip magic number (\x1f\x8b) skip
    # the tarfile-extraction branch entirely and are decoded as a single
    # "main.tex" blob instead - even when they happen to be a real
    # (uncompressed) tar archive. This documents that current behavior.
    tex_content = (
        b"\\documentclass{article}\\begin{document}UncompressedTarBody\\end{document}"
    )
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name="main.tex")
        info.size = len(tex_content)
        tar.addfile(info, io.BytesIO(tex_content))
    raw_bytes = buf.getvalue()

    assert raw_bytes[:2] != b"\x1f\x8b"

    scraper = ArxivTeXScraper()
    result = scraper._unpack(raw_bytes)
    assert "UncompressedTarBody" in result


def test_arxiv_tex_unpack_no_tex_files_raises():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"not tex content"
        info = tarfile.TarInfo(name="readme.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    raw_bytes = buf.getvalue()

    scraper = ArxivTeXScraper()
    with pytest.raises(ValueError):
        scraper._unpack(raw_bytes)


def test_arxiv_tex_unpack_valid_gzip_tar_extracts_tex_member():
    tex_content = (
        b"\\documentclass{article}\\begin{document}RealTarballBody\\end{document}"
    )
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="paper.tex")
        info.size = len(tex_content)
        tar.addfile(info, io.BytesIO(tex_content))

        # A non-.tex member alongside it, to make sure the endswith(".tex")
        # filter still lets the real member through for extraction.
        aux = b"some auxiliary data"
        aux_info = tarfile.TarInfo(name="notes.bib")
        aux_info.size = len(aux)
        tar.addfile(aux_info, io.BytesIO(aux))
    raw_bytes = buf.getvalue()

    assert raw_bytes[:2] == b"\x1f\x8b"

    scraper = ArxivTeXScraper()
    result = scraper._unpack(raw_bytes)
    assert "RealTarballBody" in result


def test_find_main_tex_no_candidates():
    scraper = ArxivTeXScraper()
    tex_files = {
        "short.tex": "short",
        "long.tex": "a much longer piece of content without documentclass",
    }
    result = scraper._find_main_tex(tex_files)
    assert result == "long.tex"


def test_find_main_tex_many_candidates():
    scraper = ArxivTeXScraper()
    tex_files = {
        "chapter.tex": "\\documentclass{article}\\begin{document}chapter body\\end{document}",
        "main.tex": "\\documentclass{article}\\input{chapter}",
    }
    # Both files declare \documentclass, but "chapter" is \input by "main",
    # so it's excluded and "main.tex" is picked as the entry point.
    result = scraper._find_main_tex(tex_files)
    assert result == "main.tex"


def test_find_main_tex_many_candidates_all_included_fallback():
    scraper = ArxivTeXScraper()
    tex_files = {
        "a.tex": "\\documentclass{article}\\input{b}",
        "b.tex": "\\documentclass{article}\\input{a}",
    }
    # Circular references mean every candidate is "included" somewhere, so
    # the method falls back to the first candidate.
    result = scraper._find_main_tex(tex_files)
    assert result == "a.tex"


def test_resolve_inputs_depth_limit():
    scraper = ArxivTeXScraper()
    text = "\\input{a}"
    tex_files = {"a.tex": "\\input{a}"}
    # Depth already past the limit: the text is returned untouched without
    # attempting further substitution.
    result = scraper._resolve_inputs(text, tex_files, depth=11)
    assert result == text


def test_resolve_inputs_replace():
    scraper = ArxivTeXScraper()
    tex_files = {
        "chapter.tex": "Chapter Body",
    }
    text = "Before \\input{chapter} After \\include{missing}"
    result = scraper._resolve_inputs(text, tex_files)
    assert "Chapter Body" in result
    assert "Before" in result and "After" in result
    # A referenced file that isn't present is silently dropped.
    assert "missing" not in result
    assert "\\include" not in result


def test_extract_braced_unbalanced():
    scraper = ArxivTeXScraper()
    text = "\\title{Unbalanced content without closing brace"
    brace_start = text.index("{")
    # No closing brace is ever found, so the method falls through to
    # returning everything after the opening brace.
    result = scraper._extract_braced(text, brace_start)
    assert result == "Unbalanced content without closing brace"


def test_braced_end_unbalanced():
    scraper = ArxivTeXScraper()
    text = "{Unbalanced content"
    # No closing brace, so the scan runs off the end of the string.
    result = scraper._braced_end(text, 0)
    assert result == len(text)


def test_strip_remaining_commands_preserves_math():
    scraper = ArxivTeXScraper()
    text = (
        "Before \\textbf{ignored} $\\alpha + \\beta$ middle "
        "\\command{x} $$\\gamma$$ after"
    )
    result = scraper._strip_remaining_commands(text)
    # Each math span is collected via math_spans.append(...) and stitched
    # back in verbatim, untouched by command stripping.
    assert "$\\alpha + \\beta$" in result
    assert "$$\\gamma$$" in result
    # Non-math commands are still stripped.
    assert "\\textbf" not in result
    assert "\\command" not in result
    assert "ignored" in result


def test_strip_remaining_commands_overlapping_spans_skipped():
    scraper = ArxivTeXScraper()
    text = "Before \\begin{equation}$x$\\end{equation} After \\command{y}"
    result = scraper._strip_remaining_commands(text)
    # The equation-environment span fully contains an inline "$x$" match
    # found by a different pattern. Since the environment span is sorted
    # first (it starts earlier) and consumed first, the inline match's
    # start falls behind the cursor and must be skipped via "continue",
    # leaving the whole environment untouched rather than reprocessed.
    assert "\\begin{equation}$x$\\end{equation}" in result
    assert "Before" in result and "After" in result
    assert "\\command" not in result
    assert "y" in result


def test_archive_org_scraper(httpserver):

    identifier = "article-identifier"
    filename = "Article-File-Name"

    metadata = {
        "metadata": {
            "creator": "Mocked Creator",
        },
        "files": [
            {"name": f"{filename}.pdf"},
            {"name": f"{filename}.epub"},
            {"name": f"{filename}_djvu.txt"},
        ],
    }

    djvu = (
        "Test djvu string for ArchiveOrgScraper"
        "\n\n\n\n"
        "\n\naaa\n\x0c"
        "page\x0cbreak"
        "nobre-\nak"
        "\n\naaa\n\x0cpublic domain google"
        "\n\naaa\n\x0cI"
        "\n\naaa\n\x0c"
        "final line"
        "\n\naaa\n\x0c"
        "\n\naaa\n\x0c"
    )

    httpserver.expect_request(f"/metadata/{identifier}").respond_with_json(metadata)
    httpserver.expect_request(
        f"/download/{identifier}/{filename}_djvu.txt"
    ).respond_with_data(djvu)

    scraper = ArchiveOrgScraper()
    result = scraper.extract(
        httpserver.url_for(f"/details/{identifier}/{filename}/")
    ).body

    assert "djvu string for Arch" in result
    assert "page\n\nbreak" in result
    assert "nobreak" in result
    assert "LLL" not in result


def test_archive_org_missing_metadata(httpserver):
    identifier = "missing-meta-id"

    # 404 the metadata to force the exception block
    httpserver.expect_request(f"/metadata/{identifier}").respond_with_data(
        "Not Found", status=404
    )
    httpserver.expect_request(
        f"/download/{identifier}/{identifier}_djvu.txt"
    ).respond_with_data("Fallback text")

    scraper = ArchiveOrgScraper()
    doc = scraper.extract(httpserver.url_for(f"/details/{identifier}"))

    assert doc.title == identifier
    assert "Fallback text" in doc.body


def test_archive_org_identifier_value_error():
    scraper = ArchiveOrgScraper()
    value_error_ok = False
    try:
        scraper._extract_identifier("dummy_url")
    except ScraperException:
        value_error_ok = True
    assert value_error_ok


def test_planalto_br_scraper(httpserver):

    html_content = """
        <!DOCTYPE html>
        <html>
        <head><title>Lei n° 0.000 - Estatuto dos Testes Unitários</title></head>
        <body>
            <header><h1>Lei n° 0.000 - Estatuto dos Testes Unitários</h1></header>
            <main>
                <div>
                    <script>x=1;</script>
                    <p>Capítulo I - Primeiro Capítulo</p>
                    <p>Art. 1º. Todos os testes são iguais perante a Lei, mas os unitários vem primeiro.</p>
                    <p>Parágrafo único: Lá, lá, lá</p>
                    <p>I - Este inciso deve estar aninhado</p>
                </div>
            </main>
        </body>
        </html>
    """
    httpserver.expect_request("/planalto").respond_with_data(html_content)

    scraper = PlanaltoBRScraper()
    result = scraper.extract(httpserver.url_for("/planalto")).body
    assert "## Capítulo I" in result
    assert "**Art. 1º" in result
    assert "  **Parágrafo único" in result
    assert "    - **I" in result


def test_planalto_br_scraper_edge_cases(httpserver):
    """Targets title fallbacks, list logic, and heading backtracking."""
    html_content = """
        <!DOCTYPE html>
        <html>
        <head></head>
        <body>
            <div class="texto-lei">
                <p></p>
                <p>TÍTULO I</p>
                <p>CAPÍTULO I</p>
                <p>Seção I</p>
                <p>TÍTULO II</p>
                <p>Art. 1º.</p>
                <p>I - Inciso</p>
                <p>a) Alínea</p>
                <p>II - Inciso 2</p>
                <p>Texto plano sem formatação</p>
            </div>
        </body>
        </html>
    """
    httpserver.expect_request("/lei_teste.html").respond_with_data(html_content)

    scraper = PlanaltoBRScraper()
    doc = scraper.extract(httpserver.url_for("/lei_teste.html"))

    # 1. Title fallback since <title> is missing (Line 155)
    assert doc.title == "lei_teste"

    # 2. Heading level adjustment & backtracking logic (Lines 97-105)
    assert "## TÍTULO I" in doc.body
    assert "### CAPÍTULO I" in doc.body
    assert "#### Seção I" in doc.body
    assert "## TÍTULO II" in doc.body

    # 3. Article list branching & backtracking logic (Lines 116-122)
    assert "**Art. 1º**" in doc.body
    assert "  - **I - ** Inciso" in doc.body
    assert "    - **a) ** Alínea" in doc.body
    assert "  - **II - ** Inciso 2" in doc.body

    # 4. Plain text loop catch-all (Lines 84, 127)
    assert "Texto plano sem formatação" in doc.body


def test_planalto_format_device_fallback():
    """Direct invocation to test fallback when a regex string fails internally."""
    scraper = PlanaltoBRScraper()

    # Targets Line 145 where pattern matches as true inside process but fails inner match.
    # While practically gated during loop execution, we directly verify logic response:
    result = scraper._format_device("Format without regex marker", "artigo", 2)
    assert result == "    - Format without regex marker"


def test_planalto_process_elements_empty_text():
    """Targets Line 84: feeds an element that becomes empty after _clean_text."""
    scraper = PlanaltoBRScraper()
    # A string of spaces will pass BS4's existence check but fail _clean_text
    soup = BeautifulSoup("<p>   </p>", "html.parser")
    tag = soup.find("p")
    if tag is not None:
        result = scraper._process_elements([tag])

    assert result == []


def test_planalto_heading_backtrack_middle(httpserver):
    """Targets Line 105: forces a backtrack to a middle-tier heading."""
    html_content = """
        <!DOCTYPE html>
        <html><body><div class="texto-lei">
            <p>TÍTULO I</p>
            <p>CAPÍTULO I</p>
            <p>Seção I</p>
            <p>CAPÍTULO II</p>
        </div></body></html>
    """
    httpserver.expect_request("/backtrack.html").respond_with_data(html_content)
    scraper = PlanaltoBRScraper()
    doc = scraper.extract(httpserver.url_for("/backtrack.html"))

    # Verifies the backtrack loops past Título and breaks at Capítulo, iterating current_heading_level
    assert "## TÍTULO I" in doc.body
    assert "### CAPÍTULO I" in doc.body
    assert "#### Seção I" in doc.body
    assert "### CAPÍTULO II" in doc.body
