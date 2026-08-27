import json
from pathlib import Path
from typing import Optional

import pytest
from pydantic import BaseModel

from datorum.binding.binder import Binder
from datorum.binding.settings import (
    ContextBind,
    ContextBindType,
    ResourceBind,
)
from datorum.context.settings import (
    DocumentContext,
)
from datorum.context.commons.chat import (
    AssistantMessage,
    ChatHistory,
    ToolCall,
    ToolFunction,
    ToolMessage,
    UserMessage,
)
from datorum.tooling.exceptions import ToolWorkerError
from datorum.tooling.registry import (
    ContextField,
    ResourceField,
    ToolBoxRegistry,
    tool,
    toolbox,
)
from datorum.tooling.settings import ToolBoxSetUp, ToolKit
from datorum.tooling.worker import ToolWorker
from datorum.work.job import Job, JobStatus


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture(autouse=True)
def clear_registry():
    """Clear and restore the global ToolBoxRegistry before and after each test."""
    original = ToolBoxRegistry.copy()
    ToolBoxRegistry.clear()
    yield
    ToolBoxRegistry.clear()
    ToolBoxRegistry.update(original)


class GreetParams(BaseModel):
    name: str


@pytest.fixture
def greeter_box():
    @toolbox(name="GreeterBox")
    class GreeterBox:
        prefix: str = ContextField(
            name="prefix", context_bind_type=ContextBindType.text, required=True)
        suffix: Optional[str] = ContextField(
            name="suffix", context_bind_type=ContextBindType.text, required=False)
        echo: Optional[str] = ContextField(
            name="echo", context_bind_type=ContextBindType.text_output, required=False)

        @tool()
        def greet(self, params: GreetParams) -> str:
            self.echo = f"echoed:{params.name}"
            return f"{self.prefix}{params.name}{self.suffix or ''}"

        @tool()
        def ping(self) -> str:
            return "pong"

    return GreeterBox


class SampleModel(BaseModel):
    data: str


@pytest.fixture
def multi_type_box():
    @toolbox(name="MultiTypeBox")
    class MultiTypeBox:
        input_only: Optional[str] = ContextField(
            name="input_only",
            context_bind_type=ContextBindType.text_input,
            required=False,
        )
        
        @tool()
        def return_dict(self) -> dict:
            return {"status": "ok", "count": 1}

        @tool()
        def return_model(self) -> SampleModel:
            return SampleModel(data="test_value")

        @tool()
        def return_primitive(self) -> int:
            return 12345

    return MultiTypeBox


@pytest.fixture
def resourceful_box():
    @toolbox(name="ResourcefulBox")
    class ResourcefulBox:
        req_res: Optional[str] = ResourceField(
            name="req_res",
            required=True,
        )
        opt_res: Optional[str] = ResourceField(
            name="opt_res",
            required=False,
        )

        @tool()
        def check_resources(self) -> str:
            return f"req_res:{self.req_res}, opt_res:{self.opt_res}"

    return ResourcefulBox


def _make_context(tmp_path: Path, ctx_id: str = "ctx1") -> DocumentContext:
    ctx = DocumentContext(id=ctx_id)
    ctx.save_as(tmp_path / f"{ctx_id}.yml")
    return ctx


def _make_worker(ctx: DocumentContext, toolkit: ToolKit) -> ToolWorker:
    binder = Binder()
    binder.shared_context[ctx.id] = ctx
    worker = ToolWorker(binder=binder, toolkit=toolkit)
    return worker


def _job(
    params_bind_type=ContextBindType.model,
    result_bind_type=ContextBindType.model_output,
    selector: str = "greeter1.greet",
    extra_context_bindings: Optional[list[ContextBind]] = None,
    extra_resource_bindings: Optional[list[ResourceBind]] = None,
) -> Job:
    return Job(
        id="job1",
        context_bindings=[
            ContextBind(binded_id="tool_params", field_id="tool_params", context_bind_type=params_bind_type),
            ContextBind(binded_id="tool_result", field_id="tool_result", context_bind_type=result_bind_type),
            *(extra_context_bindings or []),
        ],
        resource_bindings=[
            ResourceBind(factory_name="toolbox_setup", selector=selector, field_id="toolbox_setup"),
            *(extra_resource_bindings or []),
        ],
    )


