from pathlib import Path

import pytest

from datorum.domains import (
    DOMAIN_DELIMITER,
    DomainCollection,
    Domain,
    Source,
)


def test_resolve_path():
    p1 = DomainCollection._resolve_path()
    p2 = DomainCollection._resolve_path('data')
    p3 = DomainCollection._resolve_path(Path('data'))
    assert p2 == p3


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


def test_invalid_name():
    error_ok = False
    try:
        Domain(id = f'invalid{DOMAIN_DELIMITER}id')
    except ValueError:
        error_ok = True
    assert error_ok


def test_find():
    idc = 'a_collection'
    idd1 = 'a_domain_1'
    idd2 = 'a_domain_2'
    idd3 = 'a_domain_3'
    idd4 = 'a_domain_4'
    ids1 = 'a_source_1'
    ids2 = 'a_source_2'

    col = DomainCollection(id=idc, name='Domain Collection Test')
    d1 = Domain(id=idd1, name='Domain Test 1')
    d2 = Domain(id=idd2, name='Domain Test 2')
    d3 = Domain(id=idd3, name='Domain Test 3')
    d4 = Domain(id=idd4, name='Domain Test 4')
    s1 = Source(id=ids1, name='Source Test 1')
    s2 = Source(id=ids2, name='Source Test 2')

    col.domains.append(d1)
    col.domains.append(d2)
    d1.domains.append(d3)
    d3.domains.append(d4)
    d2.sources.append(s1)
    d4.sources.append(s2)

    col_dump = col.model_dump()
    _col = DomainCollection.model_validate(col_dump)

    _d4 = _col[f'{idd1}{DOMAIN_DELIMITER}{idd3}{DOMAIN_DELIMITER}{idd4}']
    _s1 = _col[f'{idd2}{DOMAIN_DELIMITER}{ids1}']
    _s2 = _col[f'{idd1}{DOMAIN_DELIMITER}{idd3}{DOMAIN_DELIMITER}{idd4}{DOMAIN_DELIMITER}{ids2}']
    _all_sources = [node for node in _col.walk() if isinstance(node, Source)]

    assert _d4.id == d4.id
    assert _d4.name == d4.name
    assert type(_d4) == type(d4)
    assert _s1.id == s1.id
    assert _s2.id == s2.id
    assert _s2.parent.id == d4.id
    assert f'{idd2}{DOMAIN_DELIMITER}{ids1}' in _col
    assert _col.get('') == _col
    assert len(_all_sources) == 2

    assert _col.get(f'{idd2}{DOMAIN_DELIMITER}{idd1}') is None
    assert _col.get(f'{idd2}{DOMAIN_DELIMITER}{ids1}{DOMAIN_DELIMITER}{idd1}') is None


def test_find_errors():
    error_ok = False

    idc = 'a_collection'
    idd1 = 'a_domain_1'
    idd2 = 'a_domain_2'
    ids1 = 'a_source_1'

    col = DomainCollection(id=idc, name='Domain Collection Test')
    d1 = Domain(id=idd1, name='Domain Test 1')
    d1_clone = Domain(id=idd1, name='Domain Test 1')
    d2 = Domain(id=idd2, name='Domain Test 2')
    s1 = Source(id=ids1, name='Source Test 1')

    col.domains.append(d1)
    col.domains.append(d1_clone)
    col.domains.append(d2)
    d1.domains.append(s1)

    try:
        col[f'{idd2}{DOMAIN_DELIMITER}{idd1}']
    except KeyError:
        error_ok = True
    assert error_ok

    error_ok = False
    try:
        col_dump = col.model_dump()
        _col = DomainCollection.model_validate(col_dump)
    except ValueError:
        error_ok = True
    assert error_ok




