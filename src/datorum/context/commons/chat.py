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
    """Image URL payload for multimodal vision inputs."""

    url: str = Field(description="Image URL or data URI.")
    detail: Literal["low", "high", "auto"] | None = Field(
        default="auto",
        description="Fidelity detail setting, defaults to 'auto'.",
    )


class TextPart(BaseModel):
    """Text block content part in multimodal messages."""

    type: Literal["text"] = Field(
        default="text",
        description="Content part discriminator, always 'text'."
    )
    text: str = Field(description="Text content.")


class ImagePart(BaseModel):
    """Image content part in multimodal user messages."""

    type: Literal["image_url"] = Field(
        default="image_url",
        description="Content part discriminator, always 'image_url'.",
    )
    image_url: ImageUrl = Field(description="Image payload for this content part.")


# User content can be plain text or a mixed list of text and images.
ContentPart = Annotated[TextPart | ImagePart, Field(discriminator="type")]
UserContent = str | list[ContentPart]


# ============================
# 2. Function calls / Tools
# ============================
class FunctionCall(BaseModel):
    """Deprecated legacy function call structure."""

    name: str = Field(description="Name of the called function.")
    arguments: str = Field(description="Function arguments, as a JSON-encoded string.")


class ToolFunction(BaseModel):
    """Function call detail payload inside a tool call."""

    name: str = Field(description="Name of the called function.")
    arguments: str = Field(description="Function arguments, as a JSON-encoded string.")


class ToolCall(BaseModel):
    """Tool invocation payload structure."""

    id: str = Field(description="Unique identifier for this tool call.")
    type: Literal["function"] = Field(
        default="function",
        description="Tool call discriminator, always 'function'.",
    )
    function: ToolFunction = Field(description="Function call detail for this tool call.")


# ============================
# 3. Message definitions (Discriminated Union based on the 'role' field)
# ============================
class _MessageBase(BaseModel):
    name: str | None = Field(
        default=None,
        description="Optional participant name attached to the message.",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Arbitrary metadata attached to the message.",
    )

    model_config = {"extra": "allow"}

    def prepare_request(self) -> dict[str, Any]:
        """Build the inference-request payload for this message.

        :returns: Dict with the message data, without the extra fields, in its
            request-ready form.
        :rtype: dict[str, Any]
        """

        known_fields = set(type(self).model_fields.keys()) - {"metadata"}
        return self.model_dump(mode="json", exclude_none=True, include=known_fields)


class SystemMessage(_MessageBase):
    """System message delivering top-level instructions to LLM models."""

    role: Literal["system"] = Field(
        default="system",
        description="Message role discriminator, always 'system'.",
    )
    content: str = Field(description="System instruction text.")


class UserMessage(_MessageBase):
    """User input message containing text or multimodal content blocks."""

    role: Literal["user"] = Field(
        default="user",
        description="Message role discriminator, always 'user'.",
    )
    content: UserContent = Field(description="Message content: plain text, or a list of text/image parts.")


class AssistantMessage(_MessageBase):
    """Assistant response message containing text, tool calls, or function calls."""

    role: Literal["assistant"] = Field(
        default="assistant",
        description="Message role discriminator, always 'assistant'.",
    )
    content: str | None = Field(
        default=None,
        description="Assistant response text.",
    )
    tool_calls: list[ToolCall] | None = Field(
        default=None,
        description="Tool calls requested by the assistant, if any.",
    )
    function_call: FunctionCall | None = Field(
        default=None,
        description="Deprecated legacy function call, retained for compatibility.",
    )


class ToolMessage(_MessageBase):
    """Tool execution response message."""

    role: Literal["tool"] = Field(
        default="tool",
        description="Message role discriminator, always 'tool'.",
    )
    content: str = Field(description="Tool execution result content.")
    tool_call_id: str = Field(description="ID of the `ToolCall` this message is a response to.")


class FunctionMessage(_MessageBase):
    """Legacy function execution response message."""

    role: Literal["function"] = Field(
        default="function",
        description="Message role discriminator, always 'function'.",
    )
    content: str | None = Field(
        default=None,
        description="Function execution result content.",
    )
    name: str = Field(description="Name of the function that was called.")


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
        """Build the inference-request payload for this chat history.

        :returns: Dict with a `messages` key holding each message's request-ready form.
        :rtype: dict[str, Any]
        """

        dumped_messages: list[dict] = []
        for msg in self.messages:
            dumped_messages.append(msg.prepare_request())
        return {"messages": dumped_messages}