# ==============================================================================
# Happy path: plain dict params/result, with input + output context bindings
# ==============================================================================

@pytest.mark.asyncio
@pytest.mark.depends(on=["tests/test_work_worker.py", "tests/test_tooling_registry.py"])
async def test_tool_worker_success_dict_params_with_bindings(tmp_path: Path, greeter_box):
    ctx = _make_context(tmp_path)
    prefix_doc = ctx.create_document(id="prefix_doc", doc_type="text/plain", doc_model="text")
    echo_doc = ctx.create_document(id="echo_doc", doc_type="text/plain", doc_model="text")
    params_doc = ctx.create_document(id="tool_params", doc_type="application/json", doc_model="dict")
    result_doc = ctx.create_document(id="tool_result", doc_type="text/plain", doc_model="text")

    prefix_doc.save("Hello, ")
    echo_doc.save("placeholder")
    params_doc.save({"name": "World"})

    toolkit = ToolKit(toolboxes={"greeter1": ToolBoxSetUp(
        id="greeter1",
        toolbox_name="GreeterBox",
        tools_enabled=["greet"],
    )})
    worker = _make_worker(ctx, toolkit)

    job = _job(extra_context_bindings=[
        ContextBind(binded_id="prefix_doc", field_id="prefix", context_bind_type=ContextBindType.text),
        ContextBind(binded_id="echo_doc", field_id="echo", context_bind_type=ContextBindType.text_output),
    ])

    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    assert result_doc.load() == "Hello, World"
    assert echo_doc.load() == "echoed:World"


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_tool_worker_success_dict_params_with_bindings"])
async def test_tool_worker_optional_context_field_not_bound_is_skipped(tmp_path: Path, greeter_box):
    """`suffix` is optional and has no binding in the job -> no error, just left unset."""
    ctx = _make_context(tmp_path)
    prefix_doc = ctx.create_document(id="prefix_doc", doc_type="text/plain", doc_model="text")
    params_doc = ctx.create_document(id="tool_params", doc_type="application/json", doc_model="dict")
    result_doc = ctx.create_document(id="tool_result", doc_type="text/plain", doc_model="text")

    prefix_doc.save("Hi, ")
    params_doc.save({"name": "Ana"})

    toolkit = ToolKit(toolboxes={"greeter1": ToolBoxSetUp(
        id="greeter1",
        toolbox_name="GreeterBox",
        tools_enabled=["greet"]
    )})
    worker = _make_worker(ctx, toolkit)

    job = _job(extra_context_bindings=[
        ContextBind(binded_id="prefix_doc", field_id="prefix", context_bind_type=ContextBindType.text),
    ])

    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    assert result_doc.load() == "Hi, Ana"


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_tool_worker_success_dict_params_with_bindings"])
async def test_tool_worker_required_context_field_missing_raises(tmp_path: Path, greeter_box):
    """`prefix` is required but has no binding in the job -> ToolWorkerError, before the tool runs."""
    ctx = _make_context(tmp_path)
    params_doc = ctx.create_document(id="tool_params", doc_type="application/json", doc_model="dict")
    ctx.create_document(id="tool_result", doc_type="text/plain", doc_model="text")
    params_doc.save({"name": "Ana"})

    toolkit = ToolKit(toolboxes={"greeter1": ToolBoxSetUp(
        id="greeter1",
        toolbox_name="GreeterBox",
        tools_enabled=["greet"]
    )})
    worker = _make_worker(ctx, toolkit)

    job = _job()

    with pytest.raises(ToolWorkerError, match=r"Context field 'prefix' is required"):
        await worker.run(job)

    assert job.status == JobStatus.CRASHED


# ==============================================================================
# Chat-history driven params/result
# ==============================================================================

