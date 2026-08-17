import json
from pathlib import Path
from typing import Optional

import pytest
from pydantic import BaseModel
from werkzeug.wrappers import Response

from datorum.agency.exceptions import AgentWorkerError
from datorum.agency.settings import AgencyKit, AgentRole, InferenceServiceProvider
from datorum.agency.worker import AgentWorker
from datorum.binding.binder import Binder
from datorum.context.commons.chat import ChatHistory, SystemMessage, UserMessage
from datorum.context.registry import DocumentModelRegistry, register_doc_model
from datorum.context.settings import (
    ContextBind,
    ContextBindType,
    DocumentContext,
    ResourceBind,
)
from datorum.tooling.registry import ToolBoxRegistry, tool, toolbox
from datorum.tooling.settings import ToolBoxSetUp, ToolKit
from datorum.tooling.worker import ToolWorker
from datorum.work.job import Job, JobStatus


# ==============================================================================
# Fixtures / helpers
# ==============================================================================

@pytest.fixture(autouse=True)
def clear_toolbox_registry():
    """Clear and restore the global ToolBoxRegistry before and after each test."""
    original = ToolBoxRegistry.copy()
    ToolBoxRegistry.clear()
    yield
    ToolBoxRegistry.clear()
    ToolBoxRegistry.update(original)


@pytest.fixture(autouse=True)
def clear_doc_model_registry():
    """Clear and restore the global DocumentModelRegistry before and after each test."""
    original = DocumentModelRegistry.copy()
    yield
    DocumentModelRegistry.clear()
    DocumentModelRegistry.update(original)


def _make_context(tmp_path: Path, ctx_id: str = "ctx1") -> DocumentContext:
    ctx = DocumentContext(id=ctx_id)
    ctx.save_as(tmp_path / f"{ctx_id}.yml")
    return ctx


def _make_agent_worker(
    ctx: DocumentContext,
    agencykit: AgencyKit,
    toolkit: Optional[ToolKit] = None,
    api_key: str = "test-api-key",
) -> tuple[AgentWorker, ToolWorker]:
    """Build an AgentWorker + ToolWorker pair wired to the same context, with a
    stubbed `api_key` resource factory (a real deployment would resolve this
    from a secrets store, which is out of scope here)."""
    binder: Binder = Binder()
    binder.contexts[ctx.id] = ctx
    tool_worker = ToolWorker(binder=binder, toolkit=toolkit or ToolKit())
    worker = AgentWorker(binder=binder, agencykit=agencykit, tool_worker=tool_worker)

    @binder.resource(name="api_key")
    def _api_key(selector: Optional[str]) -> str:
        return api_key

    return worker, tool_worker


def _provider(
    id: str = "provider1",
    base_url: str = "http://localhost/v1/",
    models: Optional[list[str]] = None,
    supports_streaming: bool = True,
    api_key_selector: Optional[str] = None,
) -> InferenceServiceProvider:
    return InferenceServiceProvider(
        id=id,
        base_url=base_url,
        models=models if models is not None else ["gpt-test"],
        supports_streaming=supports_streaming,
        api_key_selector=api_key_selector,
    )


def _role(
    id: str = "role1",
    preferred_models: Optional[list[str]] = None,
    tools_enabled: Optional[list[str]] = None,
    tool_choice: str = "auto",
    tool_max_iter: int = 3,
    output_doc_model: Optional[str] = None,
) -> AgentRole:
    return AgentRole(
        id=id,
        preferred_models=preferred_models if preferred_models is not None else ["gpt-test"],
        tools_enabled=tools_enabled or [],
        tool_choice=tool_choice,
        tool_max_iter=tool_max_iter,
        output_doc_model=output_doc_model,
    )


def _agent_job(
    role_selector: str = "role1",
    provider_selector: Optional[str] = "__unset__",
    chat_binded_id: str = "chat_doc",
    chat_bind_type: ContextBindType = ContextBindType.model,
    job_id: str = "job1",
    include_role_binding: bool = True,
    include_chat_binding: bool = True,
) -> Job:
    """`provider_selector="__unset__"` (the default) omits the inference_provider
    resource binding entirely, exercising the get_preferred_provider() fallback."""
    resource_bindings = []
    if include_role_binding:
        resource_bindings.append(
            ResourceBind(field_id="agent_role", factory_name="agent_role", selector=role_selector)
        )
    if provider_selector != "__unset__":
        resource_bindings.append(
            ResourceBind(field_id="inference_provider", factory_name="inference_provider", selector=provider_selector)
        )
    context_bindings = []
    if include_chat_binding:
        context_bindings.append(
            ContextBind(field_id="chat_history", binded_id=chat_binded_id, context_bind_type=chat_bind_type)
        )
    return Job(id=job_id, context_bindings=context_bindings, resource_bindings=resource_bindings)


