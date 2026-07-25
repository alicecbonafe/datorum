# datorum/providers/inference.py
from typing import Optional, Any, Type
from abc import ABC, abstractmethod

from openai import OpenAI
from pydantic import BaseModel, Field

from .. import GeneralConfig

class InferenceRequest(BaseModel):
    provider: str = Field(default='')

    model: str
    system_instructions: str
    user_prompt: str

    temperature: float = Field(default=0.7)
    top_p: float = Field(default=1.0)
    max_tokens: int = Field(default=4096)

    response_schema: Optional[Type[BaseModel]] = Field(default=None)


class InferenceFactory():
    _config: Optional[dict[str, str]] = None
    _instance: Optional['InferenceFactory'] = None

    @classmethod
    def configure(cls, config: dict[str, str] = None):
        if config is None:
            config = {}
        cls._config = {
            **GeneralConfig,
            **config
        }

    def __new__(cls, *args, **kwargs):
        if not cls._config:
            cls.configure()
        if not cls._instance:
            cls._instance = super().__new__(cls, *args, **kwargs)
            cls._instance.clients = {}
        return cls._instance

    def get_config(self, key: str, provider: str = '', default: Optional[str] = None):
        prefix = f'{provider.strip()}_' if provider.strip() else ''
        return self._config.get(f'{prefix}{key}'.upper(), default)

    def get_client(self, provider: str = '') -> OpenAI:
        if provider not in self.clients:
            api_key = self.get_config('api_key', provider)
            base_url = self.get_config('base_url', provider)

            self.clients[provider] = OpenAI(
                api_key=api_key,
                base_url=base_url
            )
        return self.clients[provider]

    def generate(self, request: InferenceRequest) -> str:
        client = self.get_client(request.provider)
        
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
            completion = client.beta.chat.completions.parse(
                **request_kwargs,
                response_format=request.response_schema
            )
            return completion.choices[0].message.parsed.model_dump_json(indent=2)

        completion = client.chat.completions.create(
            **request_kwargs
        )
        return completion.choices[0].message.content