@pytest.mark.asyncio
@pytest.mark.depends(on=["test_tool_worker_success_dict_params_with_bindings"])
async def test_tool_worker_chat_history_same_document(tmp_path: Path, greeter_box):
    """params and result point at the *same* chat-history document: the tool call and its
    response should both end up appended to that single conversation."""
    ctx = _make_context(tmp_path)
    prefix_doc = ctx.create_document(id="prefix_doc", doc_type="text/plain", doc_model="text")
    chat_doc = ctx.create_document(id="chat", doc_type="application/json", doc_model="chat-history")
    prefix_doc.save("Hello, ")

    history = ChatHistory(messages=[
        UserMessage(content="please greet Sam"),
        AssistantMessage(tool_calls=[
            ToolCall(id="call_1", function=ToolFunction(
                name="greeter1.greet", arguments=json.dumps({"name": "Sam"}))),
        ]),
    ])
    chat_doc.save(history)

    toolkit = ToolKit(toolboxes={"greeter1": ToolBoxSetUp(
        id="greeter1",
        toolbox_name="GreeterBox",
        tools_enabled=["greet"]
    )})
    worker = _make_worker(ctx, toolkit)

    job = Job(
        id="job_chat",
        context_bindings=[
            ContextBind(binded_id="prefix_doc", field_id="prefix", context_bind_type=ContextBindType.text),
            ContextBind(binded_id="chat", field_id="tool_params", context_bind_type=ContextBindType.model),
            ContextBind(binded_id="chat", field_id="tool_result", context_bind_type=ContextBindType.model_output),
        ],
        resource_bindings=[ResourceBind(factory_name="toolbox_setup", selector="greeter1.greet", field_id="toolbox_setup")],
    )

    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    saved: ChatHistory = chat_doc.load()
    assert len(saved.messages) == 3
    tool_msg = saved.messages[-1]
    assert isinstance(tool_msg, ToolMessage)
    assert tool_msg.tool_call_id == "call_1"
    assert tool_msg.content == "Hello, Sam"


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_tool_worker_chat_history_same_document"])
async def test_tool_worker_chat_history_separate_documents(tmp_path: Path, greeter_box):
    """params and result point at *different* chat-history documents: an existing result
    document should be loaded and appended to, not replaced."""
    ctx = _make_context(tmp_path)
    prefix_doc = ctx.create_document(id="prefix_doc", doc_type="text/plain", doc_model="text")
    params_chat_doc = ctx.create_document(id="in_chat", doc_type="application/json", doc_model="chat-history")
    out_chat_doc = ctx.create_document(id="out_chat", doc_type="application/json", doc_model="chat-history")
    prefix_doc.save("Hey, ")

    params_chat_doc.save(ChatHistory(messages=[
        AssistantMessage(tool_calls=[
            ToolCall(id="call_9", function=ToolFunction(
                name="greeter1.greet", arguments=json.dumps({"name": "Lee"}))),
        ]),
    ]))
    out_chat_doc.save(ChatHistory(messages=[UserMessage(content="pre-existing log entry")]))

    toolkit = ToolKit(toolboxes={"greeter1": ToolBoxSetUp(
        id="greeter1",
        toolbox_name="GreeterBox",
        tools_enabled=["greet"],
    )})
    worker = _make_worker(ctx, toolkit)

    job = Job(
        id="job_chat2",
        context_bindings=[
            ContextBind(binded_id="prefix_doc", field_id="prefix", context_bind_type=ContextBindType.text),
            ContextBind(binded_id="in_chat", field_id="tool_params", context_bind_type=ContextBindType.model),
            ContextBind(binded_id="out_chat", field_id="tool_result", context_bind_type=ContextBindType.model_output),
        ],
        resource_bindings=[ResourceBind(factory_name="toolbox_setup", selector="greeter1.greet", field_id="toolbox_setup")],
    )

    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    # params document is untouched
    assert len(params_chat_doc.load().messages) == 1
    # result document keeps its pre-existing entry and gains the tool response
    saved_out = out_chat_doc.load()
    assert len(saved_out.messages) == 2
    assert saved_out.messages[0].content == "pre-existing log entry"
    assert saved_out.messages[1].content == "Hey, Lee"
    assert saved_out.messages[1].tool_call_id == "call_9"


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_tool_worker_chat_history_same_document"])
async def test_tool_worker_chat_history_no_tool_calls_raises(tmp_path: Path, greeter_box):
    ctx = _make_context(tmp_path)
    prefix_doc = ctx.create_document(id="prefix_doc", doc_type="text/plain", doc_model="text")
    chat_doc = ctx.create_document(id="chat", doc_type="application/json", doc_model="chat-history")
    prefix_doc.save("Hello, ")
    chat_doc.save(ChatHistory(messages=[AssistantMessage(content="no tool calls here")]))

    toolkit = ToolKit(toolboxes={"greeter1": ToolBoxSetUp(
        id="greeter1",
        toolbox_name="GreeterBox",
        tools_enabled=["greet"]
    )})
    worker = _make_worker(ctx, toolkit)

    job = Job(
        id="job_chat_empty",
        context_bindings=[
            ContextBind(binded_id="prefix_doc", field_id="prefix", context_bind_type=ContextBindType.text),
            ContextBind(binded_id="chat", field_id="tool_params", context_bind_type=ContextBindType.model),
            ContextBind(binded_id="chat", field_id="tool_result", context_bind_type=ContextBindType.model_output),
        ],
        resource_bindings=[ResourceBind(factory_name="toolbox_setup", selector="greeter1.greet", field_id="toolbox_setup")],
    )

    with pytest.raises(ToolWorkerError, match="Assistant's tool call is empty"):
        await worker.run(job)

    assert job.status == JobStatus.CRASHED


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_tool_worker_chat_history_same_document"])
async def test_tool_worker_chat_history_no_matching_tool_call_runs_with_no_params(tmp_path: Path, greeter_box):
    """None of the tool_calls match this ToolBoxSetUp's id/tool: params stays None and
    the zero-arg 'ping' tool still runs fine with no arguments."""
    ctx = _make_context(tmp_path)
    prefix_doc = ctx.create_document(id="prefix_doc", doc_type="text/plain", doc_model="text")
    chat_doc = ctx.create_document(id="chat", doc_type="application/json", doc_model="chat-history")
    prefix_doc.save("Hello, ")
    chat_doc.save(ChatHistory(messages=[
        AssistantMessage(tool_calls=[
            ToolCall(id="call_x", function=ToolFunction(name="other.other", arguments="{}")),
        ]),
    ]))

    toolkit = ToolKit(toolboxes={"greeter1": ToolBoxSetUp(
        id="greeter1",
        toolbox_name="GreeterBox",
        tools_enabled=["ping"]
    )})
    worker = _make_worker(ctx, toolkit)

    job = Job(
        id="job_chat_nomatch",
        context_bindings=[
            ContextBind(binded_id="prefix_doc", field_id="prefix", context_bind_type=ContextBindType.text),
            ContextBind(binded_id="chat", field_id="tool_params", context_bind_type=ContextBindType.model),
            ContextBind(binded_id="chat", field_id="tool_result", context_bind_type=ContextBindType.model_output),
        ],
        resource_bindings=[ResourceBind(factory_name="toolbox_setup", selector="greeter1.ping", field_id="toolbox_setup")],
    )

    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    saved = chat_doc.load()
    tool_msg = saved.messages[-1]
    assert tool_msg.content == "pong"
    assert tool_msg.tool_call_id == "no-id"


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_tool_worker_chat_history_same_document"])
async def test_tool_worker_chat_history_new_file_creation(tmp_path: Path, greeter_box):
    """Covers `chat_history = ChatHistory()` when result_doc is chat-history,
    does not exist on disk yet, and params_doc is not chat-history.
    """
    ctx = _make_context(tmp_path)
    prefix_doc = ctx.create_document(id="prefix_doc", doc_type="text/plain", doc_model="text")
    params_doc = ctx.create_document(id="tool_params", doc_type="application/json", doc_model="dict")
    # Reference created, but file not saved to disk -> doc_path.exists() is False
    result_chat_doc = ctx.create_document(id="new_chat", doc_type="application/json", doc_model="chat-history")

    prefix_doc.save("Hello, ")
    params_doc.save({"name": "NewUser"})

    toolkit = ToolKit(toolboxes={"greeter1": ToolBoxSetUp(
        id="greeter1",
        toolbox_name="GreeterBox",
        tools_enabled=["greet"]
    )})
    worker = _make_worker(ctx, toolkit)

    job = Job(
        id="job_new_chat",
        context_bindings=[
            ContextBind(binded_id="prefix_doc", field_id="prefix", context_bind_type=ContextBindType.text),
            ContextBind(binded_id="tool_params", field_id="tool_params", context_bind_type=ContextBindType.model),
            ContextBind(binded_id="new_chat", field_id="tool_result", context_bind_type=ContextBindType.model_output),
        ],
        resource_bindings=[ResourceBind(factory_name="toolbox_setup", selector="greeter1.greet", field_id="toolbox_setup")],
    )

    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    saved: ChatHistory = result_chat_doc.load()
    assert len(saved.messages) == 1
    assert saved.messages[0].content == "Hello, NewUser"


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_tool_worker_chat_history_same_document"])
async def test_tool_worker_chat_history_user_message_only_raises(tmp_path: Path, greeter_box):
    """Chat history contains only a UserMessage -> break on UserMessage and raise."""
    ctx = _make_context(tmp_path)
    prefix_doc = ctx.create_document(id="prefix_doc", doc_type="text/plain", doc_model="text")
    chat_doc = ctx.create_document(id="chat", doc_type="application/json", doc_model="chat-history")
    prefix_doc.save("Hi, ")
    chat_doc.save(ChatHistory(messages=[UserMessage(content="Hello")]))

    toolkit = ToolKit(toolboxes={"greeter1": ToolBoxSetUp(
        id="greeter1",
        toolbox_name="GreeterBox",
        tools_enabled=["ping"]
    )})
    worker = _make_worker(ctx, toolkit)

    job = Job(
        id="job_chat_user",
        context_bindings=[
            ContextBind(binded_id="prefix_doc", field_id="prefix", context_bind_type=ContextBindType.text),
            ContextBind(binded_id="chat", field_id="tool_params", context_bind_type=ContextBindType.model),
            ContextBind(binded_id="chat", field_id="tool_result", context_bind_type=ContextBindType.model_output),
        ],
        resource_bindings=[ResourceBind(factory_name="toolbox_setup", selector="greeter1.ping", field_id="toolbox_setup")],
    )

    with pytest.raises(ToolWorkerError, match="Assistant's message not found"):
        await worker.run(job)

    assert job.status == JobStatus.CRASHED


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_tool_worker_chat_history_same_document"])
async def test_tool_worker_chat_history_empty_raises(tmp_path: Path, greeter_box):
    """Empty chat history -> no break, but assistant_message remains None and raise."""
    ctx = _make_context(tmp_path)
    prefix_doc = ctx.create_document(id="prefix_doc", doc_type="text/plain", doc_model="text")
    chat_doc = ctx.create_document(id="chat", doc_type="application/json", doc_model="chat-history")
    prefix_doc.save("Hi, ")
    chat_doc.save(ChatHistory(messages=[]))  # empty history

    toolkit = ToolKit(toolboxes={"greeter1": ToolBoxSetUp(
        id="greeter1",
        toolbox_name="GreeterBox",
        tools_enabled=["ping"]
    )})
    worker = _make_worker(ctx, toolkit)

    job = Job(
        id="job_chat_empty",
        context_bindings=[
            ContextBind(binded_id="prefix_doc", field_id="prefix", context_bind_type=ContextBindType.text),
            ContextBind(binded_id="chat", field_id="tool_params", context_bind_type=ContextBindType.model),
            ContextBind(binded_id="chat", field_id="tool_result", context_bind_type=ContextBindType.model_output),
        ],
        resource_bindings=[ResourceBind(factory_name="toolbox_setup", selector="greeter1.ping", field_id="toolbox_setup")],
    )

    with pytest.raises(ToolWorkerError, match="Assistant's message not found"):
        await worker.run(job)

    assert job.status == JobStatus.CRASHED


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_tool_worker_chat_history_same_document"])
async def test_tool_worker_chat_history_formatting_and_input_only_fields(tmp_path: Path, multi_type_box):
    """Covers dict, BaseModel, and primitive formatting branches when saving to chat history,
    as well as skipping input-only fields (`continue`) during output binding serialization.
    """
    ctx = _make_context(tmp_path)
    params_doc = ctx.create_document(id="tool_params", doc_type="application/json", doc_model="dict")
    params_doc.save({})

    toolkit = ToolKit(toolboxes={"box1": ToolBoxSetUp(
        id="box1",
        toolbox_name="MultiTypeBox",
        tools_enabled=["return_dict", "return_model", "return_primitive"]
    )})
    worker = _make_worker(ctx, toolkit)

    # 1. Dict result formatting + triggers continue for input_only field in MultiTypeBox
    result_dict_doc = ctx.create_document(id="chat_dict", doc_type="application/json", doc_model="chat-history")
    job_dict = Job(
        id="job_dict",
        context_bindings=[
            ContextBind(binded_id="tool_params", field_id="tool_params", context_bind_type=ContextBindType.model),
            ContextBind(binded_id="chat_dict", field_id="tool_result", context_bind_type=ContextBindType.model_output),
        ],
        resource_bindings=[ResourceBind(factory_name="toolbox_setup", selector="box1.return_dict", field_id="toolbox_setup")],
    )
    await worker.run(job_dict)
    assert job_dict.status == JobStatus.FINISHED
    saved_dict: ChatHistory = result_dict_doc.load()
    assert saved_dict.messages[-1].content == json.dumps({"status": "ok", "count": 1}, indent=2, ensure_ascii=False)

    # 2. BaseModel result formatting
    result_model_doc = ctx.create_document(id="chat_model", doc_type="application/json", doc_model="chat-history")
    job_model = Job(
        id="job_model",
        context_bindings=[
            ContextBind(binded_id="tool_params", field_id="tool_params", context_bind_type=ContextBindType.model),
            ContextBind(binded_id="chat_model", field_id="tool_result", context_bind_type=ContextBindType.model_output),
        ],
        resource_bindings=[ResourceBind(factory_name="toolbox_setup", selector="box1.return_model", field_id="toolbox_setup")],
    )
    await worker.run(job_model)
    assert job_model.status == JobStatus.FINISHED
    saved_model: ChatHistory = result_model_doc.load()
    assert saved_model.messages[-1].content == SampleModel(data="test_value").model_dump_json(indent=2, ensure_ascii=False)

    # 3. Primitive (e.g. int) result formatting
    result_int_doc = ctx.create_document(id="chat_int", doc_type="application/json", doc_model="chat-history")
    job_int = Job(
        id="job_int",
        context_bindings=[
            ContextBind(binded_id="tool_params", field_id="tool_params", context_bind_type=ContextBindType.model),
            ContextBind(binded_id="chat_int", field_id="tool_result", context_bind_type=ContextBindType.model_output),
        ],
        resource_bindings=[ResourceBind(factory_name="toolbox_setup", selector="box1.return_primitive", field_id="toolbox_setup")],
    )
    await worker.run(job_int)
    assert job_int.status == JobStatus.FINISHED
    saved_int: ChatHistory = result_int_doc.load()
    assert saved_int.messages[-1].content == "12345"


