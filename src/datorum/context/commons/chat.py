from typing import (
    Annotated,
    Any,
    Literal,
)

from pydantic import BaseModel, Field

from ..registry import doc_model


# ============================
# 1. Content blocks for vision / multimodal
# ============================
class ImageUrl(BaseModel):
    """Image URL payload for multimodal vision inputs.

    :param url: Image URL or data URI.
    :type url: str
    :param detail: Fidelity detail setting, defaults to 'auto'.
    :type detail: Literal['low', 'high', 'auto'] | None
    """

    url: str
    detail: Literal["low", "high", "auto"] | None = "auto"


class TextPart(BaseModel):
    """Text block content part in multimodal messages."""

    type: Literal["text"] = "text"
    text: str


class ImagePart(BaseModel):
    """Image content part in multimodal user messages."""

    type: Literal["image_url"] = "image_url"
    image_url: ImageUrl


# User content can be plain text or a mixed list of text and images.
ContentPart = Annotated[TextPart | ImagePart, Field(discriminator="type")]
UserContent = str | list[ContentPart]


# ============================
# 2. Function calls / Tools
# ============================
class FunctionCall(BaseModel):
    """Deprecated legacy function call structure."""

    name: str
    arguments: str  # String JSON


class ToolFunction(BaseModel):
    """Function call detail payload inside a tool call."""

    name: str
    arguments: str  # String JSON


class ToolCall(BaseModel):
    """Tool invocation payload structure."""

    id: str
    type: Literal["function"] = "function"
    function: ToolFunction


# ============================
# 3. Message definitions (Discriminated Union based on the 'role' field)
# ============================
class _MessageBase(BaseModel):
    name: str | None = None
    metadata: dict[str, Any] | None = None

    model_config = {"extra": "allow"}

    def prepare_request(self) -> dict[str, Any]:
        known_fields = set(type(self).model_fields.keys()) - {"metadata"}
        return self.model_dump(mode="json", exclude_none=True, include=known_fields)


class SystemMessage(_MessageBase):
    """System message delivering top-level instructions to LLM models."""

    role: Literal["system"] = "system"
    content: str


class UserMessage(_MessageBase):
    """User input message containing text or multimodal content blocks."""

    role: Literal["user"] = "user"
    content: UserContent


class AssistantMessage(_MessageBase):
    """Assistant response message containing text, tool calls, or function calls."""

    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    function_call: FunctionCall | None = (
        None  # Deprecated, but retained for compatibility
    )


class ToolMessage(_MessageBase):
    """Tool execution response message."""

    role: Literal["tool"] = "tool"
    content: str
    tool_call_id: str  # Required for 'tool' messages


class FunctionMessage(_MessageBase):
    """Legacy function execution response message."""

    role: Literal["function"] = "function"
    content: str | None = None
    name: str  # Mandatory and overrides the optional base field.


# Combination of all message types, distinguished by the 'role' field.
ChatMessage = Annotated[
    SystemMessage | UserMessage | AssistantMessage | ToolMessage | FunctionMessage,
    Field(discriminator="role"),
]
ChatMessage.__doc__ = "Discriminated union type covering all supported chat messages."


# ============================
# 4. Main History Model
# ============================
@doc_model(id="chat-history")
class ChatHistory(BaseModel):
    """Document model representing an ordered chat turn history."""

    messages: list[ChatMessage] = Field(
        default_factory=list, description="Ordered list of chat history messages"
    )

    model_config = {"extra": "forbid"}

    def prepare_request(self) -> dict[str, Any]:
        dumped_messages: list[dict] = []
        for msg in self.messages:
            dumped_messages.append(msg.prepare_request())
        return {"messages": dumped_messages}