def _sse(events: list[dict], done: bool = True) -> str:
    """Build a Server-Sent-Events body from a list of JSON-able event dicts."""
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events)
    if done:
        body += "data: [DONE]\n\n"
    return body


def _sse_response(body: str) -> Response:
    return Response(body, mimetype="text/event-stream")


class AgentToolParams(BaseModel):
    name: str


@pytest.fixture
def agent_toolbox():
    @toolbox(name="AgentGreeterBox")
    class AgentGreeterBox:
        @tool()
        def greet(self, params: AgentToolParams) -> str:
            return f"Hello, {params.name}!"

    return AgentGreeterBox


@pytest.fixture
def second_agent_toolbox():
    @toolbox(name="AgentSecondBox")
    class AgentSecondBox:
        @tool()
        def shout(self, params: AgentToolParams) -> str:
            return f"{params.name.upper()}!!!"

    return AgentSecondBox


class SimpleOutputModel(BaseModel):
    answer: str


class NestedOutputModel(BaseModel):
    inner: SimpleOutputModel
    tags: list[str]


# ==============================================================================
# get_role / get_provider / get_preferred_provider / _select_model
# ==============================================================================

def test_get_role_success(tmp_path):
    ctx = _make_context(tmp_path)
    role = _role(id="role1")
    agencykit = AgencyKit(providers={}, roles={"role1": role})
    worker, _ = _make_agent_worker(ctx, agencykit)

    assert worker.get_role("role1") is role


def test_get_role_not_found(tmp_path):
    ctx = _make_context(tmp_path)
    agencykit = AgencyKit(providers={}, roles={})
    worker, _ = _make_agent_worker(ctx, agencykit)

    with pytest.raises(AgentWorkerError, match="Role not found: 'missing'"):
        worker.get_role("missing")


def test_get_provider_success(tmp_path):
    ctx = _make_context(tmp_path)
    provider = _provider(id="provider1")
    agencykit = AgencyKit(providers={"provider1": provider}, roles={})
    worker, _ = _make_agent_worker(ctx, agencykit)

    assert worker.get_provider("provider1") is provider


def test_get_provider_not_found(tmp_path):
    ctx = _make_context(tmp_path)
    agencykit = AgencyKit(providers={}, roles={})
    worker, _ = _make_agent_worker(ctx, agencykit)

    with pytest.raises(AgentWorkerError, match="Provider not found: 'missing'"):
        worker.get_provider("missing")


def test_get_preferred_provider_success(tmp_path):
    ctx = _make_context(tmp_path)
    provider_a = _provider(id="provider_a", models=["model-x"])
    provider_b = _provider(id="provider_b", models=["model-y", "model-z"])
    agencykit = AgencyKit(providers={"provider_a": provider_a, "provider_b": provider_b}, roles={})
    worker, _ = _make_agent_worker(ctx, agencykit)

    # "model-y" only exists on provider_b
    assert worker.get_preferred_provider(["model-y"]) is provider_b
    # first preferred model wins even if a later one also matches another provider
    assert worker.get_preferred_provider(["model-x", "model-y"]) is provider_a


def test_get_preferred_provider_not_found(tmp_path):
    ctx = _make_context(tmp_path)
    provider_a = _provider(id="provider_a", models=["model-x"])
    agencykit = AgencyKit(providers={"provider_a": provider_a}, roles={})
    worker, _ = _make_agent_worker(ctx, agencykit)

    with pytest.raises(AgentWorkerError, match=r"No provider found for models: \['nope'\]"):
        worker.get_preferred_provider(["nope"])


def test_select_model_success(tmp_path):
    ctx = _make_context(tmp_path)
    agencykit = AgencyKit(providers={}, roles={})
    worker, _ = _make_agent_worker(ctx, agencykit)

    provider = _provider(id="provider1", models=["model-a", "model-b"])
    role = _role(id="role1", preferred_models=["model-nope", "model-b"])

    assert worker._select_model(role, provider) == "model-b"


def test_select_model_not_found(tmp_path):
    ctx = _make_context(tmp_path)
    agencykit = AgencyKit(providers={}, roles={})
    worker, _ = _make_agent_worker(ctx, agencykit)

    provider = _provider(id="provider1", models=["model-a"])
    role = _role(id="role1", preferred_models=["model-z"])

    with pytest.raises(
        AgentWorkerError,
        match="Can not determine model for role 'role1' on provider 'provider1'",
    ):
        worker._select_model(role, provider)


# ==============================================================================
# _strict_json_schema
# ==============================================================================

