from pathlib import Path

from pydantic import BaseModel
import pytest

from datorum.document import (
    DOC_TYPES, DOC_MODELS, DOC_HANDLERS,
    register_doc_type,
    register_pydantic_based_handler,
    get_or_create_handler,
    find_handlers,
)
from datorum.exceptions import (
    DocumentFormatException
)


def test_registry(tmp_path: Path):
    doc_type = "text/test"
    doc_extentions = ["tst", "test"]

    doc_path = tmp_path / "test_registry.json"
    content_test = "Mocked Content"

    class PydanticBasedModel(BaseModel):
        var_test: str = ""

    registry_doc_type = register_doc_type(
        id=doc_type,
        extentions=doc_extentions
    )

    assert DOC_TYPES[doc_type].extentions == doc_extentions

    register_pydantic_based_handler(
        model_type=PydanticBasedModel,
    )
    registry_pydantic_handler = get_or_create_handler(
        doc_type="application/json",
        doc_model=PydanticBasedModel.__name__,
    )

    assert ("application/json", PydanticBasedModel.__name__) == registry_pydantic_handler.id

    obj1 = PydanticBasedModel(var_test=content_test)
    registry_pydantic_handler.serializer(obj1, doc_path)
    obj2 = registry_pydantic_handler.deserializer(doc_path)

    assert isinstance(obj2, PydanticBasedModel)
    assert obj1.var_test == obj2.var_test

    with pytest.raises(DocumentFormatException, match=r"^No dict serializer.*?$"):
        register_pydantic_based_handler(
            model_type=PydanticBasedModel,
            doc_type=doc_type
        )

    assert len(find_handlers()) > 3
    assert len(find_handlers(doc_type=doc_type)) == 0
    assert len(find_handlers(
        doc_model=PydanticBasedModel.__name__)) == 3
    assert len(find_handlers(
        doc_type="application/json",
        doc_model=PydanticBasedModel.__name__)) == 1