# ==============================================================================
# toolbox_setup resource factory / selector handling
# ==============================================================================

@pytest.mark.asyncio
@pytest.mark.depends(on=["test_tool_worker_success_dict_params_with_bindings"])
async def test_tool_worker_missing_selector_raises(tmp_path: Path, greeter_box):
    ctx = _make_context(tmp_path)
    ctx.create_document(id="tool_params", doc_type="application/json", doc_model="dict").save({"name": "x"})
    ctx.create_document(id="tool_result", doc_type="text/plain", doc_model="text")

    toolkit = ToolKit(toolboxes={"greeter1": ToolBoxSetUp(id="greeter1", toolbox_name="GreeterBox")})
    worker = _make_worker(ctx, toolkit)

    job = _job(selector="")

    with pytest.raises(ToolWorkerError, match="Missing toolbox selector"):
        await worker.run(job)


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_tool_worker_success_dict_params_with_bindings"])
async def test_tool_worker_bad_selector_format_raises(tmp_path: Path, greeter_box):
    ctx = _make_context(tmp_path)
    ctx.create_document(id="tool_params", doc_type="application/json", doc_model="dict").save({"name": "x"})
    ctx.create_document(id="tool_result", doc_type="text/plain", doc_model="text")

    toolkit = ToolKit(toolboxes={"greeter1": ToolBoxSetUp(id="greeter1", toolbox_name="GreeterBox")})
    worker = _make_worker(ctx, toolkit)

    job = _job(selector="GreeterBoxOnly")

    with pytest.raises(ToolWorkerError, match="Wrong selector format"):
        await worker.run(job)


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_tool_worker_success_dict_params_with_bindings"])
async def test_tool_worker_unknown_toolbox_in_toolkit_raises(tmp_path: Path, greeter_box):
    ctx = _make_context(tmp_path)
    ctx.create_document(id="tool_params", doc_type="application/json", doc_model="dict").save({"name": "x"})
    ctx.create_document(id="tool_result", doc_type="text/plain", doc_model="text")

    toolkit = ToolKit(toolboxes={"greeter1": ToolBoxSetUp(id="greeter1", toolbox_name="GreeterBox")})
    worker = _make_worker(ctx, toolkit)

    job = _job(selector="NotConfiguredBox.greet")

    with pytest.raises(ToolWorkerError, match="Unknown toolbox 'NotConfiguredBox'"):
        await worker.run(job)


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_tool_worker_success_dict_params_with_bindings"])
async def test_tool_worker_unknown_tool_on_toolbox_raises(tmp_path: Path, greeter_box):
    ctx = _make_context(tmp_path)
    ctx.create_document(id="tool_params", doc_type="application/json", doc_model="dict").save({"name": "x"})
    ctx.create_document(id="tool_result", doc_type="text/plain", doc_model="text")

    toolkit = ToolKit(toolboxes={"greeter1": ToolBoxSetUp(id="greeter1", toolbox_name="GreeterBox")})
    worker = _make_worker(ctx, toolkit)

    job = _job(selector="greeter1.nonexistent")

    with pytest.raises(ToolWorkerError, match="Tool 'nonexistent' not found in ToolBox 'greeter1'"):
        await worker.run(job)


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_tool_worker_success_dict_params_with_bindings"])
async def test_tool_worker_disabled_tool_on_toolbox_raises(tmp_path: Path, greeter_box):
    ctx = _make_context(tmp_path)
    ctx.create_document(id="tool_params", doc_type="application/json", doc_model="dict").save({"name": "x"})
    ctx.create_document(id="tool_result", doc_type="text/plain", doc_model="text")

    toolkit = ToolKit(toolboxes={"greeter1": ToolBoxSetUp(id="greeter1", toolbox_name="GreeterBox")})
    worker = _make_worker(ctx, toolkit)

    job = _job(selector="greeter1.greet")

    with pytest.raises(ToolWorkerError, match="Tool 'greet' not enabled for ToolBox 'greeter1'"):
        await worker.run(job)


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_tool_worker_success_dict_params_with_bindings"])
async def test_tool_worker_selector_lookup_leaves_toolkit_entry_untouched(tmp_path: Path, greeter_box):
    """Regression test: resolving a selector must not mutate the ToolBoxSetUp stored on the
    ToolKit (this used to crash with a RecursionError from an unsafe deepcopy)."""
    ctx = _make_context(tmp_path)
    prefix_doc = ctx.create_document(id="prefix_doc", doc_type="text/plain", doc_model="text")
    params_doc = ctx.create_document(id="tool_params", doc_type="application/json", doc_model="dict")
    ctx.create_document(id="tool_result", doc_type="text/plain", doc_model="text")
    prefix_doc.save("Hi, ")
    params_doc.save({"name": "A"})

    toolkit = ToolKit(toolboxes={"greeter1": ToolBoxSetUp(
        id="greeter1",
        toolbox_name="GreeterBox",
        tools_enabled=["greet", "ping"]
    )})
    worker = _make_worker(ctx, toolkit)

    job = _job(extra_context_bindings=[
        ContextBind(binded_id="prefix_doc", field_id="prefix", context_bind_type=ContextBindType.text),
    ])
    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    # the ToolKit's own stored setup was never mutated with an active_tool
    assert toolkit.toolboxes["greeter1"].active_tool is None

    # and running it again (e.g. for a different tool) still works
    params_doc.save({"name": "B"})
    job2 = _job(selector="greeter1.ping", extra_context_bindings=[
        ContextBind(binded_id="prefix_doc", field_id="prefix", context_bind_type=ContextBindType.text),
    ])
    await worker.run(job2)
    assert job2.status == JobStatus.FINISHED


