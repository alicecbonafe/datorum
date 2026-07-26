import json
import sys
from unittest.mock import patch, mock_open, MagicMock
import pytest
from pathlib import Path

from datorum.cli import app
from datorum import GeneralConfig

@pytest.fixture
def mock_domains_data():
    return [{
        "id": "d",
        "topics": [{
            "id": "d-t1",
            "sources": [{
                "id": "d-t1-s001",
                "slug": "test-source",
                "scraper": "BasicHTMLScraper",
                "url": "https://example.com",
                "source_file": "source.md",
                "chunks_file": "chunks.json",
                "scraper_args": {"title": "Test"}
            }]
        }]
    }]

@patch("datorum.cli.registry")
@patch("pathlib.Path.open", new_callable=mock_open, read_data="mocked content")
@patch("json.load")
def test_main_scrape_command(mock_json_load, mock_file, mock_registry, mock_domains_data):
    mock_json_load.return_value = mock_domains_data
    
    # Mock the scraper
    mock_scraper_instance = MagicMock()
    mock_registry.__getitem__.return_value = lambda: mock_scraper_instance

    with patch.object(sys, "argv", ["datorum", "scrape", "d-t1-s001"]):
        app()
        
    mock_scraper_instance.scrape_from.assert_called_once()

@patch("datorum.cli.InferenceProvider")
@patch("pathlib.Path.open", new_callable=mock_open, read_data="mocked instructions")
@patch("json.load")
def test_main_chunk_command(mock_json_load, mock_file, mock_provider, mock_domains_data):
    mock_json_load.return_value = mock_domains_data
    
    # Mock inference generation
    mock_instance = MagicMock()
    mock_instance.generate.return_value = '{"title": "Test", "chunks": []}'
    mock_provider.load.return_value = mock_instance

    with patch.object(sys, "argv", ["datorum", "chunk", "d-t1-s001"]):
        app()
        
    mock_instance.generate.assert_called_once()

@patch("json.load")
def test_exceptions(mock_json_load, mock_domains_data):
    mock_json_load.return_value = mock_domains_data

    domain_exception = False
    try:
        with patch.object(sys, "argv", ["datorum", "chunk", "f-t1-s001"]):
            app()
    except Exception as e:
        assert str(e) == 'Domain not found: f'
        domain_exception = True
    assert domain_exception

    topic_exception = False
    try:
        with patch.object(sys, "argv", ["datorum", "chunk", "d-t2-s001"]):
            app()
    except Exception as e:
        assert str(e) == 'Topic not found: d-t2'
        topic_exception = True
    assert topic_exception

    source_exception = False
    try:
        with patch.object(sys, "argv", ["datorum", "chunk", "d-t1-u001"]):
            app()
    except Exception as e:
        assert str(e) == 'Source not found: d-t1-u001'
        source_exception = True
    assert source_exception
