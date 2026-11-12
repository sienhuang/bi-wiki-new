"""设置只在创建运行实例时读取，导入模块不会连接数据库或读取知识资产。"""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def postgres_url(value: SecretStr) -> SecretStr:
    try:
        url = make_url(value.get_secret_value())
    except Exception:
        raise ValueError("数据库 URL 格式无效") from None
    if url.drivername not in {"postgresql", "postgresql+asyncpg"} or not url.database:
        raise ValueError("数据库必须使用 PostgreSQL 并显式指定库名")
    return SecretStr(url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BI_WIKI_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    llm_provider: Literal["openai", "cli"] = "openai"
    llm_cli_command: list[str] = Field(default_factory=list, repr=False)
    llm_timeout_seconds: float = Field(default=300, ge=0.1, le=3600)
    ingest_overhead_seconds: float = Field(default=30, ge=1, le=300)
    ingest_recovery_grace_seconds: float = Field(default=60, ge=1, le=600)

    @property
    def ingest_timeouts(self) -> dict[str, float]:
        execution = self.llm_timeout_seconds + self.ingest_overhead_seconds
        return {
            "model_seconds": self.llm_timeout_seconds,
            "execution_seconds": execution,
            "recovery_seconds": execution + self.ingest_recovery_grace_seconds,
            "client_seconds": execution + 30,
        }

    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: SecretStr | None = Field(default=None, repr=False)
    raw_root: Path = PROJECT_ROOT / "var" / "raw"
    raw_backend: Literal["local", "s3"] = "local"
    s3_bucket: str = ""
    s3_prefix: str = "bi-wiki/raw"
    s3_endpoint_url: str = ""
    s3_region: str = "us-east-1"
    s3_access_key: SecretStr | None = Field(default=None, repr=False)
    s3_secret_key: SecretStr | None = Field(default=None, repr=False)
    s3_session_token: SecretStr | None = Field(default=None, repr=False)
    s3_addressing_style: Literal["auto", "path", "virtual"] = "auto"

    @field_validator("s3_prefix")
    @classmethod
    def validate_s3_prefix(cls, value: str) -> str:
        value = value.strip("/")
        if (
            "\\" in value
            or any(ord(c) < 32 for c in value)
            or any(part in {".", "..", ""} for part in value.split("/"))
            and value
        ):
            raise ValueError("S3 prefix 必须为有效对象前缀")
        return value

    @field_validator("s3_endpoint_url")
    @classmethod
    def validate_s3_endpoint(cls, value: str) -> str:
        if value:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("S3 endpoint 必须为不含凭据的 HTTP(S) 地址")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_s3_config(self):
        if self.raw_backend == "s3":
            if not self.s3_bucket.strip():
                raise ValueError("S3 RawStore 必须配置 bucket")
            if bool(self.s3_access_key) != bool(self.s3_secret_key):
                raise ValueError("S3 access key 和 secret key 必须同时配置")
            if self.s3_session_token and not self.s3_access_key:
                raise ValueError("显式S3 session token必须同时配置access/secret key")
        return self

    @field_validator("llm_base_url")
    @classmethod
    def validate_model_url(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("模型地址必须为不含凭据的 HTTP(S) 地址")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("非本地模型地址必须使用 HTTPS")
        return value.rstrip("/")

    moa_portal_url: str = "https://login.moa.moonton.net"
    moa_auth_url: str = "https://auth-api.moa.moonton.net"
    moa_project_id: int = Field(default=1564, gt=0)
    moa_timeout_seconds: float = Field(default=10, ge=1, le=30)

    @field_validator("moa_portal_url", "moa_auth_url")
    @classmethod
    def validate_moa_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("MOA 地址必须为不含凭据、路径或查询参数的 HTTPS origin")
        return value.rstrip("/")

    database_url: SecretStr = Field(repr=False)
    test_database_url: SecretStr | None = Field(default=None, repr=False)
    database_schema: str = Field(default="public", pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    database_timeout_seconds: float = Field(default=5, ge=0.1, le=60)
    initialize_database: bool = True
    host: Literal["127.0.0.1", "::1", "localhost"] = "127.0.0.1"
    port: int = Field(default=8020, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_file: Path | None = None
    log_backup_count: int = Field(default=7, ge=1, le=365)
    knowledge_root: Path = PROJECT_ROOT / "knowledge"

    @field_validator("database_url", "test_database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        return postgres_url(value) if value is not None else None

    @field_validator("knowledge_root", "raw_root")
    @classmethod
    def resolve_knowledge_root(cls, value: Path) -> Path:
        return (PROJECT_ROOT / value).resolve() if not value.is_absolute() else value.resolve()


def get_settings() -> Settings:
    return Settings()


def checked_test_url(settings: Settings) -> str:
    """在任何测试 DDL 之前拒绝误用运行库；不猜测或复用现有项目的连接配置。"""
    if settings.test_database_url is None:
        raise ValueError("请显式配置 BI_WIKI_TEST_DATABASE_URL")
    target = make_url(settings.test_database_url.get_secret_value())
    runtime = make_url(settings.database_url.get_secret_value())
    if not target.database or not target.database.lower().endswith("_test"):
        raise ValueError("测试库名必须以 _test 结尾")
    if target == runtime or target.database == runtime.database:
        raise ValueError("测试库不能与运行库相同")
    return target.render_as_string(hide_password=False)
