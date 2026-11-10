import json
import logging

import pytest
from pydantic import ValidationError

from bi_wiki.core.config import Settings, checked_test_url
from bi_wiki.core.logging import JsonFormatter

RUNTIME = "postgresql+asyncpg://user:secret@localhost/runtime"
TEST = "postgresql+asyncpg://user:secret@localhost/runtime_test"


def settings(**kwargs):
    return Settings(_env_file=None, database_url=RUNTIME, **kwargs)


@pytest.mark.parametrize("url", ["sqlite:///test.db", "mysql://localhost/db", "not-a-url"])
def test_rejects_other_databases(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=url)


def test_settings_normalize_postgresql_and_hide_credentials():
    config = Settings(_env_file=None, database_url="postgresql://user:sensitive@localhost/db")
    assert config.database_url.get_secret_value().startswith("postgresql+asyncpg://")
    assert "sensitive" not in repr(config)


def test_environment_overrides_dotenv(tmp_path, monkeypatch):
    source = tmp_path / ".env"
    source.write_text("BI_WIKI_PORT=8021\nBI_WIKI_DATABASE_URL=" + RUNTIME)
    monkeypatch.setenv("BI_WIKI_PORT", "8022")
    config = Settings(_env_file=source)
    assert config.port == 8022


@pytest.mark.parametrize("updates", [{"host": "0.0.0.0"}, {"port": 0}, {"database_schema": "a;b"}])
def test_local_configuration_constraints(updates):
    with pytest.raises(ValidationError):
        settings(**updates)


def test_requires_explicit_test_database():
    with pytest.raises(ValueError, match="显式"):
        checked_test_url(settings())


def test_rejects_runtime_database_for_tests():
    with pytest.raises(ValueError, match="相同"):
        config = Settings(_env_file=None, database_url=TEST, test_database_url=TEST)
        checked_test_url(config)


def test_rejects_non_test_database_name():
    with pytest.raises(ValueError, match="_test"):
        checked_test_url(settings(test_database_url="postgresql://localhost/production"))


def test_accepts_isolated_postgresql_test_database():
    assert checked_test_url(settings(test_database_url=TEST)) == TEST


def test_log_formatter_only_includes_selected_fields():
    record = logging.LogRecord("bi_wiki", logging.INFO, "", 0, "request_completed", (), None)
    record.request_id = "test-id"
    record.database_url = RUNTIME
    result = json.loads(JsonFormatter().format(record))
    assert result["request_id"] == "test-id"
    assert "secret" not in json.dumps(result)