def test_strict_json_schema_recursive(tmp_path):
    ctx = _make_context(tmp_path)
    agencykit = AgencyKit(providers={}, roles={})
    worker, _ = _make_agent_worker(ctx, agencykit)

    schema = {
        "title": "Root",
        "type": "object",
        "properties": {
            "name": {"type": "string", "title": "Name", "default": "x"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "title": "Item",
                    "properties": {"n": {"type": "integer"}},
                },
            },
            "choice": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "either": {"oneOf": [{"type": "string", "title": "S"}]},
            "combo": {"allOf": [{"type": "string", "default": "z"}]},
        },
    }

    result = worker._strict_json_schema(schema)

    assert result is schema  # mutated in place and returned
    assert "title" not in result
    assert result["additionalProperties"] is False
    assert result["required"] == ["name", "items", "choice", "either", "combo"]

    # simple property: title/default stripped
    assert "title" not in result["properties"]["name"]
    assert "default" not in result["properties"]["name"]

    # array -> items recursed into (object gets additionalProperties/required too)
    item_schema = result["properties"]["items"]["items"]
    assert "title" not in item_schema
    assert item_schema["additionalProperties"] is False
    assert item_schema["required"] == ["n"]

    # anyOf / oneOf / allOf: every sub-schema recursed into
    assert result["properties"]["choice"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert "title" not in result["properties"]["either"]["oneOf"][0]
    assert "default" not in result["properties"]["combo"]["allOf"][0]


# ==============================================================================
# _toolkit_schema
# ==============================================================================

def test_toolkit_schema_builds_and_namespaces_function_names(tmp_path, agent_toolbox):
    ctx = _make_context(tmp_path)
    toolkit = ToolKit(toolboxes={
        "box1": ToolBoxSetUp(id="box1", toolbox_name="AgentGreeterBox", tools_enabled=["greet"]),
    })
    agencykit = AgencyKit(providers={}, roles={})
    worker, _tool_worker = _make_agent_worker(ctx, agencykit, toolkit=toolkit)

    role = _role(tools_enabled=["box1.greet"])
    result = worker._toolkit_schema(role)

    assert len(result) == 1
    entry = result[0]
    assert entry["type"] == "function"
    assert "name" not in entry  # ToolDefinition.name is excluded from the dump
    assert entry["function"]["name"] == "box1.greet"
    assert entry["function"]["parameters"]["properties"].keys() == {"name"}


def test_toolkit_schema_empty_when_no_tools_enabled(tmp_path):
    ctx = _make_context(tmp_path)
    agencykit = AgencyKit(providers={}, roles={})
    worker, _ = _make_agent_worker(ctx, agencykit)

    assert worker._toolkit_schema(_role(tools_enabled=[])) == []


# ==============================================================================
# _response_format
# ==============================================================================

def test_response_format_without_defs(tmp_path):
    ctx = _make_context(tmp_path)
    agencykit = AgencyKit(providers={}, roles={})
    worker, _ = _make_agent_worker(ctx, agencykit)

    result = worker._response_format(SimpleOutputModel, name="simple-output")

    assert result["type"] == "json_schema"
    assert result["json_schema"]["name"] == "simple-output"
    assert result["json_schema"]["strict"] is True
    schema = result["json_schema"]["schema"]
    assert "$defs" not in schema
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["answer"]


def test_response_format_with_defs_and_default_name(tmp_path):
    ctx = _make_context(tmp_path)
    agencykit = AgencyKit(providers={}, roles={})
    worker, _ = _make_agent_worker(ctx, agencykit)

    result = worker._response_format(NestedOutputModel)

    assert result["json_schema"]["name"] == "NestedOutputModel"
    schema = result["json_schema"]["schema"]
    assert "$defs" in schema
    inner_def = schema["$defs"]["SimpleOutputModel"]
    # nested $defs schemas are also strictified
    assert inner_def["additionalProperties"] is False
    assert inner_def["required"] == ["answer"]
    assert schema["additionalProperties"] is False


# ==============================================================================
# _call_streamer
# ==============================================================================

@pytest.mark.asyncio
async def test_call_streamer_success_content_and_response_meta(tmp_path, httpserver):
    ctx = _make_context(tmp_path)
    provider = _provider(base_url=httpserver.url_for("/v1/"))
    agencykit = AgencyKit(providers={"provider1": provider}, roles={})
    worker, _ = _make_agent_worker(ctx, agencykit)
    job = Job(id="job1")

    body = (
        "data: " + json.dumps({"id": "chatcmpl-1", "model": "gpt-test", "choices": [{"delta": {"role": "assistant"}}]}) + "\n\n"
        "data: " + json.dumps({"id": "chatcmpl-1", "choices": [{"delta": {"content": "Hel"}}]}) + "\n\n"
        ": keep-alive\n\n"
        "data: " + json.dumps({"choices": [{"delta": {"content": "lo"}}]}) + "\n\n"
        # id is None here -> must NOT overwrite the previously captured "chatcmpl-1"
        "data: " + json.dumps({"id": None, "choices": [{"delta": {}, "finish_reason": "stop"}]}) + "\n\n"
        "data: [DONE]\n\n"
    )
    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_response(_sse_response(body))

    message, response_meta = await worker._call_streamer(
        request_payload={"model": "gpt-test", "messages": {"messages": []}},
        provider=provider,
        api_key="key-123",
        job=job,
    )

    assert message == {"role": "assistant", "content": "Hello"}
    assert response_meta["id"] == "chatcmpl-1"
    assert response_meta["model"] == "gpt-test"
    assert response_meta["finish_reason"] == "stop"
    assert job.is_streaming is False
    assert job.chunk_broadcaster.history == ["Hel", "lo"]

    sent = httpserver.log[0][0].get_json()
    assert sent["stream"] is True
    assert sent["messages"] == {"messages": []}
    assert httpserver.log[0][0].headers["Authorization"] == "Bearer key-123"


@pytest.mark.asyncio
async def test_call_streamer_tool_calls_sorted_and_extra_parts(tmp_path, httpserver):
    ctx = _make_context(tmp_path)
    provider = _provider(base_url=httpserver.url_for("/v1/"))
    agencykit = AgencyKit(providers={"provider1": provider}, roles={})
    worker, _ = _make_agent_worker(ctx, agencykit)
    job = Job(id="job1")

    events = [
        # tool call chunk arrives for index 1 BEFORE index 0 -> output must still be sorted
        {
            "choices": [{
                "delta": {
                    "tool_calls": [
                        {"index": 1, "id": "call_1", "function": {"name": "box1.sh", "arguments": ""}},
                    ],
                    "reasoning_content": "thinking a",
                    "custom_meta": {"step": 1},
                },
            }]
        },
        {
            "choices": [{
                "delta": {
                    "tool_calls": [
                        {"index": 0, "id": "call_0", "function": {"name": "box1.gr", "arguments": ""}},
                        {"index": 1, "function": {"arguments": "out"}},
                    ],
                    "reasoning_content": "thinking b",
                    "custom_meta": {"step": 2},
                },
            }]
        },
        {
            "choices": [{
                "delta": {
                    "tool_calls": [
                        {"index": 0, "function": {"arguments": '{"n":1}'}},
                    ],
                },
                "finish_reason": "tool_calls",
            }]
        },
    ]
    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_response(
        _sse_response(_sse(events))
    )

    message, response_meta = await worker._call_streamer(
        request_payload={"model": "gpt-test", "messages": {}},
        provider=provider,
        api_key="key",
        job=job,
    )

    # no "content" delta was ever seen -> falls back to None
    assert message["content"] is None
    # extra string deltas accumulate; non-string extras just get overwritten
    assert message["reasoning_content"] == "thinking athinking b"
    assert message["custom_meta"] == {"step": 2}
    assert response_meta["finish_reason"] == "tool_calls"

    assert message["tool_calls"] == [
        {"id": "call_0", "type": "function", "function": {"name": "box1.gr", "arguments": '{"n":1}'}},
        {"id": "call_1", "type": "function", "function": {"name": "box1.sh", "arguments": "out"}},
    ]


@pytest.mark.asyncio
async def test_call_streamer_http_error_wraps_and_resets_streaming_flag(tmp_path, httpserver):
    ctx = _make_context(tmp_path)
    provider = _provider(id="flaky", base_url=httpserver.url_for("/v1/"))
    agencykit = AgencyKit(providers={"flaky": provider}, roles={})
    worker, _ = _make_agent_worker(ctx, agencykit)
    job = Job(id="job1")

    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_data("boom", status=500)

    with pytest.raises(AgentWorkerError, match="Failed to call inference provider 'flaky'"):
        await worker._call_streamer(
            request_payload={"model": "gpt-test", "messages": {}},
            provider=provider,
            api_key="key",
            job=job,
        )

    assert job.is_streaming is False


# ==============================================================================
# _call_fetcher
# ==============================================================================

@pytest.mark.asyncio
async def test_call_fetcher_success(tmp_path, httpserver):
    ctx = _make_context(tmp_path)
    provider = _provider(base_url=httpserver.url_for("/v1/"), supports_streaming=False)
    agencykit = AgencyKit(providers={"provider1": provider}, roles={})
    worker, _ = _make_agent_worker(ctx, agencykit)
    job = Job(id="job1")

    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_json({
        "id": "chatcmpl-9",
        "model": "gpt-test",
        "usage": None,
        "choices": [{
            "message": {"role": "assistant", "content": "hi there"},
            "finish_reason": "stop",
        }],
    })

    message, response_meta = await worker._call_fetcher(
        request_payload={"model": "gpt-test", "messages": {}},
        provider=provider,
        api_key="key-abc",
        job=job,
    )

    assert message == {"role": "assistant", "content": "hi there"}
    assert response_meta["finish_reason"] == "stop"
    assert response_meta["id"] == "chatcmpl-9"
    assert response_meta["model"] == "gpt-test"
    assert "usage" not in response_meta  # None values excluded
    assert "choices" not in response_meta

    assert httpserver.log[0][0].headers["Authorization"] == "Bearer key-abc"


@pytest.mark.asyncio
async def test_call_fetcher_http_error_wraps(tmp_path, httpserver):
    ctx = _make_context(tmp_path)
    provider = _provider(id="flaky", base_url=httpserver.url_for("/v1/"), supports_streaming=False)
    agencykit = AgencyKit(providers={"flaky": provider}, roles={})
    worker, _ = _make_agent_worker(ctx, agencykit)
    job = Job(id="job1")

    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_data("nope", status=503)

    with pytest.raises(AgentWorkerError, match="Failed to call inference provider 'flaky'"):
        await worker._call_fetcher(
            request_payload={"model": "gpt-test", "messages": {}},
            provider=provider,
            api_key="key",
            job=job,
        )


# ==============================================================================
# work() - validation errors
# ==============================================================================

@pytest.mark.asyncio
async def test_work_wrong_chat_bind_type_raises(tmp_path):
    ctx = _make_context(tmp_path)
    agencykit = AgencyKit(providers={"provider1": _provider()}, roles={"role1": _role()})
    worker, _ = _make_agent_worker(ctx, agencykit)

    job = _agent_job(provider_selector="provider1", chat_bind_type=ContextBindType.text)

    with pytest.raises(AgentWorkerError, match="must be binded to an input-output model"):
        await worker.run(job)


@pytest.mark.asyncio
async def test_work_empty_chat_history_raises(tmp_path):
    ctx = _make_context(tmp_path)
    chat_doc = ctx.create_document(id="chat_doc", doc_type="application/json", doc_model="chat-history")
    chat_doc.save(ChatHistory(messages=[]))

    agencykit = AgencyKit(providers={"provider1": _provider()}, roles={"role1": _role()})
    worker, _ = _make_agent_worker(ctx, agencykit)

    job = _agent_job(provider_selector="provider1")

    with pytest.raises(AgentWorkerError, match="must have at least one message"):
        await worker.run(job)


@pytest.mark.asyncio
async def test_work_missing_chat_history_binding_raises(tmp_path):
    ctx = _make_context(tmp_path)
    agencykit = AgencyKit(providers={"provider1": _provider()}, roles={"role1": _role()})
    worker, _ = _make_agent_worker(ctx, agencykit)

    job = _agent_job(provider_selector="provider1", include_chat_binding=False)

    # the required binding is fetched with `next(...)` and no default, so a
    # missing binding surfaces as StopIteration -> asyncio turns this into a RuntimeError
    with pytest.raises(RuntimeError):
        await worker.run(job)


@pytest.mark.asyncio
async def test_work_missing_agent_role_binding_raises(tmp_path):
    ctx = _make_context(tmp_path)
    chat_doc = ctx.create_document(id="chat_doc", doc_type="application/json", doc_model="chat-history")
    chat_doc.save(ChatHistory(messages=[UserMessage(content="hi")]))

    agencykit = AgencyKit(providers={"provider1": _provider()}, roles={"role1": _role()})
    worker, _ = _make_agent_worker(ctx, agencykit)

    job = _agent_job(provider_selector="provider1", include_role_binding=False)

    with pytest.raises(RuntimeError):
        await worker.run(job)


@pytest.mark.asyncio
async def test_work_blank_agent_role_selector_raises(tmp_path):
    ctx = _make_context(tmp_path)
    agencykit = AgencyKit(providers={"provider1": _provider()}, roles={"role1": _role()})
    worker, _ = _make_agent_worker(ctx, agencykit)

    job = _agent_job(role_selector="", provider_selector="provider1")

    with pytest.raises(AgentWorkerError, match="Role ID is required"):
        await worker.run(job)


@pytest.mark.asyncio
async def test_work_blank_inference_provider_selector_raises(tmp_path):
    ctx = _make_context(tmp_path)
    agencykit = AgencyKit(providers={"provider1": _provider()}, roles={"role1": _role()})
    worker, _ = _make_agent_worker(ctx, agencykit)

    job = _agent_job(role_selector="role1", provider_selector="")

    with pytest.raises(AgentWorkerError, match="Provider ID is required"):
        await worker.run(job)


# ==============================================================================
# work() - happy paths
# ==============================================================================

@pytest.mark.asyncio
async def test_work_success_streaming_with_explicit_provider(tmp_path, httpserver):
    ctx = _make_context(tmp_path)
    chat_doc = ctx.create_document(id="chat_doc", doc_type="application/json", doc_model="chat-history")
    chat_doc.save(ChatHistory(messages=[
        SystemMessage(content="You are helpful."),
        UserMessage(content="hi"),
    ]))

    provider = _provider(id="provider1", base_url=httpserver.url_for("/v1/"), models=["gpt-test"])
    role = _role(id="role1", preferred_models=["gpt-test"])
    agencykit = AgencyKit(providers={"provider1": provider}, roles={"role1": role})
    worker, _tool_worker = _make_agent_worker(ctx, agencykit)

    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_response(
        _sse_response(_sse([{"choices": [{"delta": {"content": "Hello there"}, "finish_reason": "stop"}]}]))
    )

    job = _agent_job(role_selector="role1", provider_selector="provider1")
    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    saved: ChatHistory = chat_doc.load()
    assert len(saved.messages) == 3
    assert saved.messages[-1].role == "assistant"
    assert saved.messages[-1].content == "Hello there"
    assert saved.messages[-1].metadata["finish_reason"] == "stop"

    sent = httpserver.log[0][0].get_json()
    assert sent["model"] == "gpt-test"
    assert sent["temperature"] == role.temperature
    assert sent["top_p"] == role.top_p
    assert sent["max_tokens"] == role.max_tokens
    assert "tools" not in sent
    assert "response_format" not in sent
    # NOTE: ChatHistory.prepare_request() itself returns {"messages": [...]}, and
    # work() assigns that whole dict directly as request_payload["messages"].
    assert sent["messages"] == {
        "messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hi"},
        ]
    }


