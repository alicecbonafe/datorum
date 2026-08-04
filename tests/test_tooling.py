import pytest
from pydantic import BaseModel

from datorum.exceptions import (
    ToolBoxException,
)
from datorum.tooling import (
    AttributeExposure,
    FunctionDefinition,
    ToolBoxDefinition,
    ToolBoxRegistry,
    ToolDefinition,
    _coerce_to_dict,
    _first_typed_param,
    _hint_matches,
    _params_model_from_signature,
    _resolve_call_args,
    _unwrap_optional,
    tool,
    toolbox,
)


def test_helpers():
    class mocked_model_1(BaseModel):
        required_text: str
        optional_int: int | None = None

    def mocked_func_1(
        self, required_text: str, optional_int: int | None = None, **kwargs
    ):
        return f"{required_text}: {optional_int or -1}"

    # _params_model_from_signature
    mocked_model_2 = _params_model_from_signature(mocked_func_1)
    assert mocked_model_2 is not None
    fields_1 = mocked_model_1.model_fields
    fields_2 = mocked_model_2.model_fields

    assert set(fields_1.keys()) == set(fields_2.keys())
    assert _params_model_from_signature(lambda: "Ok") is None

    with pytest.raises(
        ToolBoxException, match=r"^Could not resolve type hints for.*?$"
    ):
        _params_model_from_signature("error")  # type: ignore[arg-type]
    with pytest.raises(ToolBoxException, match=r"^Tool .*? has no type annotation.*?$"):
        _params_model_from_signature(lambda no_hint: no_hint + 1)

    # _unwrap_optional
    assert _unwrap_optional(str | None) == str
    assert _unwrap_optional(str) == str

    # _hint_matches
    assert not _hint_matches(None, mocked_model_1)
    assert not _hint_matches("mocked", mocked_model_1)
    assert not _hint_matches(mocked_model_2, mocked_model_1)
    assert not _hint_matches(mocked_model_2, "mocked")  # type: ignore[arg-type]

    class mocke_model_3(mocked_model_1): ...

    assert _hint_matches(mocke_model_3, mocked_model_1)

    # _first_typed_param
    assert _first_typed_param(mocked_func_1, mocked_model_1) is None

    def mocked_func_2(arg_1: mocked_model_1): ...

    param = _first_typed_param(mocked_func_2, mocked_model_1)
    assert param is not None
    assert param[0] == "arg_1"
    assert param[1] == mocked_model_1

    with pytest.raises(ToolBoxException, match="Argument is not callable"):
        _first_typed_param("", mocked_model_1)  # type: ignore[arg-type]

    # _coerce_to_dict
    data_1 = {"required_text": "Mocked Text!!!", "optional_int": 100}
    data_1_model = mocked_model_1.model_validate(data_1)
    data_2 = _coerce_to_dict(data=data_1)
    data_3 = _coerce_to_dict(data=data_1_model)
    assert data_1 == data_2
    assert data_1 == data_3

    with pytest.raises(ToolBoxException, match=r"^Expected a dict or BaseModel.*?$"):
        _coerce_to_dict("raises exception")

    # _resolve_call_args
    assert _resolve_call_args(
        callable_obj=mocked_func_1, data=None, model_type=mocked_model_1
    ) == ((), {})

    assert _resolve_call_args(
        callable_obj=mocked_func_1, data={}, model_type=mocked_model_1
    ) == ((), {})

    assert _resolve_call_args(
        callable_obj=mocked_func_2, data=data_1_model, model_type=mocked_model_1
    ) == ((data_1_model,), {})

    args_2 = _resolve_call_args(
        callable_obj=mocked_func_2,
        data={"required_text": "Mocked Test!!!"},
        model_type=mocked_model_1,
    )
    assert isinstance(args_2[0][0], mocked_model_1)
    assert args_2[0][0].required_text == "Mocked Test!!!"

    def mocked_func_3(a_dict: dict): ...

    args_1 = _resolve_call_args(
        callable_obj=mocked_func_3, data=data_1_model, model_type=dict
    )
    assert args_1[0][0]["required_text"] == data_1_model.required_text


