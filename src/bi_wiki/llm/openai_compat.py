"""Bounded, non-streaming chat completion over an HTTP-compatible gateway."""

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from time import monotonic

import httpx
from pydantic import SecretStr

from bi_wiki.core.errors import ServiceError
from bi_wiki.core.logging import logger
from bi_wiki.llm.base import Message


@dataclass(frozen=True)
class ModelConfig:
    base_url: str
    model: str
    api_key: SecretStr | None = field(default=None, repr=False)
    timeout_seconds: float = 300
    max_response_bytes: int = 1_000_000


class OpenAICompatibleProvider:
    def __init__(self, config: ModelConfig, *, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self._transport = transport

    @property
    def ready(self) -> bool:
        return bool(self.config.base_url and self.config.model)

    @property
    def model(self) -> str:
        return self.config.model

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_object: bool = False,
    ) -> str:
        if not self.ready:
            raise ServiceError("MODEL_NOT_CONFIGURED", "请先配置模型地址和模型名", 503)
        headers = {}
        if self.config.api_key:
            headers["Authorization"] = "Bearer " + self.config.api_key.get_secret_value()
        payload = {"model": self.model, "messages": list(messages), "stream": False}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if json_object:
            payload["response_format"] = {"type": "json_object"}
        started = monotonic()
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.config.timeout_seconds, connect=10),
                    follow_redirects=False,
                    transport=self._transport,
                ) as client:
                    async with client.stream(
                        "POST",
                        self.config.base_url.rstrip("/") + "/chat/completions",
                        headers=headers,
                        json=payload,
                    ) as response:
                        response.raise_for_status()
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > self.config.max_response_bytes:
                                raise ValueError("response too large")
            choice = json.loads(data)["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ServiceError(
                    "MODEL_OUTPUT_TRUNCATED",
                    "模型输出达到 token 上限，结果可能不完整；请减少候选数量或拆分资料后重新生成",
                    422,
                )
            if choice.get("finish_reason") == "content_filter":
                raise ServiceError(
                    "MODEL_OUTPUT_FILTERED", "模型服务过滤了输出，未生成可用结果", 422
                )
            answer = choice["message"]["content"]
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("missing text")
            return answer
        except httpx.HTTPStatusError as exc:
            code, message, status = {
                401: ("MODEL_AUTH_FAILED", "模型凭据无效，请检查服务端配置", 503),
                403: ("MODEL_ACCESS_DENIED", "模型网关拒绝访问，请检查模型权限及预算池有效期", 503),
                429: ("MODEL_RATE_LIMITED", "模型服务限流或配额不足，请稍后重试", 503),
            }.get(
                exc.response.status_code,
                (
                    "MODEL_REQUEST_REJECTED"
                    if exc.response.status_code < 500
                    else "MODEL_UNAVAILABLE",
                    "模型服务拒绝请求，请检查地址、模型名和请求参数"
                    if exc.response.status_code < 500
                    else "模型服务暂时不可用，请稍后重试",
                    502 if exc.response.status_code < 500 else 503,
                ),
            )
            raise ServiceError(code, message, status) from None
        except (TimeoutError, httpx.TimeoutException):
            raise ServiceError("MODEL_TIMEOUT", "模型调用超时，请稍后重试", 504) from None
        except httpx.HTTPError as exc:
            error_type = type(exc).__name__
            elapsed = round(monotonic() - started, 2)
            logger.warning(
                "model_transport_failed",
                extra={"error_type": error_type, "elapsed_ms": round(elapsed * 1000)},
            )
            if isinstance(exc, (httpx.RemoteProtocolError, httpx.ReadError)):
                hint = "模型响应连接中断，请检查网关或代理的长请求限制"
            elif isinstance(exc, httpx.ConnectError):
                hint = "无法建立模型连接，请检查网络、地址及TLS配置"
            else:
                hint = "模型请求传输失败，请检查网关与网络"
            raise ServiceError(
                "MODEL_UNAVAILABLE", f"{hint}（{error_type}，已等待{elapsed}秒）", 503
            ) from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise ServiceError(
                "MODEL_RESPONSE_INVALID", "模型服务未返回有效的文本响应", 502
            ) from None
