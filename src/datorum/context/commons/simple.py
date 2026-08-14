import json
from pathlib import Path

import tomli_w
import tomllib
import yaml

from ..registry import (
    register_doc_type,
    DocumentModelRegistry,
    DocumentModel,
    serializer,
    deserializer,
)

register_doc_type("text/plain", ["txt"])
register_doc_type("application/json", ["json"])
register_doc_type("application/yaml", ["yml", "yaml"])
register_doc_type("application/toml", ["toml"])

DocumentModelRegistry["text"] = DocumentModel(id="text", clazz=str)
DocumentModelRegistry["dict"] = DocumentModel(id="dict", clazz=dict)


@serializer(doc_type="text/plain", doc_model="text")
def simple_text_writer(data: str, file_path: Path):
    file_path.write_text(data, encoding="utf-8")


@deserializer(doc_type="text/plain", doc_model="text")
def simple_text_reader(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8")


@serializer(doc_type="application/json", doc_model="dict")
def simple_json_writer(data: dict, file_path: Path):
    text = json.dumps(data, indent=2, ensure_ascii=False)
    file_path.write_text(text)


@deserializer(doc_type="application/json", doc_model="dict")
def simple_json_reader(file_path: Path) -> dict:
    text = file_path.read_text(encoding="utf-8")
    return json.loads(text)


@serializer(doc_type="application/yaml", doc_model="dict")
def simple_yaml_writer(data: dict, file_path: Path):
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    file_path.write_text(text)


@deserializer(doc_type="application/yaml", doc_model="dict")
def simple_yaml_reader(file_path: Path) -> dict:
    text = file_path.read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


@serializer(doc_type="application/toml", doc_model="dict")
def simple_toml_writer(data: dict, file_path: Path):
    text = tomli_w.dumps(data)
    file_path.write_text(text)


@deserializer(doc_type="application/toml", doc_model="dict")
def simple_toml_reader(file_path: Path) -> dict:
    text = file_path.read_text(encoding="utf-8")
    return tomllib.loads(text)
