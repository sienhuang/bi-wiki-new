"""Provider boundary tests with a fake HTTP gateway; no real model is called."""

import json

import httpx
import pytest
from pydantic import SecretStr

from bi_wiki.core.errors import ServiceError
from bi_wiki.ingest.extractor import Extractor
from bi_wiki.llm.openai_compat import ModelConfig, OpenAICompatibleProvider


def provider(handler, **options):
    return OpenAICompatibleProvider(
        ModelConfig("https://model.example/v1/", "test", SecretStr("private-key"), **options),
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "MODEL_AUTH_FAILED"),
        (403, "MODEL_ACCESS_DENIED"),
        (429, "MODEL_RATE_LIMITED"),
        (400, "MODEL_REQUEST_REJECTED"),
        (404, "MODEL_REQUEST_REJECTED"),
        (503, "MODEL_UNAVAILABLE"),
        (302, "MODEL_REQUEST_REJECTED"),
    ],
)
async def test_gateway_errors_are_classified_without_leaking(status, code):
    llm = provider(lambda r: httpx.Response(status, text="private-key private-body"))
    with pytest.raises(ServiceError) as error:
        await llm.complete([{"role": "user", "content": "private-document"}])
    assert error.value.code == code
    assert "private" not in str(error.value)
    assert "private-key" not in repr(llm.config)


@pytest.mark.parametrize(
    "exception,code",
    [
        (httpx.ReadTimeout, "MODEL_TIMEOUT"),
        (httpx.ConnectError, "MODEL_UNAVAILABLE"),
    ],
)
async def test_transport_errors(exception, code):
    def handler(request):
        raise exception("private-detail", request=request)

    with pytest.raises(ServiceError) as error:
        await provider(handler).complete([])
    assert error.value.code == code
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "body",
    [
        b"invalid",
        b"null",
        b"{}",
        b'{"choices": []}',
        b'{"choices": [{"message": {"content": null}}]}',
    ],
)
async def test_invalid_gateway_response(body):
    with pytest.raises(ServiceError, match="MODEL_RESPONSE_INVALID"):
        await provider(lambda r: httpx.Response(200, content=body)).complete([])


async def test_response_limit():
    with pytest.raises(ServiceError, match="MODEL_RESPONSE_INVALID"):
        await provider(
            lambda r: httpx.Response(200, content=b"x" * 11), max_response_bytes=10
        ).complete([])


async def test_generic_provider_does_not_force_ingest_options():
    def handler(request):
        assert str(request.url) == "https://model.example/v1/chat/completions"
        assert json.loads(request.content) == {
            "model": "test",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": False,
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})

    assert await provider(handler).complete([{"role": "user", "content": "hello"}]) == "answer"


async def test_unconfigured_provider_never_calls_network():
    def handler(request):
        pytest.fail("unconfigured provider made request")

    llm = OpenAICompatibleProvider(ModelConfig("", ""), transport=httpx.MockTransport(handler))
    assert not llm.ready
    with pytest.raises(ServiceError, match="MODEL_NOT_CONFIGURED"):
        await llm.complete([])


async def test_extractor_uses_injected_provider_and_preserves_domain_validation():
    class FakeProvider:
        ready = True
        model = "fake"
        answer = '{"candidates": [], "notes": []}'

        async def complete(self, messages, **options):
            assert json.loads(messages[1]["content"])["source_lines"] == ["first", "second"]
            assert options == {"temperature": 0, "max_tokens": 12000, "json_object": True}
            return self.answer

    fake = FakeProvider()
    extractor = Extractor(fake)
    assert extractor.ready and extractor.model == "fake"
    assert (await extractor.extract("first\nsecond", {}, [])).candidates == []
    fake.answer = '{"candidates": [{"unsupported": true}]}'
    with pytest.raises(ServiceError, match="MODEL_OUTPUT_INVALID"):
        await extractor.extract("first\nsecond", {}, [])


async def test_model_total_deadline():
    import asyncio

    async def handler(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={"choices": [{"message": {"content": "late"}}]})

    with pytest.raises(ServiceError, match="MODEL_TIMEOUT"):
        await provider(handler, timeout_seconds=0.01).complete([])


async def test_truncated_model_output_has_specific_error():
    llm = provider(
        lambda r: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": '{"candidates": ['},
                    }
                ]
            },
        )
    )
    with pytest.raises(ServiceError, match="MODEL_OUTPUT_TRUNCATED"):
        await llm.complete([])


async def test_schema_error_location_is_safe_and_useful():
    class FakeProvider:
        ready = True
        model = "fake"

        async def complete(self, *args, **kwargs):
            return '{"candidates": [{"name": 42, "private-secret-field": "private-body"}]}'

    with pytest.raises(ServiceError) as error:
        await Extractor(FakeProvider()).extract("", {}, [])
    assert "candidates.0.name：应为字符串" in error.value.message
    assert "缺少必填字段" in error.value.message
    assert "private" not in error.value.message


async def test_remote_disconnect_has_actionable_safe_diagnostics():
    def handler(request):
        raise httpx.RemoteProtocolError("private-token private-document", request=request)

    with pytest.raises(ServiceError) as error:
        await provider(handler).complete([])
    assert error.value.code == "MODEL_UNAVAILABLE"
    assert "RemoteProtocolError" in error.value.message
    assert "模型响应连接中断" in error.value.message
    assert "private" not in error.value.message
