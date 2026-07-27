from pathlib import Path

from datorum import GeneralConfig
from datorum.domains import (
    DOMAIN_DELIMITER,
    Domain,
    DomainCollection,
    Source,
)
from datorum.exceptions import InvalidIdentifierException, OrphanSourceException


def test_resolve_path():
    GeneralConfig["DATA_DIR"] = "data"
    p1 = DomainCollection._resolve_path()
    p2 = DomainCollection._resolve_path("data/domains.yml")
    p3 = DomainCollection._resolve_path(Path("data") / "domains.yml")
    assert p1 == p2
    assert p2 == p3


def test_persistence(tmp_path: Path):
    domains_file = tmp_path / "domains.yml"

    id = "test"
    name = "Test Collection"
    description = "This is a test."

    collection = DomainCollection(id=id, name=name, description=description)
    collection.save(domains_file)

    with domains_file.open("r", encoding="utf-8") as f:
        file_data = f.read()
    assert 0 <= file_data.find(f"id: {id}")
    assert 0 <= file_data.find(f"name: {name}")
    assert 0 <= file_data.find(f"description: {description}")

    collection2 = DomainCollection.load(domains_file)
    assert collection.id == collection2.id
    assert collection.name == collection2.name
    assert collection.description == collection2.description


def test_invalid_name():
    error_ok = False
    try:
        Domain(id=f"invalid{DOMAIN_DELIMITER}id")
    except InvalidIdentifierException:
        error_ok = True
    assert error_ok


def test_find():
    idc = "a_collection"
    idd1 = "a_domain_1"
    idd2 = "a_domain_2"
    idd3 = "a_domain_3"
    idd4 = "a_domain_4"
    ids1 = "a_source_1"
    ids2 = "a_source_2"

    col = DomainCollection(id=idc, name="Domain Collection Test")
    d1 = Domain(id=idd1, name="Domain Test 1")
    d2 = Domain(id=idd2, name="Domain Test 2")
    d3 = Domain(id=idd3, name="Domain Test 3")
    d4 = Domain(id=idd4, name="Domain Test 4")
    s1 = Source(id=ids1, name="Source Test 1")
    s2 = Source(id=ids2, name="Source Test 2")

    col.domains.append(d1)
    col.domains.append(d2)
    d1.domains.append(d3)
    d3.domains.append(d4)
    d2.sources.append(s1)
    d4.sources.append(s2)

    col_dump = col.model_dump()
    _col = DomainCollection.model_validate(col_dump)

    _d4 = _col[f"{idd1}{DOMAIN_DELIMITER}{idd3}{DOMAIN_DELIMITER}{idd4}"]
    _s1 = _col[f"{idd2}{DOMAIN_DELIMITER}{ids1}"]
    _s2 = _col[
        f"{idd1}{DOMAIN_DELIMITER}{idd3}{DOMAIN_DELIMITER}{idd4}{DOMAIN_DELIMITER}{ids2}"
    ]
    _all_sources = [node for node in _col.walk() if isinstance(node, Source)]

    assert _d4.id == d4.id
    assert _d4.name == d4.name
    assert type(_d4) == type(d4)
    assert _s1.id == s1.id
    assert _s2.id == s2.id
    assert _s2.parent.id == d4.id
    assert f"{idd2}{DOMAIN_DELIMITER}{ids1}" in _col
    assert _col.get("") == _col
    assert len(_all_sources) == 2

    assert _col.get(f"{idd2}{DOMAIN_DELIMITER}{idd1}") is None
    assert _col.get(f"{idd2}{DOMAIN_DELIMITER}{ids1}{DOMAIN_DELIMITER}{idd1}") is None

    assert _col.full_id == _col.id
    assert _col[idd1].full_id == f"{_col.id}{DOMAIN_DELIMITER}{idd1}"


def test_find_errors():
    error_ok = False

    idc = "a_collection"
    idd1 = "a_domain_1"
    idd2 = "a_domain_2"
    ids1 = "a_source_1"

    col = DomainCollection(id=idc, name="Domain Collection Test")
    d1 = Domain(id=idd1, name="Domain Test 1")
    d1_clone = Domain(id=idd1, name="Domain Test 1")
    d2 = Domain(id=idd2, name="Domain Test 2")
    s1 = Source(id=ids1, name="Source Test 1")

    col.domains.append(d1)
    col.domains.append(d1_clone)
    col.domains.append(d2)
    d1.domains.append(s1)

    try:
        col[f"{idd2}{DOMAIN_DELIMITER}{idd1}"]
    except KeyError:
        error_ok = True
    assert error_ok

    error_ok = False
    try:
        col_dump = col.model_dump()
        _col = DomainCollection.model_validate(col_dump)
    except InvalidIdentifierException:
        error_ok = True
    assert error_ok