@pytest.mark.asyncio
async def test_work_uses_preferred_provider_when_not_bound(tmp_path, httpserver):
    ctx = _make_context(tmp_path)
    chat_doc = ctx.create_document(id="chat_doc", doc_type="application/json", doc_model="chat-history")
    chat_doc.save(ChatHistory(messages=[UserMessage(content="hi")]))

    other_provider = _provider(id="other", base_url="http://unused.invalid/v1/", models=["other-model"])
    preferred_provider = _provider(id="preferred", base_url=httpserver.url_for("/v1/"), models=["gpt-test"])
    role = _role(id="role1", preferred_models=["gpt-test"])
    agencykit = AgencyKit(
        providers={"other": other_provider, "preferred": preferred_provider},
        roles={"role1": role},
    )
    worker, _ = _make_agent_worker(ctx, agencykit)

    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_response(
        _sse_response(_sse([{"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}]))
    )

    job = _agent_job(role_selector="role1")  # no provider_selector -> preferred lookup
    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    assert len(httpserver.log) == 1


@pytest.mark.asyncio
async def test_work_uses_fetcher_when_provider_does_not_support_streaming(tmp_path, httpserver):
    ctx = _make_context(tmp_path)
    chat_doc = ctx.create_document(id="chat_doc", doc_type="application/json", doc_model="chat-history")
    chat_doc.save(ChatHistory(messages=[UserMessage(content="hi")]))

    provider = _provider(
        id="provider1", base_url=httpserver.url_for("/v1/"), models=["gpt-test"], supports_streaming=False
    )
    role = _role(id="role1", preferred_models=["gpt-test"])
    agencykit = AgencyKit(providers={"provider1": provider}, roles={"role1": role})
    worker, _ = _make_agent_worker(ctx, agencykit)

    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_json({
        "choices": [{"message": {"role": "assistant", "content": "fetched"}, "finish_reason": "stop"}],
    })

    job = _agent_job(role_selector="role1", provider_selector="provider1")
    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    saved: ChatHistory = chat_doc.load()
    assert saved.messages[-1].content == "fetched"


@pytest.mark.asyncio
async def test_work_with_output_doc_model_includes_response_format_in_request(tmp_path, httpserver):
    ctx = _make_context(tmp_path)
    chat_doc = ctx.create_document(id="chat_doc", doc_type="application/json", doc_model="chat-history")
    chat_doc.save(ChatHistory(messages=[UserMessage(content="hi")]))

    register_doc_model(id="agent-output", clazz=SimpleOutputModel)

    provider = _provider(id="provider1", base_url=httpserver.url_for("/v1/"), models=["gpt-test"])
    role = _role(id="role1", preferred_models=["gpt-test"], output_doc_model="agent-output")
    agencykit = AgencyKit(providers={"provider1": provider}, roles={"role1": role})
    worker, _ = _make_agent_worker(ctx, agencykit)

    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_response(
        _sse_response(_sse([{"choices": [{"delta": {"content": '{"answer": "42"}'}, "finish_reason": "stop"}]}]))
    )

    job = _agent_job(role_selector="role1", provider_selector="provider1")
    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    sent = httpserver.log[0][0].get_json()
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["name"] == "agent-output"
    assert sent["response_format"]["json_schema"]["schema"]["required"] == ["answer"]


# ==============================================================================
# work() - tool-call round trips
# ==============================================================================

@pytest.mark.asyncio
async def test_work_tool_call_round_trip_success(tmp_path, httpserver, agent_toolbox):
    ctx = _make_context(tmp_path)
    chat_doc = ctx.create_document(id="chat_doc", doc_type="application/json", doc_model="chat-history")
    chat_doc.save(ChatHistory(messages=[UserMessage(content="please greet Ana")]))

    toolkit = ToolKit(toolboxes={
        "box1": ToolBoxSetUp(id="box1", toolbox_name="AgentGreeterBox", tools_enabled=["greet"]),
    })
    provider = _provider(id="provider1", base_url=httpserver.url_for("/v1/"), models=["gpt-test"])
    role = _role(
        id="role1", preferred_models=["gpt-test"], tools_enabled=["box1.greet"], tool_max_iter=3
    )
    agencykit = AgencyKit(providers={"provider1": provider}, roles={"role1": role})
    worker, _tool_worker = _make_agent_worker(ctx, agencykit, toolkit=toolkit)

    round1 = _sse([
        {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0, "id": "call_abc",
                        "function": {"name": "box1.greet", "arguments": '{"name": "Ana"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }]
        },
    ])
    round2 = _sse([
        {"choices": [{"delta": {"content": "Done!"}, "finish_reason": "stop"}]},
    ])
    httpserver.expect_oneshot_request("/v1/chat/completions", method="POST").respond_with_response(_sse_response(round1))
    httpserver.expect_oneshot_request("/v1/chat/completions", method="POST").respond_with_response(_sse_response(round2))

    job = _agent_job(role_selector="role1", provider_selector="provider1")
    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    assert len(job.delegates) == 1

    saved: ChatHistory = chat_doc.load()
    roles = [m.role for m in saved.messages]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert saved.messages[1].tool_calls[0].function.name == "box1.greet"
    assert saved.messages[2].content == "Hello, Ana!"
    assert saved.messages[2].tool_call_id == "call_abc"
    assert saved.messages[3].content == "Done!"

    # the second round's request already includes the tool result in its messages
    second_request = httpserver.log[1][0].get_json()
    assert second_request["messages"]["messages"][2]["role"] == "tool"


@pytest.mark.asyncio
async def test_work_tool_call_missing_toolbox_appends_message_and_continues(tmp_path, httpserver, agent_toolbox):
    ctx = _make_context(tmp_path)
    chat_doc = ctx.create_document(id="chat_doc", doc_type="application/json", doc_model="chat-history")
    chat_doc.save(ChatHistory(messages=[UserMessage(content="hi")]))

    toolkit = ToolKit(toolboxes={
        "box1": ToolBoxSetUp(id="box1", toolbox_name="AgentGreeterBox", tools_enabled=["greet"]),
    })
    provider = _provider(id="provider1", base_url=httpserver.url_for("/v1/"), models=["gpt-test"])
    role = _role(
        id="role1", preferred_models=["gpt-test"], tools_enabled=["box1.greet"], tool_max_iter=1
    )
    agencykit = AgencyKit(providers={"provider1": provider}, roles={"role1": role})
    worker, _tool_worker = _make_agent_worker(ctx, agencykit, toolkit=toolkit)

    body = _sse([
        {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0, "id": "call_ghost",
                        "function": {"name": "ghostbox.sometool", "arguments": "{}"},
                    }],
                },
                "finish_reason": "tool_calls",
            }]
        },
    ])
    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_response(_sse_response(body))

    job = _agent_job(role_selector="role1", provider_selector="provider1")
    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    assert len(job.delegates) == 0  # no tool_job was ever created

    saved: ChatHistory = chat_doc.load()
    tool_message = saved.messages[-1]
    assert tool_message.role == "tool"
    assert tool_message.content == "ToolBox 'ghostbox' not found."
    assert tool_message.tool_call_id == "call_ghost"


