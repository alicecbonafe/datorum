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
    url: str
    detail: Literal["low", "high", "auto"] | None = "auto"


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImagePart(BaseModel):
    type: Literal["image_url"] = "image_url"
    image_url: ImageUrl


# User content can be plain text or a mixed list of text and images.
ContentPart = Annotated[TextPart | ImagePart, Field(discriminator="type")]
UserContent = str | list[ContentPart]


# ============================
# 2. Function calls / Tools
# ============================
class FunctionCall(BaseModel):
    """Old (deprecated) function call format."""

    name: str
    arguments: str  # String JSON


class ToolFunction(BaseModel):
    """Function definition within a tool_call."""

    name: str
    arguments: str  # String JSON


class ToolCall(BaseModel):
    """Tool call in the new format (tools)."""

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
    role: Literal["system"] = "system"
    content: str


class UserMessage(_MessageBase):
    role: Literal["user"] = "user"
    content: UserContent


class AssistantMessage(_MessageBase):
    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    function_call: FunctionCall | None = (
        None  # Deprecated, but retained for compatibility
    )


class ToolMessage(_MessageBase):
    """Response from a called tool."""

    role: Literal["tool"] = "tool"
    content: str
    tool_call_id: str  # Required for 'tool' messages


class FunctionMessage(_MessageBase):
    """Response from a called function (old format)."""

    role: Literal["function"] = "function"
    content: str | None = None
    name: str  # Mandatory and overrides the optional base field.


# Combination of all message types, distinguished by the 'role' field.
ChatMessage = Annotated[
    SystemMessage | UserMessage | AssistantMessage | ToolMessage | FunctionMessage,
    Field(discriminator="role"),
]


# ============================
# 4. Main History Model
# ============================
@doc_model(id="chat-history")
class ChatHistory(BaseModel):
    """Represents the complete message history for the OpenAI API."""

    messages: list[ChatMessage] = Field(
        default_factory=list, description="Ordered list of chat history messages"
    )

    model_config = {"extra": "forbid"}

    def prepare_request(self) -> dict[str, Any]:
        dumped_messages: list[dict] = []
        for msg in self.messages:
            dumped_messages.append(msg.prepare_request())
        return {"messages": dumped_messages}
