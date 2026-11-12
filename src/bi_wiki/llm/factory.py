"""Resolve application configuration at the composition boundary."""

from bi_wiki.core.config import Settings
from bi_wiki.llm.base import ModelProvider
from bi_wiki.llm.cli import CliProvider
from bi_wiki.llm.openai_compat import ModelConfig, OpenAICompatibleProvider


def create_provider(settings: Settings) -> ModelProvider:
    if settings.llm_provider == "cli":
        return CliProvider(
            settings.llm_cli_command,
            settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    return OpenAICompatibleProvider(
        ModelConfig(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    )