# ==============================================================================
# Resource bindings
# ==============================================================================

@pytest.mark.asyncio
@pytest.mark.depends(on=["test_tool_worker_required_context_field_missing_raises"])
async def test_tool_worker_resource_bindings(tmp_path: Path, resourceful_box):
    ctx = _make_context(tmp_path)
    params_doc = ctx.create_document(id="tool_params", doc_type="application/json", doc_model="dict")
    result_doc = ctx.create_document(id="tool_result", doc_type="text/plain", doc_model="text")
    params_doc.save({"name": "A"})

    toolkit = ToolKit(toolboxes={"resourceful_1": ToolBoxSetUp(
        id="resourceful_1",
        toolbox_name="ResourcefulBox",
        tools_enabled=["check_resources"]
    )})
    worker = _make_worker(ctx, toolkit)

    @worker.resource(name="in_parentheses")
    def in_parentheses(text):
        return f"({text})"

    assert "in_parentheses" in worker.factories.keys()

    binding1 = ResourceBind(field_id="req_res", factory_name="in_parentheses", selector="req")
    binding2 = ResourceBind(field_id="opt_res", factory_name="in_parentheses", selector="opt")
    job = _job(selector="resourceful_1.check_resources", extra_resource_bindings=[binding1, binding2])
    await worker.run(job)

    assert result_doc.load() == "req_res:(req), opt_res:(opt)"
    assert job.status == JobStatus.FINISHED

