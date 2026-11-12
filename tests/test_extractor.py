"""Protocol tests use MockTransport; no external model calls or credentials."""

import json

import httpx
import pytest
from pydantic import SecretStr

from bi_wiki.core.config import Settings
from bi_wiki.core.errors import ServiceError
from bi_wiki.ingest.extractor import Extractor
from bi_wiki.llm.factory import create_provider


@pytest.mark.parametrize("mode", ["valid", "malformed", "unavailable"])
async def test_model_protocol_and_failure_sanitization(monkeypatch, mode):
    def handler(request):
        assert str(request.url) == "https://model.example/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer fake-key"
        payload = json.loads(request.content)
        assert payload["model"] == "test-model"
        assert payload["response_format"] == {"type": "json_object"}
        if mode == "unavailable":
            return httpx.Response(503, text="private-provider-detail")
        content = (
            json.dumps({"candidates": [], "notes": ["没有足够证据"]})
            if mode == "valid"
            else "private-invalid-response"
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "bi_wiki.llm.openai_compat.httpx.AsyncClient",
        lambda **kwargs: real_client(**(kwargs | {"transport": httpx.MockTransport(handler)})),
    )
    config = Settings(
        _env_file=None,
        database_url="postgresql://test@localhost/test",
        llm_base_url="https://model.example/v1",
        llm_model="test-model",
        llm_api_key=SecretStr("fake-key"),
    )
    extractor = Extractor(create_provider(config))
    if mode == "valid":
        result = await extractor.extract("文档", {}, [])
        assert result.candidates == []
    else:
        with pytest.raises(ServiceError) as error:
            await extractor.extract("文档", {}, [])
        assert error.value.code == (
            "MODEL_UNAVAILABLE" if mode == "unavailable" else "MODEL_OUTPUT_INVALID"
        )
        assert "private" not in str(error.value)
        assert "fake-key" not in str(error.value)