def test_create():

    idc = "a_collection"
    idd1 = "a_domain_1"
    idd2 = "a_domain_2"
    idd3 = "a_domain_3"
    ids1 = "a_source_1"
    ids2 = "a_source_2"

    col = DomainCollection(id=idc, name="Domain Collection Test")
    d1 = col.create_domain(idd1)
    d3 = col.create_domain(f"{idd2}{DOMAIN_DELIMITER}{idd3}")
    d2 = col[idd2]
    s1 = d1.create_source(ids1)
    s2 = col.create_source(f"{idd2}{DOMAIN_DELIMITER}{idd3}{DOMAIN_DELIMITER}{ids2}")

    assert len(col.domains) == 2
    assert len(d2.domains) == 1
    assert len(d3.sources) == 1


def test_create_errors():

    error_ok = False

    idc = "a_collection"

    idd1 = "a_domain_1"
    ids1 = "a_source_1"

    col = DomainCollection(id=idc, name="Domain Collection Test")
    col.create_domain(idd1)
    col.create_source(ids1)

    error_ok = False
    try:
        col.create_domain("")
    except InvalidIdentifierException:
        error_ok = True
    assert error_ok

    error_ok = False
    try:
        col.create_source("")
    except InvalidIdentifierException:
        error_ok = True
    assert error_ok

    error_ok = False
    try:
        col.create_domain(ids1)
    except InvalidIdentifierException:
        error_ok = True
    assert error_ok

    error_ok = False
    try:
        col.create_source(idd1)
    except InvalidIdentifierException:
        error_ok = True
    assert error_ok


def test_invalid_id_characters():
    for bad_id in ("invalid/id", "invalid id", "invalid..id"):
        error_ok = False
        try:
            Domain(id=bad_id)
        except InvalidIdentifierException:
            error_ok = True
        assert error_ok, f"expected '{bad_id}' to be rejected"


def test_path_parts_and_root():
    col = DomainCollection(id="a_collection", name="Collection")
    d1 = col.create_domain("domain_1")
    d2 = d1.create_domain("domain_2")
    s1 = d2.create_source("source_1")

    assert col.path_parts == ()
    assert d1.path_parts == ("domain_1",)
    assert d2.path_parts == ("domain_1", "domain_2")
    assert s1.path_parts == ("domain_1", "domain_2", "source_1")

    assert d1.root is col
    assert d2.root is col
    assert s1.root is col


def test_source_path_defaults(tmp_path: Path):
    col = DomainCollection(id="col")
    col.save(tmp_path / "domains.yml")

    d1 = col.create_domain("domain_1")
    s1 = d1.create_source("source_1")

    assert (
        s1.source_path == tmp_path / "sources" / "domain_1" / "source_1" / "source_1.md"
    )
    assert (
        s1.chunks_path
        == tmp_path / "chunks" / "domain_1" / "source_1" / "source_1.json"
    )


def test_source_path_explicit_filenames(tmp_path: Path):
    col = DomainCollection(id="col")
    col.save(tmp_path / "domains.yml")

    d1 = col.create_domain("domain_1")
    s1 = d1.create_source("source_1", source_file="raw.html", chunks_file="out.json")

    assert s1.source_path == tmp_path / "sources" / "domain_1" / "source_1" / "raw.html"
    assert s1.chunks_path == tmp_path / "chunks" / "domain_1" / "source_1" / "out.json"


def test_source_path_custom_dirs(tmp_path: Path):
    col = DomainCollection(id="col", sources_dir="raw", chunks_dir="processed")
    col.save(tmp_path / "domains.yml")

    s1 = col.create_source("source_1")

    assert s1.source_path == tmp_path / "raw" / "source_1" / "source_1.md"
    assert s1.chunks_path == tmp_path / "processed" / "source_1" / "source_1.json"


def test_source_path_requires_attached_collection():
    detached = Source(id="detached")

    error_ok = False
    try:
        if detached.source_path:
            assert False
    except OrphanSourceException:
        error_ok = True
    assert error_ok