@pytest.mark.asyncio
@pytest.mark.depends(on=["test_tool_worker_required_context_field_missing_raises"])
async def test_tool_worker_resource_bindings(tmp_path: Path, resourceful_box):
    ctx = _make_context(tmp_path)
    params_doc = ctx.create_document(id="tool_params", doc_type="application/json", doc_model="dict")
    result_doc = ctx.create_document(id="tool_result", doc_type="text/plain", doc_model="text")
    params_doc.save({"name": "A"})

    toolkit = ToolKit(toolboxes={"resourceful_1": ToolBoxSetUp(
        id="resourceful_1",
        toolbox_name="ResourcefulBox",
        tools_enabled=["check_resources"]
    )})
    worker = _make_worker(ctx, toolkit)

    @worker.binder.resource(name="in_parentheses")
    def in_parentheses(text):
        return f"({text})"

    assert "in_parentheses" in worker.binder.factories.keys()

    binding1 = ResourceBind(field_id="req_res", factory_name="in_parentheses", selector="req")

    job = _job(selector="resourceful_1.check_resources", extra_resource_bindings=[binding1])
    await worker.run(job)

    assert result_doc.load() == "req_res:(req), opt_res:None"
    assert job.status == JobStatus.FINISHED

    job_err = _job(selector="resourceful_1.check_resources")
    with pytest.raises(ToolWorkerError, match="Context field 'req_res' is required for ToolBox 'ResourcefulBox'"):
        await worker.run(job_err)