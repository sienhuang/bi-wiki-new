"""Immutable, owner-scoped S3 raw objects. Caller runs blocking operations in a thread."""

import hashlib
import re

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from bi_wiki.core.config import Settings
from bi_wiki.core.errors import ServiceError
from bi_wiki.ingest.raw import RawStorage, RawStore


class S3RawStore:
    def __init__(self, bucket: str, prefix: str, client):
        self.bucket, self.prefix, self.client = bucket, prefix.strip("/"), client

    def key(self, owner: str, digest: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ServiceError("INVALID_SOURCE_HASH", "来源哈希格式无效", 422)
        suffix = hashlib.sha256(owner.encode()).hexdigest() + "/" + digest
        return f"{self.prefix}/{suffix}" if self.prefix else suffix

    def put(self, owner: str, data: bytes) -> str:
        if not data or len(data) > 131072:
            raise ServiceError("SOURCE_LIMIT", "原始资料须为非空且不超过128 KiB", 413)
        digest = hashlib.sha256(data).hexdigest()
        key = self.key(owner, digest)
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                IfNoneMatch="*",
                ContentType="application/octet-stream",
            )
        except ClientError as exc:
            # Only a failed conditional create is an existing-object case.
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 412:
                raise ServiceError(
                    "RAW_UNAVAILABLE", "S3原始资料写入失败，请检查存储配置", 503
                ) from None
        except (BotoCoreError, OSError):
            raise ServiceError(
                "RAW_UNAVAILABLE", "S3原始资料写入失败，请检查存储配置", 503
            ) from None
        # Verify both newly written and existing objects; never trust an ETag as SHA-256.
        self.read(owner, digest)
        return digest

    def read(self, owner: str, digest: str) -> bytes:
        key = self.key(owner, digest)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"]
            try:
                data = body.read(131073)
            finally:
                body.close()
        except (BotoCoreError, ClientError, OSError):
            raise ServiceError(
                "RAW_UNAVAILABLE", "S3原始资料不可读取，请检查对象和访问权限", 503
            ) from None
        if len(data) > 131072 or hashlib.sha256(data).hexdigest() != digest:
            raise ServiceError("SOURCE_CHANGED", "原始资料校验失败，已阻止处理", 409)
        return data

    def close(self) -> None:
        self.client.close()


def create_raw_store(settings: Settings) -> RawStorage:
    if settings.raw_backend == "local":
        return RawStore(settings.raw_root)
    try:
        session = boto3.session.Session(
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key.get_secret_value()
            if settings.s3_access_key
            else None,
            aws_secret_access_key=settings.s3_secret_key.get_secret_value()
            if settings.s3_secret_key
            else None,
            aws_session_token=settings.s3_session_token.get_secret_value()
            if settings.s3_session_token
            else None,
        )
        client = session.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            config=Config(
                connect_timeout=5,
                read_timeout=15,
                retries={"total_max_attempts": 2, "mode": "standard"},
                s3={"addressing_style": settings.s3_addressing_style},
            ),
        )
        return S3RawStore(settings.s3_bucket, settings.s3_prefix, client)
    except (BotoCoreError, ClientError, ValueError):
        raise ServiceError("RAW_UNAVAILABLE", "S3客户端初始化失败，请检查存储配置", 503) from None
