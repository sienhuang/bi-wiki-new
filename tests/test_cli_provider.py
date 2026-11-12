"""Real local subprocesses stand in for a CLI model; no external model calls."""

import asyncio
import sys

import pytest

from bi_wiki.core.config import Settings
from bi_wiki.core.errors import ServiceError
from bi_wiki.llm.cli import CliProvider
from bi_wiki.llm.factory import create_provider
from bi_wiki.llm.openai_compat import OpenAICompatibleProvider


def cli(code, **options):
    return CliProvider([sys.executable, "-c", code, "{model}"], "test-model", **options)


async def test_cli_stdin_and_model_argument():
    code = "import sys; assert sys.argv[1]=='test-model'; print(sys.stdin.read())"
    answer = await cli(code).complete(
        [{"role": "system", "content": "规则"}, {"role": "user", "content": "资料"}],
        json_object=True,
    )
    assert "[system]\n规则" in answer
    assert "[user]\n资料" in answer
    assert "JSON" in answer


async def test_stderr_drained_concurrently():
    code = "import sys; sys.stderr.write('x'*200000); sys.stderr.flush(); print('OK')"
    assert await cli(code, timeout_seconds=5).complete([]) == "OK"


@pytest.mark.parametrize(
    "code,error",
    [
        ("import sys; sys.stderr.write('private-key'); sys.exit(2)", "MODEL_CLI_FAILED"),
        ("pass", "MODEL_RESPONSE_INVALID"),
        ("print('x'*100)", "MODEL_RESPONSE_INVALID"),
        ("import sys; sys.stderr.write('x'*100)", "MODEL_RESPONSE_INVALID"),
    ],
)
async def test_cli_failures(code, error):
    with pytest.raises(ServiceError) as caught:
        await cli(code, max_response_bytes=50).complete([])
    assert caught.value.code == error
    assert "private-key" not in str(caught.value)


async def test_missing_executable():
    with pytest.raises(ServiceError, match="MODEL_CLI_FAILED"):
        await CliProvider(["/no-such-model-command"], "test").complete([])


@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_and_cancellation_reap_process(monkeypatch, cancel):
    spawned = []
    started = asyncio.Event()
    original = asyncio.create_subprocess_exec

    async def record(*args, **kwargs):
        process = await original(*args, **kwargs)
        spawned.append(process)
        started.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", record)
    task = asyncio.create_task(
        cli("import time; time.sleep(30)", timeout_seconds=5 if cancel else 0.1).complete([])
    )
    if cancel:
        async with asyncio.timeout(3):
            await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(ServiceError, match="MODEL_TIMEOUT"):
            await task
    assert spawned and spawned[0].returncode is not None


async def test_unconfigured_cli():
    provider = CliProvider([], "test")
    assert not provider.ready
    with pytest.raises(ServiceError, match="MODEL_NOT_CONFIGURED"):
        await provider.complete([])


def test_new_env_configuration_and_factory(monkeypatch):
    monkeypatch.setenv("BI_WIKI_LLM_PROVIDER", "cli")
    monkeypatch.setenv("BI_WIKI_LLM_MODEL", "test-model")
    monkeypatch.setenv("BI_WIKI_LLM_CLI_COMMAND", '["command", "--model", "{model}"]')
    monkeypatch.setenv("BI_WIKI_LLM_BASE_URL", "https://example.com/v1")
    settings = Settings(_env_file=None, database_url="postgresql://test@localhost/test")
    assert settings.llm_base_url == "https://example.com/v1"
    provider = create_provider(settings)
    assert isinstance(provider, CliProvider) and provider.ready
    assert isinstance(
        create_provider(settings.model_copy(update={"llm_provider": "openai"})),
        OpenAICompatibleProvider,
    )


def test_old_configuration_names_are_not_aliases(monkeypatch):
    for key in ("BI_WIKI_LLM_BASE_URL", "BI_WIKI_LLM_MODEL", "BI_WIKI_LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BI_WIKI_INGEST_MODEL_URL", "https://old.example/v1")
    monkeypatch.setenv("BI_WIKI_INGEST_MODEL", "old-model")
    settings = Settings(_env_file=None, database_url="postgresql://test@localhost/test")
    assert not settings.llm_base_url and not settings.llm_model