@pytest.mark.asyncio
async def test_work_tool_call_empty_tool_calls_raises(tmp_path, httpserver, agent_toolbox):
    ctx = _make_context(tmp_path)
    chat_doc = ctx.create_document(id="chat_doc", doc_type="application/json", doc_model="chat-history")
    chat_doc.save(ChatHistory(messages=[UserMessage(content="hi")]))

    toolkit = ToolKit(toolboxes={
        "box1": ToolBoxSetUp(id="box1", toolbox_name="AgentGreeterBox", tools_enabled=["greet"]),
    })
    provider = _provider(id="provider1", base_url=httpserver.url_for("/v1/"), models=["gpt-test"])
    role = _role(id="role1", preferred_models=["gpt-test"], tools_enabled=["box1.greet"])
    agencykit = AgencyKit(providers={"provider1": provider}, roles={"role1": role})
    worker, _tool_worker = _make_agent_worker(ctx, agencykit, toolkit=toolkit)

    # finish_reason says "tool_calls" but no tool_call deltas were ever sent
    body = _sse([{"choices": [{"delta": {"content": "oops"}, "finish_reason": "tool_calls"}]}])
    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_response(_sse_response(body))

    job = _agent_job(role_selector="role1", provider_selector="provider1")

    with pytest.raises(AgentWorkerError, match="Assistant's tool call is empty"):
        await worker.run(job)

    assert job.status == JobStatus.CRASHED