@pytest.mark.depends(on="test_helpers")
def test_classes():
    function_name = "mocked-function"
    function_descr = "This function is a mock!"
    tool_definition_name = "mocked-tool-def"
    attribute_name = "mocked_attribute"
    toolbox_definition_id_1 = "mocked-toolbox-def-1"
    toolbox_definition_id_2 = "mocked-toolbox-def-2"
    toolbox_definition_id_3 = "mocked-toolbox-def-3"

    class MockedClass1(BaseModel):
        param_1: str
        param_2: str | None = None

    class MockedToolBox1:
        def tool_1(self, param_1: str, param_2: str | None = None) -> str:
            return f"{param_1}[{param_2 or ''}]"

    class MockedToolBox2:
        def __init__(self, settings: dict):
            self.settings = settings

        def tool_2(self): ...

    class MockedToolBox3:
        def __init__(self):
            self.settings = {}

        def tool_3(self): ...

    # FunctionDefinition
    function_1 = FunctionDefinition.from_params_model(
        name=function_name, description=function_descr, params_model=MockedClass1
    )
    assert function_1.parameters_model is MockedClass1

    function_2 = FunctionDefinition.from_params_model(
        name=function_name, description=function_descr, params_model=None
    )
    assert function_2.parameters_model is None
    assert "properties" in function_2.parameters
    assert isinstance(function_2.parameters["properties"], dict)
    assert len(function_2.parameters["properties"]) == 0

    # ToolDefinition
    tool_def_1 = ToolDefinition(name=tool_definition_name, function=function_1)
    tool_def_1.returns = MockedClass1
    assert issubclass(tool_def_1.returns, BaseModel)

    # AttributeExposure
    attr_exp_1 = AttributeExposure(attr_name=attribute_name)
    attr_exp_1.attr_type = MockedClass1
    assert attr_exp_1.attr_type is not None
    assert issubclass(attr_exp_1.attr_type, BaseModel)

    # ToolBoxDefinition
    FunctionDefinition(
        name=function_name,
        description=function_descr,
    )
    tb_def_1 = ToolBoxDefinition(id=toolbox_definition_id_1)
    tb_def_1.clazz = MockedToolBox1
    MockedToolBox1.tool_1._tool_def = tool_def_1  # type: ignore[attr-defined]

    toolbox_instance_1 = tb_def_1.create_toolbox()

    assert hasattr(toolbox_instance_1, "run_tool")

    tool_result = toolbox_instance_1.run_tool("tool_1", {"param_1": "mocked-test"})
    assert tool_result == "mocked-test[]"

    tb_def_2 = ToolBoxDefinition(id=toolbox_definition_id_2)
    tb_def_2.clazz = MockedToolBox2

    tool_def_2 = ToolDefinition(name=tool_definition_name, function=function_2)
    MockedToolBox2.tool_2._tool_def = tool_def_2  # type: ignore[attr-defined]

    toolbox_instance_2 = tb_def_2.create_toolbox({"any_key": "any-value"})

    assert hasattr(toolbox_instance_2, "run_tool")
    assert toolbox_instance_2.settings["any_key"] == "any-value"

    toolbox_instance_2.run_tool("tool_2")

    tb_def_3 = ToolBoxDefinition(id=toolbox_definition_id_3)
    tb_def_3.clazz = MockedToolBox3
    tb_def_3.settings_attr = "settings"
    tb_def_3.settings_type = dict
    MockedToolBox3.tool_3._tool_def = tool_def_2  # type: ignore[attr-defined]

    toolbox_instance_3 = tb_def_3.create_toolbox({"any_key": "any-other-value"})

    assert hasattr(toolbox_instance_3, "run_tool")
    assert toolbox_instance_3.settings["any_key"] == "any-other-value"

    with pytest.raises(ToolBoxException, match=r"^ToolBox '.*?' has no defined clazz$"):
        assert ToolBoxDefinition(id=toolbox_definition_id_1).clazz


@pytest.mark.depends(on="test_classes")
def test_decorators():
    toolbox_name = "mocked-toolbox"
    tool_value = "any-value"

    @toolbox(name=toolbox_name, expose=["exposed_attr"])
    class MockedToolBox:
        exposed_attr: dict

        @tool()
        def mocked_tool(self, param_1: str):
            return f"[{param_1}]"

    assert toolbox_name in ToolBoxRegistry
    assert ToolBoxRegistry[toolbox_name].clazz is MockedToolBox
    assert "exposed_attr" in ToolBoxRegistry[toolbox_name].attributes
    assert hasattr(MockedToolBox.mocked_tool, "_tool_def")

    toolbox_1 = ToolBoxRegistry[toolbox_name].create_toolbox()
    result_1 = toolbox_1.run_tool("mocked_tool", {"param_1": tool_value})
    assert result_1 == f"[{tool_value}]"
