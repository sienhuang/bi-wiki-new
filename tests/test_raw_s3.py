"""S3 protocol tests use botocore Stubber; no real bucket or credentials."""

import hashlib
import io

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber
from pydantic import ValidationError

from bi_wiki.core.config import Settings
from bi_wiki.core.errors import ServiceError
from bi_wiki.ingest.raw import RawStore
from bi_wiki.ingest.raw_s3 import S3RawStore, create_raw_store


@pytest.fixture
def store():
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        endpoint_url="https://s3.example",
    )
    with Stubber(client) as stub:
        yield S3RawStore("test-bucket", "wiki/raw", client), stub
        stub.assert_no_pending_responses()
    client.close()


def read_response(data):
    body = StreamingBody(io.BytesIO(data), len(data))
    return {"Body": body}, body


@pytest.mark.parametrize("duplicate", [False, True])
def test_conditional_put_and_verified_read(store, duplicate):
    raw, stub = store
    data = "原始资料".encode()
    digest = hashlib.sha256(data).hexdigest()
    params = {"Bucket": "test-bucket", "Key": raw.key("owner", digest)}
    put = params | {"Body": data, "IfNoneMatch": "*", "ContentType": "application/octet-stream"}
    if duplicate:
        stub.add_client_error(
            "put_object", "PreconditionFailed", http_status_code=412, expected_params=put
        )
    else:
        stub.add_response("put_object", {}, put)
    response, body = read_response(data)
    stub.add_response("get_object", response, params)
    assert raw.put("owner", data) == digest
    assert body._raw_stream.closed
    assert raw.key("owner", digest) != raw.key("another", digest)


@pytest.mark.parametrize(
    "status,code",
    [(403, "AccessDenied"), (409, "ConditionalRequestConflict"), (501, "NotImplemented")],
)
def test_write_errors_do_not_fallback_to_overwrite(store, status, code):
    raw, stub = store
    stub.add_client_error(
        "put_object", code, service_message="private credentials", http_status_code=status
    )
    with pytest.raises(ServiceError) as error:
        raw.put("owner", b"data")
    assert error.value.code == "RAW_UNAVAILABLE"
    assert "private" not in str(error.value)


@pytest.mark.parametrize("data", [b"tampered", b"x" * 131073])
def test_corrupt_or_oversize_read_is_rejected_and_closed(store, data):
    raw, stub = store
    response, body = read_response(data)
    stub.add_response("get_object", response)
    with pytest.raises(ServiceError, match="SOURCE_CHANGED"):
        raw.read("owner", hashlib.sha256(b"original").hexdigest())
    assert body._raw_stream.closed


def test_missing_object_and_invalid_digest(store):
    raw, stub = store
    stub.add_client_error("get_object", "NoSuchKey", http_status_code=404)
    with pytest.raises(ServiceError, match="RAW_UNAVAILABLE"):
        raw.read("owner", "a" * 64)
    with pytest.raises(ServiceError, match="INVALID_SOURCE_HASH"):
        raw.read("owner", "../escape")


def test_s3_configuration_and_local_default(tmp_path):
    base = dict(_env_file=None, database_url="postgresql://test@localhost/test")
    assert isinstance(create_raw_store(Settings(**base, raw_root=tmp_path)), RawStore)
    with pytest.raises(ValidationError):
        Settings(**base, raw_backend="s3")
    with pytest.raises(ValidationError):
        Settings(**base, raw_backend="s3", s3_bucket="test", s3_access_key="test")
    with pytest.raises(ValidationError):
        Settings(**base, s3_prefix="../escape")
    with pytest.raises(ValidationError):
        Settings(**base, s3_endpoint_url="https://secret:password@example.com")
    settings = Settings(**base, raw_backend="s3", s3_bucket="test", s3_prefix="/raw/")
    assert settings.s3_prefix == "raw"


def test_existing_corrupt_object_is_not_overwritten(store):
    raw, stub = store
    stub.add_client_error("put_object", "PreconditionFailed", http_status_code=412)
    response, _ = read_response(b"corrupt")
    stub.add_response("get_object", response)
    with pytest.raises(ServiceError, match="SOURCE_CHANGED"):
        raw.put("owner", b"original")


async def test_s3_upload_and_read_api(client, store):
    import base64

    connection, app = client
    raw, stub = store
    app.state.ingest.raw = raw
    data = b"raw source"
    digest = hashlib.sha256(data).hexdigest()
    params = {"Bucket": "test-bucket", "Key": raw.key("test-user", digest)}
    stub.add_response(
        "put_object",
        {},
        params
        | {
            "Body": data,
            "IfNoneMatch": "*",
            "ContentType": "application/octet-stream",
        },
    )
    response, _ = read_response(data)
    stub.add_response("get_object", response, params)
    payload = {"filename": "source.md", "content_base64": base64.b64encode(data).decode()}
    result = await connection.post("/api/v1/sources", json=payload)
    assert result.status_code == 201
    source = result.json()["data"]["source"]
    # Registry deduplication makes no extra storage request.
    duplicate = await connection.post("/api/v1/sources", json=payload)
    assert duplicate.json()["data"]["duplicate"] is True
    response, _ = read_response(data)
    stub.add_response("get_object", response, params)
    read = await connection.get("/api/v1/sources/" + source["id"])
    assert read.json()["data"]["text"] == "raw source"
