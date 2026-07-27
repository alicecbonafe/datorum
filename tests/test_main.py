from typing import Tuple, Any, Dict
import sys
from pathlib import Path

import pytest

from datorum import GeneralConfig
from datorum.cli import app
from datorum.exceptions import ScraperException, ChunkerException
from datorum.providers.inference import InferenceProvider
from datorum.scrapers import BaseScraper, ScrapedDocument, registry

DOMAINS_YAML = """\
id: d
domains:
  - id: t1
    sources:
      - id: s001
        url: https://example.com
        source_file: source.md
        chunks_file: chunks.json
        scraper: FakeScraper
        scraper_args:
          title: Test
      - id: s002
        url: https://example.com
        source_file: source.md
        chunks_file: chunks.json
        scraper_args:
          title: Test
      - id: s003
        source_file: source.md
        chunks_file: chunks.json
        scraper: FakeScraper
        scraper_args:
          title: Test
"""


class FakeScraper(BaseScraper):
    last_call: Tuple[str, Dict[str, Any]] = ("", {})

    def extract(self, url, **kwargs):
        FakeScraper.last_call = (url, kwargs)
        return ScrapedDocument(
            title="Example Document",
            license="Apache-2.0",
            source=url,
            metadata={**kwargs},
            body="scraped content",
        )


class FakeProvider:
    last_prompt = None

    def generate(self, request):
        FakeProvider.last_prompt = request.user_prompt
        return '{"title": "Test", "tags": [], "chunks": []}'


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    (tmp_path / "domains.yml").write_text(DOMAINS_YAML, encoding="utf-8")
    (tmp_path / "instructions.md").write_text(
        "You are a chunking assistant.", encoding="utf-8"
    )
    return tmp_path


def test_main_scrape_command(data_dir, monkeypatch):
    registry["FakeScraper"] = FakeScraper
    monkeypatch.setattr(
        sys, "argv", ["datorum", "--data-path", str(data_dir), "scrape", "t1.s001"]
    )

    app()

    url, kwargs = FakeScraper.last_call
    assert url == "https://example.com"
    assert kwargs == {"title": "Test"}

    path = data_dir / "sources" / "t1" / "s001" / "source.md"
    assert "scraped content" in path.read_text(encoding="utf-8")


def test_main_chunk_command(data_dir, monkeypatch):
    GeneralConfig["CHUNKER_MODEL"] = "test-model"

    source_dir = data_dir / "sources" / "t1" / "s001"
    source_dir.mkdir(parents=True)
    (source_dir / "source.md").write_text("raw scraped text", encoding="utf-8")

    monkeypatch.setattr(
        InferenceProvider, "load", classmethod(lambda cls, name: FakeProvider())
    )
    monkeypatch.setattr(
        sys, "argv", ["datorum", "--data-path", str(data_dir), "chunk", "t1.s001"]
    )

    app()

    assert FakeProvider.last_prompt == "raw scraped text"

    chunks_path = data_dir / "chunks" / "t1" / "s001" / "chunks.json"
    assert (
        chunks_path.read_text(encoding="utf-8")
        == '{"title": "Test", "tags": [], "chunks": []}'
    )


def test_exceptions(data_dir, monkeypatch):

    # KeyError

    monkeypatch.setattr(
        sys, "argv", ["datorum", "--data-path", str(data_dir), "chunk", "missing.s001"]
    )
    with pytest.raises(KeyError):
        app()

    monkeypatch.setattr(
        sys, "argv", ["datorum", "--data-path", str(data_dir), "chunk", "t1.missing"]
    )
    with pytest.raises(KeyError):
        app()

    # ScraperException

    registry["FakeScraper"] = FakeScraper

    monkeypatch.setattr(
        sys, "argv", ["datorum", "--data-path", str(data_dir), "scrape", "t1.s002"]
    )
    error_ok = False
    try:
        app()
    except ScraperException:
        error_ok = True
    assert error_ok

    monkeypatch.setattr(
        sys, "argv", ["datorum", "--data-path", str(data_dir), "scrape", "t1.s003"]
    )
    error_ok = False
    try:
        app()
    except ScraperException:
        error_ok = True
    assert error_ok

    # ChunkerException

    GeneralConfig["CHUNKER_MODEL"] = ""
    GeneralConfig["MODEL"] = ""

    source_dir = data_dir / "sources" / "t1" / "s001"
    source_dir.mkdir(parents=True)
    (source_dir / "source.md").write_text("raw scraped text", encoding="utf-8")

    monkeypatch.setattr(
        InferenceProvider, "load", classmethod(lambda cls, name: FakeProvider())
    )
    monkeypatch.setattr(
        sys, "argv", ["datorum", "--data-path", str(data_dir), "chunk", "t1.s001"]
    )

    error_ok = False
    try:
        app()
    except ChunkerException:
        error_ok = True
    assert error_ok
