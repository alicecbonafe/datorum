from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from datorum.providers.inference import InferenceProvider, InferenceRequest

TEST_RESULT = "This is a mocked reply from the assistant."

MOCKED_API_KEY = "mocked-key"
MOCKED_BASE_URL = "http://localhost:7777/v1"
MOCKED_MODEL = "mocked-model"
MOCKED_RESPONSE = {
    "id": "chatcmpl-abc123",
    "object": "chat.completion",
    "created": 1677858242,
    "model": MOCKED_MODEL,
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": TEST_RESULT},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 12, "total_tokens": 22},
}


@pytest.fixture
def mocked_server(httpserver):

    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_json(
        MOCKED_RESPONSE
    )
    return httpserver


def test_inference_provider_call(mocked_server):

    request = InferenceRequest(
        provider="test",
        model="mocked-model",
        system_instructions="You are a friendly chatbot.",
        user_prompt="Extract data from text.",
    )

    provider = InferenceProvider(
        provider="test",
        api_key=MOCKED_API_KEY,
        base_url=mocked_server.url_for("/v1"),
    )

    output = provider.generate(request)

    assert output is not None
    assert "mocked reply" in str(output)


class DummySchema(BaseModel):
    result: str


def test_inference_provider_load():
    config = {"BASE_URL": "http://localhost", "API_KEY": "secret"}
    provider = InferenceProvider.load(provider="", config=config)
    assert provider.base_url == "http://localhost"
    assert provider.provider == ""


def test_inference_structured_output(mocked_server):
    request = InferenceRequest(
        provider="test",
        model="mocked-model",
        system_instructions="Return JSON.",
        user_prompt="Data",
        response_schema=DummySchema,
    )

    provider = InferenceProvider(
        provider="test",
        api_key=MOCKED_API_KEY,
        base_url=mocked_server.url_for("/v1"),
    )

    with patch.object(provider.client.beta.chat.completions, "parse") as mock_parse:
        mock_choice = MagicMock()
        mock_choice.message.parsed.model_dump_json.return_value = (
            '{"result": "success"}'
        )
        mock_parse.return_value.choices = [mock_choice]

        output = provider.generate(request)
        assert '{"result": "success"}' in output
