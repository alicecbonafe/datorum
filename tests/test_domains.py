from pathlib import Path

import pytest

from datorum.domains import DomainCollection


def test_persistence(tmp_path: Path):
    domains_file = tmp_path / 'domains.yml'

    id = 'test'
    name = 'Test Collection'
    description = 'This is a test.'

    collection = DomainCollection(id=id, name=name, description=description)
    collection.save(domains_file)

    with domains_file.open('r', encoding='utf-8') as f:
        file_data = f.read()
    assert 0 <= file_data.find(f'id: {id}')
    assert 0 <= file_data.find(f'name: {name}')
    assert 0 <= file_data.find(f'description: {description}')

    collection2 = DomainCollection.load(domains_file)
    assert collection.id == collection2.id
    assert collection.name == collection2.name
    assert collection.description == collection2.description