@pytest.mark.asyncio
async def test_work_multiple_tool_calls_in_one_round(
    tmp_path, httpserver, agent_toolbox, second_agent_toolbox
):
    ctx = _make_context(tmp_path)
    chat_doc = ctx.create_document(id="chat_doc", doc_type="application/json", doc_model="chat-history")
    chat_doc.save(ChatHistory(messages=[UserMessage(content="hi")]))

    toolkit = ToolKit(toolboxes={
        "box1": ToolBoxSetUp(id="box1", toolbox_name="AgentGreeterBox", tools_enabled=["greet"]),
        "box2": ToolBoxSetUp(id="box2", toolbox_name="AgentSecondBox", tools_enabled=["shout"]),
    })
    provider = _provider(id="provider1", base_url=httpserver.url_for("/v1/"), models=["gpt-test"])
    role = _role(
        id="role1", preferred_models=["gpt-test"],
        tools_enabled=["box1.greet", "box2.shout"], tool_max_iter=2,
    )
    agencykit = AgencyKit(providers={"provider1": provider}, roles={"role1": role})
    worker, _tool_worker = _make_agent_worker(ctx, agencykit, toolkit=toolkit)

    round1 = _sse([
        {
            "choices": [{
                "delta": {
                    "tool_calls": [
                        {"index": 0, "id": "call_a", "function": {"name": "box1.greet", "arguments": '{"name": "Ana"}'}},
                        {"index": 1, "id": "call_b", "function": {"name": "box2.shout", "arguments": '{"name": "bob"}'}},
                    ],
                },
                "finish_reason": "tool_calls",
            }]
        },
    ])
    round2 = _sse([{"choices": [{"delta": {"content": "all done"}, "finish_reason": "stop"}]}])
    httpserver.expect_oneshot_request("/v1/chat/completions", method="POST").respond_with_response(_sse_response(round1))
    httpserver.expect_oneshot_request("/v1/chat/completions", method="POST").respond_with_response(_sse_response(round2))

    job = _agent_job(role_selector="role1", provider_selector="provider1")
    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    assert len(job.delegates) == 2

    saved: ChatHistory = chat_doc.load()
    roles = [m.role for m in saved.messages]
    assert roles == ["user", "assistant", "tool", "tool", "assistant"]
    assert saved.messages[2].content == "Hello, Ana!"
    assert saved.messages[3].content == "BOB!!!"


