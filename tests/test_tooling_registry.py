import pytest
from typing import Any, Optional, Union
from pydantic import BaseModel

from datorum.tooling.registry import (
    ToolBoxRegistry,
    ContextField,
    ResourceField,
    FunctionDefinition,
    ToolBoxDefinition,
    ToolDefinition,
    get_toolbox_definition,
    tool,
    toolbox,
    _params_model_from_signature,
    _unwrap_optional,
    _is_optional,
    _hint_matches,
    _first_typed_param,
    _coerce_to_dict,
    _resolve_call_args,
)
from datorum.tooling.exceptions import ToolBoxRegistryError


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear and restore the global ToolBoxRegistry before and after each test."""
    original = ToolBoxRegistry.copy()
    ToolBoxRegistry.clear()
    yield
    ToolBoxRegistry.clear()
    ToolBoxRegistry.update(original)


# ============================================================================
# Helper Functions Tests
# ============================================================================

@pytest.mark.depends(on=["tests/test_context_settings.py"])
def test_params_model_from_signature():
    # Zero-arg function and skipped parameters (*args, **kwargs, self, cls)
    def zero_arg(self, cls, *args, **kwargs):
        pass

    assert _params_model_from_signature(zero_arg) is None

    # Function with single BaseModel parameter
    class InputModel(BaseModel):
        val: int

    def single_model_func(self, data: InputModel):
        pass

    assert _params_model_from_signature(single_model_func) is InputModel

    # Valid typed parameters with default values (multiple parameters)
    def valid_func(x: int, y: str = "default"):
        pass

    model = _params_model_from_signature(valid_func)
    assert model is not None
    instance = model(x=10)
    assert instance.x == 10
    assert instance.y == "default"

    # Untyped parameter raises ToolBoxRegistryError
    def untyped_func(x):
        pass

    with pytest.raises(ToolBoxRegistryError, match="has no type annotation"):
        _params_model_from_signature(untyped_func)

    # Type hint resolution failure raises ToolBoxRegistryError
    class UnresolvableCallable:
        def __call__(self, x: "NonExistentType"):  # type: ignore
            pass

    with pytest.raises(ToolBoxRegistryError, match="Tool 'anonymous' parameter 'x' has no type annotation; every tool parameter must be typed."):
        _params_model_from_signature(UnresolvableCallable())

@pytest.mark.depends(on=["tests/test_context_settings.py"])
def test_params_model_from_signature_exception():
    # Test that a TypeError/NameError in signature inspection raises ToolBoxRegistryError
    class UninspectableCallable:
        def __call__(self):
            pass

        def __signature__(self):
            raise TypeError("No signature available")


    with pytest.raises(ToolBoxRegistryError, match="Could not resolve type hints for function"):
        _params_model_from_signature(UninspectableCallable())

@pytest.mark.depends(on=["test_params_model_from_signature"])
def test_unwrap_optional_and_is_optional():
    # Optional / Union with None
    assert _unwrap_optional(Optional[int]) is int
    assert _unwrap_optional(int | None) is int
    assert _is_optional(Optional[int]) is True
    assert _is_optional(int | None) is True

    # Multi-type Union without None
    multi_union = Union[int, str]
    assert _unwrap_optional(multi_union) == multi_union
    assert _is_optional(multi_union) is False

    # Standard non-optional type
    assert _unwrap_optional(int) is int
    assert _is_optional(int) is False


@pytest.mark.depends(on=["test_unwrap_optional_and_is_optional"])
def test_hint_matches():
    assert _hint_matches(None, int) is False

    # Matching class and Optional class
    assert _hint_matches(int, int) is True
    assert _hint_matches(Optional[int], int) is True

    # Non-class candidate string
    assert _hint_matches("not a class", int) is False

    # Candidate that raises TypeError in issubclass check (e.g., Any)
    assert _hint_matches(Any, int) is False
    assert _hint_matches(dict, dict[str, Any]) is False


@pytest.mark.depends(on=["test_hint_matches"])
def test_first_typed_param():
    # Non-callable argument
    with pytest.raises(ToolBoxRegistryError, match="Argument is not callable"):
        _first_typed_param(12345, int)

    class SampleModel(BaseModel):
        val: int

    def sample_func(self, a: int, b: SampleModel):
        pass

    match = _first_typed_param(sample_func, SampleModel)
    assert match == ("b", SampleModel)

    # Callable whose type hints fail gracefully
    def func_with_bad_hint(x: "UnresolvableType"):  # type: ignore
        pass

    assert _first_typed_param(func_with_bad_hint, int) is None

    def func_with_args(*args, **kwargs):
        pass

    assert _first_typed_param(func_with_args, int) is None


@pytest.mark.depends(on=["test_first_typed_param"])
def test_coerce_to_dict():
    class DummyModel(BaseModel):
        name: str

    model_inst = DummyModel(name="test")
    assert _coerce_to_dict(model_inst) == {"name": "test"}

    data_dict = {"a": 1}
    assert _coerce_to_dict(data_dict) == {"a": 1}

    # Unsupported data type raises error
    with pytest.raises(ToolBoxRegistryError, match="Expected a dict or BaseModel"):
        _coerce_to_dict(12345)


@pytest.mark.depends(on=["test_coerce_to_dict"])
def test_resolve_call_args():
    class DummyModel(BaseModel):
        val: int

    class DummyModelStr(BaseModel):
        val: str = "hello"

    def func_with_model(model: DummyModel):
        return model.val

    def func_with_dict(data: dict):
        return data

    def func_unmatched(x: int):
        return x

    # 1. data is None
    assert _resolve_call_args(func_with_model, None, DummyModel) == ((), {})

    # 2. data is already an instance of the hint
    inst = DummyModel(val=5)
    assert _resolve_call_args(func_with_model, inst, DummyModel) == ((inst,), {})

    # 3. data is a dict converted to a BaseModel parameter
    args, kwargs = _resolve_call_args(func_with_model, {"val": 10}, DummyModel)
    assert len(args) == 1 and isinstance(args[0], DummyModel) and args[0].val == 10

    # 4. hint matched but is not a BaseModel (e.g. plain dict)
    args, kwargs = _resolve_call_args(func_with_dict, {"a": 1}, dict)
    assert args == ({"a": 1},) and kwargs == {}

    # 5. match is None -> passes coerced dict as **kwargs
    args, kwargs = _resolve_call_args(func_unmatched, {"x": 42}, DummyModel)
    assert args == () and kwargs == {"x": 42}

    args, kwargs = _resolve_call_args(func_with_dict, DummyModelStr(), dict)
    assert args == ({"val": "hello"},)
    assert kwargs == {}

# ============================================================================
# Models, Registry, Decorators, and Async Execution Tests
# ============================================================================

@pytest.mark.depends(on=["test_resolve_call_args"])
def test_function_definition_and_tool_definition():
    class ParamModel(BaseModel):
        a: int

    # FunctionDefinition from params model
    func_def = FunctionDefinition.from_params_model("test_func", "desc", ParamModel)
    assert func_def.parameters_model is ParamModel
    assert "properties" in func_def.parameters

    # Setter test for parameters_model
    func_def.parameters_model = ParamModel
    assert func_def.parameters_model is ParamModel

    # FunctionDefinition without params model
    func_def_none = FunctionDefinition.from_params_model("test_func", "desc", None)
    assert func_def_none.parameters_model is None
    assert func_def_none.parameters["properties"] == {}

    # ToolDefinition getter/setter for returns property
    tool_def = ToolDefinition(name="my_tool", function=func_def)
    assert tool_def.returns is str
    tool_def.returns = int
    assert tool_def.returns is int


@pytest.mark.depends(on=["test_function_definition_and_tool_definition"])
def test_get_toolbox_definition():
    with pytest.raises(ToolBoxRegistryError, match="ToolBox 'unknown' not found"):
        get_toolbox_definition("unknown")


@pytest.mark.depends(on=["test_get_toolbox_definition"])
def test_toolbox_and_tool_decorators():
    class CustomParams(BaseModel):
        msg: str

    @toolbox(name="MyToolBox")
    class MyToolBox:
        ctx_field: ContextField = ContextField(name="ctx_1")
        res_field: ResourceField = ResourceField(name="res_1")
        untyped_ctx: ContextField = ContextField(name="ctx_untyped")
        untyped_res: ResourceField = ResourceField(name="res_untyped")

        optional_ctx: Optional[str] = ContextField(name="ctx_opt")
        required_ctx: str = ContextField(name="ctx_req")

        optional_res: Optional[str] = ResourceField(name="res_opt")
        required_res: str = ResourceField(name="res_req")

        @tool(name="custom_tool")
        def echo(self, params: CustomParams) -> str:
            """Echo description"""
            return params.msg

        @tool()
        def no_params_tool(self) -> int:
            return 42

    tb_def = get_toolbox_definition("MyToolBox")
    assert tb_def.name == "MyToolBox"
    assert "custom_tool" in tb_def.tools
    assert "no_params_tool" in tb_def.tools

    # Re-registering without force=True raises ToolBoxRegistryError
    with pytest.raises(ToolBoxRegistryError, match="already registered"):
        @toolbox(name="MyToolBox")
        class DuplicateToolBox:
            pass

    # Re-registering with force=True succeeds
    @toolbox(name="MyToolBox", force=True)
    class OverwrittenToolBox:
        pass

    assert get_toolbox_definition("MyToolBox").clazz is OverwrittenToolBox


@pytest.mark.depends(on=["test_toolbox_and_tool_decorators"])
def test_toolbox_duplicate_tool_and_field_errors():
    # Duplicate tool name on same toolbox
    with pytest.raises(ToolBoxRegistryError, match="Tool 'same_tool' is already registered"):
        @toolbox(name="DupToolBox")
        class DupToolBox:
            @tool(name="same_tool")
            def tool_1(self):
                pass

            @tool(name="same_tool")
            def tool_2(self):
                pass

    # Duplicate ContextField name
    with pytest.raises(ToolBoxRegistryError, match="Field 'same_ctx' is already registered"):
        @toolbox(name="DupCtxToolBox")
        class DupCtxToolBox:
            c1: ContextField = ContextField(name="same_ctx")
            c2: ContextField = ContextField(name="same_ctx")

    # Duplicate ResourceField name
    with pytest.raises(ToolBoxRegistryError, match="Field 'same_res' is already registered"):
        @toolbox(name="DupResToolBox")
        class DupResToolBox:
            r1: ResourceField = ResourceField(name="same_res")
            r2: ResourceField = ResourceField(name="same_res")


@pytest.mark.depends(on=["test_toolbox_duplicate_tool_and_field_errors"])
def test_toolbox_unresolvable_type_hints():
    @toolbox()
    class UnresolvableToolBox:
        unresolved: "NonExistentType"

    assert "UnresolvableToolBox" in ToolBoxRegistry

@pytest.mark.depends(on=["test_toolbox_unresolvable_type_hints"])
def test_toolbox_unannotated_field():
    @toolbox()
    class UnannotatedContextToolBox:
        ctx = ContextField(name="ctx")  # No type hint like `ctx: Any`

    tb_def = get_toolbox_definition("UnannotatedContextToolBox")
    assert tb_def.context_fields["ctx"].required is False

    @toolbox()
    class UnannotatedResourceToolBox:
        res = ResourceField(name="res")  # No type hint like `res: Any`

    tb_def = get_toolbox_definition("UnannotatedResourceToolBox")
    assert tb_def.resource_fields["res"].required is False

@pytest.mark.asyncio
@pytest.mark.depends(on=["test_toolbox_unannotated_field"])
async def test_toolbox_instance_execution_and_missing_fields():
    class InputParams(BaseModel):
        text: str

    @toolbox(name="ExecToolBox")
    class ExecToolBox:
        req_context: str = ContextField(name="req_ctx", required=True)
        req_resource: str = ResourceField(name="req_res", required=True)

        @tool()
        def process(self, params: InputParams) -> str:
            return params.text.upper()

        @tool()
        async def async_process(self, params: InputParams) -> str:
            return f"async_{params.text}"

        @tool()
        def simple(self) -> str:
            return "ok"

    tb_def = get_toolbox_definition("ExecToolBox")
    tb_instance = tb_def.create_toolbox()

    # Verify ToolBox definition method binding
    assert tb_instance.get_toolbox_definition() is tb_def

    # Missing required context/resource fields raise ToolBoxRegistryError
    with pytest.raises(
        ToolBoxRegistryError,
        match=r"Missing required field\(s\): \['ctx:req_ctx', 'res:req_res'\]",
    ):
        await tb_instance.run_tool("process", {"text": "hello"})

    # Populate required fields
    tb_instance.req_context = "ctx_val"
    tb_instance.req_resource = "res_val"

    # Execute sync tool with dict parameters
    res = await tb_instance.run_tool("process", {"text": "hello"})
    assert res == "HELLO"

    # Execute async tool with dict parameters
    async_res = await tb_instance.run_tool("async_process", {"text": "hello"})
    assert async_res == "async_hello"

    # Execute tool without parameters
    res_simple = await tb_instance.run_tool("simple")
    assert res_simple == "ok"

@pytest.mark.depends(on=["test_toolbox_unannotated_field"])
def test_toolbox_definition_create_without_clazz():
    # Test that create_toolbox raises ToolBoxRegistryError when clazz is None
    tb_def = ToolBoxDefinition(
        name="TestToolBox",
        tools={},
        context_fields={},
        resource_fields={},
        clazz=None
    )
    
    with pytest.raises(ToolBoxRegistryError, match="ToolBox type is not defined"):
        tb_def.create_toolbox()