import json
import tomllib
from pathlib import Path
from typing import Self

import tomli_w
import yaml

from ..registry import (
    deserializer,
    doc_model,
    register_doc_type,
    serializer,
)

register_doc_type("text/markdown", ["md", "markdown", "markdn", "mdown"])


@doc_model(id="markdown", doc_type="text/markdown")
class MarkdownDocument:
    FRONTMATTER_YAML = "yaml"
    FRONTMATTER_JSON = "json"
    FRONTMATTER_TOML = "toml"

    DELIMITER_YAML = "---\n"
    DELIMITER_JSON = ";;;\n"
    DELIMITER_TOML = "+++\n"

    def __init__(
        self,
        content: str,
        frontmatter: dict | None = None,
        frontmatter_format: str | None = None,
    ):
        self.content = content
        self.frontmatter = frontmatter
        self.frontmatter_format = frontmatter_format or self.FRONTMATTER_YAML

    def dumps(self) -> str:
        raw = self.content
        if self.frontmatter_format == self.FRONTMATTER_YAML:
            frontmatter_raw = yaml.safe_dump(
                self.frontmatter, sort_keys=False, allow_unicode=True
            )
            raw = (
                f"{self.DELIMITER_YAML}{frontmatter_raw}\n{self.DELIMITER_YAML}\n{raw}"
            )
        elif self.frontmatter_format == self.FRONTMATTER_JSON:
            frontmatter_raw = json.dumps(self.frontmatter, indent=2, ensure_ascii=False)
            raw = (
                f"{self.DELIMITER_JSON}{frontmatter_raw}\n{self.DELIMITER_JSON}\n{raw}"
            )
        elif self.frontmatter_format == self.FRONTMATTER_TOML:
            frontmatter_raw = tomli_w.dumps(self.frontmatter)
            raw = (
                f"{self.DELIMITER_TOML}{frontmatter_raw}\n{self.DELIMITER_TOML}\n{raw}"
            )
        return raw

    def dump(self, file_path: Path):
        file_path.write_text(self.dumps(), encoding="utf-8")

    @classmethod
    def loads(cls, raw: str) -> Self:
        content: str = raw
        frontmatter: dict | None = None
        frontmatter_format: str | None = None

        if raw.startswith(cls.DELIMITER_YAML):
            closure = raw.find(cls.DELIMITER_YAML, len(cls.DELIMITER_YAML))
            if closure > 0:
                frontmatter_format = cls.FRONTMATTER_YAML
                frontmatter_raw = raw[len(cls.DELIMITER_YAML) : closure]
                frontmatter = yaml.safe_load(frontmatter_raw) or {}
                content = raw[closure + len(cls.DELIMITER_YAML) :]
        elif raw.startswith(cls.DELIMITER_JSON):
            closure = raw.find(cls.DELIMITER_JSON, len(cls.DELIMITER_JSON))
            if closure > 0:
                frontmatter_format = cls.FRONTMATTER_JSON
                frontmatter_raw = raw[len(cls.DELIMITER_JSON) : closure]
                frontmatter = json.loads(frontmatter_raw)
                content = raw[closure + len(cls.DELIMITER_JSON) :]
        elif raw.startswith(cls.DELIMITER_TOML):
            closure = raw.find(cls.DELIMITER_TOML, len(cls.DELIMITER_TOML))
            if closure > 0:
                frontmatter_format = cls.FRONTMATTER_TOML
                frontmatter_raw = raw[len(cls.DELIMITER_TOML) : closure]
                frontmatter = tomllib.loads(frontmatter_raw)
                content = raw[closure + len(cls.DELIMITER_TOML) :]

        return cls(
            content=content.strip(),
            frontmatter=frontmatter,
            frontmatter_format=frontmatter_format,
        )

    @classmethod
    def load(cls, file_path: Path) -> Self:
        return cls.loads(file_path.read_text(encoding="utf-8"))


@serializer(doc_type="text/markdown", doc_model="markdown")
def markdown_writer(data: MarkdownDocument, file_path: Path):
    data.dump(file_path=file_path)


@deserializer(doc_type="text/markdown", doc_model="markdown")
def markdown_reader(file_path: Path) -> MarkdownDocument:
    return MarkdownDocument.load(file_path=file_path)