@pytest.mark.asyncio
async def test_work_reaches_tool_max_iter_without_explicit_break(tmp_path, httpserver, agent_toolbox):
    """If every round keeps returning finish_reason='tool_calls', the loop simply
    stops once `tool_max_iter` rounds have run (no explicit break needed)."""
    ctx = _make_context(tmp_path)
    chat_doc = ctx.create_document(id="chat_doc", doc_type="application/json", doc_model="chat-history")
    chat_doc.save(ChatHistory(messages=[UserMessage(content="hi")]))

    toolkit = ToolKit(toolboxes={
        "box1": ToolBoxSetUp(id="box1", toolbox_name="AgentGreeterBox", tools_enabled=["greet"]),
    })
    provider = _provider(id="provider1", base_url=httpserver.url_for("/v1/"), models=["gpt-test"])
    role = _role(
        id="role1", preferred_models=["gpt-test"], tools_enabled=["box1.greet"], tool_max_iter=1
    )
    agencykit = AgencyKit(providers={"provider1": provider}, roles={"role1": role})
    worker, _tool_worker = _make_agent_worker(ctx, agencykit, toolkit=toolkit)

    body = _sse([
        {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0, "id": "call_1",
                        "function": {"name": "box1.greet", "arguments": '{"name": "Zed"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }]
        },
    ])
    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_response(_sse_response(body))

    job = _agent_job(role_selector="role1", provider_selector="provider1")
    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    # only a single round happened, since tool_max_iter=1
    assert len(httpserver.log) == 1
    saved: ChatHistory = chat_doc.load()
    assert [m.role for m in saved.messages] == ["user", "assistant", "tool"]