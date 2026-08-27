import json
import uuid
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel

from ..binding.binder import Binder
from ..binding.settings import (
    ContextBind,
    ContextBindType,
    ResourceBind,
)
from ..context.commons.chat import (
    AssistantMessage,
    ChatHistory,
    ToolMessage,
)
from ..context.registry import DocumentModel, get_doc_model
from ..tooling.registry import ToolBoxDefinition, get_toolbox_definition
from ..tooling.settings import ToolBoxSetUp
from ..tooling.worker import ToolWorker
from ..work.job import Job, JobStatus
from ..work.worker import Worker
from .exceptions import AgentWorkerError
from .settings import (
    AgencyKit,
    AgentRole,
    InferenceServiceProvider,
)


class AgentWorker(Worker):
    """Worker handling agent execution loops and tool delegate invocations.

    An Agent Worker associates with a `ChatHistory` to request an inference from a
    provider.

    The Agent Worker utilizes a `ToolWorker` to enable tool calls by the model. This is
    considered a single operation that shares the local context. Thus, the `ChatHistory`
    can (and likely should) be defined as a local context.

    The provider from which inference is requested is defined by the resource bind with
    `field_id == "inference_provider"`. Each provider defines, at the settings level, a
    selector to resolve the API key as a runtime resource, by the factory named
    `api_key`. If this selector is absent, the provider ID itself is assumed to be the
    selector.

    The agent role is defined by the resource bind with `field_id == "agent_role"`. Each
    role has a list of preferred models, ordered by preference. The Worker searches for
    each preferred model within the provider's model list. The role also defines
    parameters such as temperature, top-p, and max tokens.

    Each role includes a `system_instructions` field, though it is not used directly by
    the Worker. The purpose of this field is to provide a configurable foundation for
    tools that construct the `ChatHistory`. This allows instructions to be modified
    based on the model, thereby better leveraging its capabilities.

    The role also defines the agent's behavior regarding tool usage. It is possible to
    restrict which tools are available to the model, force the model to call tools, and
    limit the number of tool calls. For instance, this allows a smaller model to be
    forced to use tools for one or two iterations, effectively preparing the context for
    a more capable model.

    :param binder: Binder instance used for context and resource loading.
    :type binder: Binder
    :param agencykit: Collection of settings defining providers and roles.
    :type agencykit: AgencyKit
    :param tool_worker: Responsible for delegated tool jobs.
    :type tool_worker: ToolWorker
    """

    required_context_binds: ClassVar[list[str]] = ["chat_history"]
    required_resource_binds: ClassVar[list[str]] = ["inference_provider", "agent_role"]

    _KNOWN_DELTA_KEYS: ClassVar[set[str]] = {"content", "tool_calls", "role"}

    def __init__(
        self,
        binder: Binder,
        agencykit: AgencyKit,
        tool_worker: ToolWorker,
    ):
        super().__init__(binder)
        self.agencykit: AgencyKit = agencykit
        self.tool_worker: ToolWorker = tool_worker

        @self.binder.resource(name="inference_provider")
        def _inference_provider(provider_id: str | None) -> InferenceServiceProvider:
            if not provider_id:
                raise AgentWorkerError("Provider ID is required")
            return self.get_provider(provider_id)

        @self.binder.resource(name="agent_role")
        def _agent_role(role_id: str | None) -> AgentRole:
            if not role_id:
                raise AgentWorkerError("Role ID is required")
            return self.get_role(role_id)

    def get_role(self, role_id: str) -> AgentRole:
        """Look up a configured agent role by ID.

        :param role_id: Role identifier.
        :type role_id: str
        :returns: The matching `AgentRole`.
        :rtype: AgentRole
        :raises AgentWorkerError: If no role with that ID is configured.
        """

        if role_id not in self.agencykit.roles:
            raise AgentWorkerError(f"Role not found: '{role_id}'")
        return self.agencykit.roles[role_id]

    def get_provider(self, provider_id: str) -> InferenceServiceProvider:
        """Look up a configured inference provider by ID.

        :param provider_id: Provider identifier.
        :type provider_id: str
        :returns: The matching `InferenceServiceProvider`.
        :rtype: InferenceServiceProvider
        :raises AgentWorkerError: If no provider with that ID is configured.
        """

        if provider_id not in self.agencykit.providers:
            raise AgentWorkerError(f"Provider not found: '{provider_id}'")
        return self.agencykit.providers[provider_id]

    def get_preferred_provider(
        self, preferred_models: list[str]
    ) -> InferenceServiceProvider:
        """Find the first configured provider offering one of the preferred models.

        :param preferred_models: Model names, in order of preference.
        :type preferred_models: list[str]
        :returns: The first matching `InferenceServiceProvider`.
        :rtype: InferenceServiceProvider
        :raises AgentWorkerError: If no configured provider offers any of the models.
        """

        for model in preferred_models:
            for provider in self.agencykit.providers.values():
                if model in provider.models:
                    return provider
        raise AgentWorkerError(f"No provider found for models: {preferred_models}")

    def _select_model(self, role: AgentRole, provider: InferenceServiceProvider) -> str:
        for candidate in role.preferred_models:
            if candidate in provider.models:
                return candidate
        raise AgentWorkerError(
            f"Can not determine model for role '{role.id}' on provider '{provider.id}'"
        )

    def _strict_json_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Recursively enforce OpenAI's structured-output constraints on a
        pydantic JSON schema: every object gets additionalProperties=false,
        and `required` must list ALL properties (optional fields become
        nullable via a type union, since strict mode has no concept of
        'optional')."""
        schema.pop("title", None)
        schema.pop("default", None)

        if schema.get("type") == "object" and "properties" in schema:
            schema["additionalProperties"] = False
            props = schema["properties"]
            for prop_schema in props.values():
                self._strict_json_schema(prop_schema)
            schema["required"] = list(props.keys())

        elif schema.get("type") == "array" and "items" in schema:
            self._strict_json_schema(schema["items"])

        for key in ("anyOf", "oneOf", "allOf"):
            if key in schema:
                for sub in schema[key]:
                    self._strict_json_schema(sub)

        return schema

    def _toolkit_schema(self, role: AgentRole) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for full_name in role.tools_enabled:
            setup_id, tool_name = full_name.rsplit(".", 1)
            setup: ToolBoxSetUp = self.tool_worker.toolkit.toolboxes[setup_id]
            toolbox_def: ToolBoxDefinition = get_toolbox_definition(setup.toolbox_name)
            tool_def = toolbox_def.tools[tool_name]
            tool_data = tool_def.model_dump(mode="json", exclude={"name"})
            function_name = tool_data["function"]["name"]
            tool_data["function"]["name"] = f"{setup.id}.{function_name}"
            result.append(tool_data)
        return result

    def _response_format(
        self, clazz: type[BaseModel], name: str | None = None, strict: bool = True
    ) -> dict[str, Any]:
        """Build an OpenAI-compatible `response_format` payload from a
        pydantic model, for structured-output / JSON-schema-constrained
        completions."""
        schema = clazz.model_json_schema()
        defs = schema.pop("$defs", {})
        for def_schema in defs.values():
            self._strict_json_schema(def_schema)
        self._strict_json_schema(schema)

        return {
            "type": "json_schema",
            "json_schema": {
                "name": name or clazz.__name__,
                "schema": {**schema, "$defs": defs} if defs else schema,
                "strict": strict,
            },
        }

    async def _call_streamer(
        self,
        request_payload: dict[str, Any],
        provider: InferenceServiceProvider,
        api_key: str,
        job: Job,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        request_payload = {**request_payload, "stream": True}
        content_parts: list[str] = []
        tool_call_parts: dict[int, dict[str, Any]] = {}
        extra_parts: dict[str, Any] = {}
        response_meta: dict[str, Any] = {}
        finish_reason: str | None = None

        job.is_streaming = True
        try:
            async with (
                httpx.AsyncClient(base_url=provider.base_url, timeout=120.0) as client,
                client.stream(
                    "POST",
                    "chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=request_payload,
                ) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    event = json.loads(data)

                    for key, value in event.items():
                        if key != "choices" and value is not None:
                            response_meta[key] = value

                    choice = event["choices"][0]
                    delta = choice.get("delta", {})
                    finish_reason = choice.get("finish_reason") or finish_reason
                    response_meta["finish_reason"] = finish_reason

                    if "content" in delta:
                        content_parts.append(delta["content"])
                        await job.push_chunk(delta["content"])

                    for tc_delta in delta.get("tool_calls", []) or []:
                        entry = tool_call_parts.setdefault(
                            tc_delta["index"],
                            {
                                "id": None,
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            },
                        )
                        if "id" in tc_delta:
                            entry["id"] = tc_delta["id"]
                        fn_delta = tc_delta.get("function") or {}
                        entry["function"]["name"] += fn_delta.get("name") or ""
                        entry["function"]["arguments"] += (
                            fn_delta.get("arguments") or ""
                        )

                    for key, value in delta.items():
                        if key in self._KNOWN_DELTA_KEYS:
                            continue
                        if isinstance(value, str):
                            extra_parts[key] = extra_parts.get(key, "") + value
                        else:
                            # extra parts that are not strings are not cumulative
                            # this will be handled when a concrete case appears
                            extra_parts[key] = value
        except httpx.HTTPError as e:
            raise AgentWorkerError(
                f"Failed to call inference provider '{provider.id}': {e}"
            ) from e
        finally:
            job.is_streaming = False

        message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(content_parts) or None,
            **extra_parts,
        }
        if tool_call_parts:
            message["tool_calls"] = [
                tool_call_parts[i] for i in sorted(tool_call_parts)
            ]

        return message, response_meta

    async def _call_fetcher(
        self,
        request_payload: dict[str, Any],
        provider: InferenceServiceProvider,
        api_key: str,
        job: Job,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            async with httpx.AsyncClient(
                base_url=provider.base_url, timeout=120.0
            ) as client:
                response = await client.post(
                    "chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=request_payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as e:
            raise AgentWorkerError(
                f"Failed to call inference provider '{provider.id}': {e}"
            ) from e

        response_data = response.json()
        message = response_data["choices"][0]["message"]
        finish_reason = response_data["choices"][0]["finish_reason"]
        response_meta: dict[str, Any] = {"finish_reason": finish_reason}

        for key, value in response_data.items():
            if key != "choices" and value is not None:
                response_meta[key] = value

        return message, response_meta

    async def work(self, job: Job):
        """Run one agent turn: request inference, then dispatch any resulting tool calls.

        Loops up to `role.tool_max_iter` times, delegating each tool call to
        `tool_worker` as a sub-job, until the model responds without requesting more
        tool calls.

        :param job: Job carrying the `chat_history` context binding and
            `inference_provider`/`agent_role` resource bindings.
        :type job: Job
        :raises AgentWorkerError: If `chat_history` isn't bound as a model, the chat
            history is empty, or no model/provider can be resolved for the role.
        """

        await job.update_status(JobStatus.WORKING, "Collecting agent resources")

        role_bind: ResourceBind = next(
            bind for bind in job.resource_bindings if bind.field_id == "agent_role"
        )
        provider_bind: ResourceBind | None = next(
            (
                bind
                for bind in job.resource_bindings
                if bind.field_id == "inference_provider"
            ),
            None,
        )
        chat_bind: ContextBind = next(
            bind for bind in job.context_bindings if bind.field_id == "chat_history"
        )

        if chat_bind.context_bind_type != ContextBindType.model:
            raise AgentWorkerError(
                f"The field 'chat_history' must be binded to an input-output model (received: '{chat_bind.context_bind_type}')"
            )

        role: AgentRole = self.binder.load_resource(role_bind)
        provider: InferenceServiceProvider = (
            self.binder.load_resource(provider_bind)
            if provider_bind
            else self.get_preferred_provider(role.preferred_models)
        )

        api_key: str = self.binder.load_resource(
            ResourceBind(
                field_id="api_key",
                factory_name="api_key",
                selector=provider.api_key_selector or provider.id,
            )
        )

        chat_doc = await self.binder.find_document(
            document_id=chat_bind.binded_id, context=chat_bind.context
        )
        chat: ChatHistory = chat_doc.load()
        if len(chat.messages) == 0:
            raise AgentWorkerError(
                "Chat history document must have at least one message"
            )

        model = self._select_model(role, provider)
        toolkit_schema = self._toolkit_schema(role)
        response_format: dict[str, Any] | None = None
        if role.output_doc_model:
            doc_model: DocumentModel = get_doc_model(role.output_doc_model)
            response_format = self._response_format(
                clazz=doc_model.clazz,
                name=doc_model.id,
            )

        for i in range(role.tool_max_iter):
            await job.update_status(
                JobStatus.WORKING,
                f"Calling model '{model}' at provider '{provider.id}' (round {i})",
            )
            request_payload: dict[str, Any] = {
                "model": model,
                "messages": chat.prepare_request(),
                "temperature": role.temperature,
                "top_p": role.top_p,
                "max_tokens": role.max_tokens,
            }

            if len(toolkit_schema) > 0:
                request_payload["tools"] = toolkit_schema
                request_payload["tool_choice"] = role.tool_choice
            if response_format:
                request_payload["response_format"] = response_format

            if provider.supports_streaming:
                message, response_meta = await self._call_streamer(
                    request_payload=request_payload,
                    provider=provider,
                    api_key=api_key,
                    job=job,
                )
            else:
                message, response_meta = await self._call_fetcher(
                    request_payload=request_payload,
                    provider=provider,
                    api_key=api_key,
                    job=job,
                )

            assistant_message: AssistantMessage = AssistantMessage.model_validate(
                message
            )
            assistant_message.metadata = response_meta

            chat.messages.append(assistant_message)
            chat_doc.save(chat)

            if response_meta.get("finish_reason") == "tool_calls":
                if not assistant_message.tool_calls:
                    raise AgentWorkerError("Assistant's tool call is empty")
                for tool_call in assistant_message.tool_calls:
                    await job.update_status(
                        JobStatus.WORKING,
                        f"Preparing tool call for '{tool_call.function.name}' (round {i})",
                    )

                    # toolbox_setup_id, tool_name = tool_call.function.name.rsplit(".", 1)
                    toolbox_setup_id, _ = tool_call.function.name.rsplit(".", 1)
                    toolbox_setup: ToolBoxSetUp | None = (
                        self.tool_worker.toolkit.toolboxes.get(toolbox_setup_id)
                    )

                    if toolbox_setup is None:
                        tool_message = ToolMessage(
                            content=f"ToolBox '{toolbox_setup_id}' not found.",
                            tool_call_id=tool_call.id,
                        )
                        chat.messages.append(tool_message)
                        chat_doc.save(chat)
                        continue

                    # toolbox_def = get_toolbox_definition(toolbox_setup.toolbox_name)
                    # tool_def = toolbox_def.tools[tool_name]

                    tool_job = Job(
                        id=f"{job.id}_tool_{uuid.uuid4().hex[:6]}",
                        context_bindings=[
                            ContextBind(
                                field_id="tool_params",
                                binded_id=chat_bind.binded_id,
                                context=chat_bind.context,
                                context_bind_type=ContextBindType.model,
                            ),
                            ContextBind(
                                field_id="tool_result",
                                binded_id=chat_bind.binded_id,
                                context=chat_bind.context,
                                context_bind_type=ContextBindType.model,
                            ),
                        ],
                        resource_bindings=[
                            ResourceBind(
                                field_id="toolbox_setup",
                                factory_name="toolbox_setup",
                                selector=tool_call.function.name,
                            )
                        ],
                        local_context_id=job.local_context_id,
                    )
                    job.delegates.append(tool_job)

                    await job.update_status(
                        JobStatus.WORKING,
                        f"Calling tool '{tool_call.function.name}' (round {i})",
                    )
                    await self.tool_worker.run(tool_job)
                    chat = chat_doc.load()

            else:
                break
