import sys
from pathlib import Path

import pytest

from datorum import GeneralConfig
from datorum.cli import app
from datorum.scrapers import registry
from datorum.providers.inference import InferenceProvider


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
"""


class FakeScraper:
    last_call = None

    def scrape_from(self, url, path, **kwargs):
        FakeScraper.last_call = (url, path, kwargs)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("scraped content", encoding='utf-8')


class FakeProvider:
    last_prompt = None

    def generate(self, request):
        FakeProvider.last_prompt = request.user_prompt
        return '{"title": "Test", "tags": [], "chunks": []}'


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    (tmp_path / 'domains.yml').write_text(DOMAINS_YAML, encoding='utf-8')
    (tmp_path / 'instructions.md').write_text('You are a chunking assistant.', encoding='utf-8')
    return tmp_path


def test_main_scrape_command(data_dir, monkeypatch):
    registry['FakeScraper'] = FakeScraper
    monkeypatch.setattr(sys, 'argv', [
        'datorum', '--data-path', str(data_dir), 'scrape', 't1.s001'
    ])

    app()

    url, path, kwargs = FakeScraper.last_call
    assert url == 'https://example.com'
    assert path == data_dir / 'sources' / 't1' / 's001' / 'source.md'
    assert kwargs == {'title': 'Test'}
    assert path.read_text(encoding='utf-8') == 'scraped content'


def test_main_chunk_command(data_dir, monkeypatch):
    GeneralConfig['CHUNKER_MODEL'] = 'test-model'

    source_dir = data_dir / 'sources' / 't1' / 's001'
    source_dir.mkdir(parents=True)
    (source_dir / 'source.md').write_text('raw scraped text', encoding='utf-8')

    monkeypatch.setattr(InferenceProvider, 'load', classmethod(lambda cls, name: FakeProvider()))
    monkeypatch.setattr(sys, 'argv', [
        'datorum', '--data-path', str(data_dir), 'chunk', 't1.s001'
    ])

    app()

    assert FakeProvider.last_prompt == 'raw scraped text'

    chunks_path = data_dir / 'chunks' / 't1' / 's001' / 'chunks.json'
    assert chunks_path.read_text(encoding='utf-8') == '{"title": "Test", "tags": [], "chunks": []}'


def test_exceptions(data_dir, monkeypatch):
    monkeypatch.setattr(sys, 'argv', [
        'datorum', '--data-path', str(data_dir), 'chunk', 'missing.s001'
    ])
    with pytest.raises(KeyError):
        app()

    monkeypatch.setattr(sys, 'argv', [
        'datorum', '--data-path', str(data_dir), 'chunk', 't1.missing'
    ])
    with pytest.raises(KeyError):
        app()