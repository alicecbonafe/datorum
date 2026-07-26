# datorum/providers/inference.py
from typing import Optional, Type

from openai import OpenAI
from pydantic import BaseModel, Field

from .. import GeneralConfig


class InferenceRequest(BaseModel):

    model: str
    system_instructions: str
    user_prompt: str

    temperature: float = Field(default=0.7)
    top_p: float = Field(default=1.0)
    max_tokens: int = Field(default=4096)

    response_schema: Optional[Type[BaseModel]] = Field(default=None)


class InferenceProvider:

    @classmethod
    def load(cls,
        provider: str = '',
        config: dict = GeneralConfig
    ) -> InferenceProvider:

        provider = provider.strip()
        prefix = f'{provider.upper()}_' if provider else ''
        base_url = config[f'{prefix}BASE_URL']
        api_key = config[f'{prefix}API_KEY']
        return cls(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
        )


    def __init__(self, provider: str, api_key: str, base_url: str):

        self.provider = provider
        self.base_url = base_url

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )


    def generate(self, request: InferenceRequest) -> str:

        messages = [
            {"role": "system", "content": request.system_instructions},
            {"role": "user", "content": request.user_prompt},
        ]

        request_kwargs = {
            "model": request.model,
            "messages": messages,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "max_tokens": request.max_tokens,
        }

        if request.response_schema is not None:
            completion = self.client.beta.chat.completions.parse(
                **request_kwargs,
                response_format=request.response_schema
            )
            return completion.choices[0].message.parsed.model_dump_json(indent=2)

        completion = self.client.chat.completions.create(
            **request_kwargs
        )
        return completion.choices[0].message.content

