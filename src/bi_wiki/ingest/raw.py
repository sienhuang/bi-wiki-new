"""Managed content-addressed immutable raw files. No client paths accepted."""

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Protocol

from bi_wiki.core.errors import ServiceError


class RawStorage(Protocol):
    def put(self, owner: str, data: bytes) -> str: ...
    def read(self, owner: str, digest: str) -> bytes: ...
    def close(self) -> None: ...


class RawStore:
    def __init__(self, root: Path):
        self.root = root

    def path(self, owner: str, digest: str) -> Path:
        return self.root / hashlib.sha256(owner.encode()).hexdigest() / digest

    def put(self, owner: str, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        target = self.path(owner, digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._check_path(target)
        fd, temp = tempfile.mkstemp(dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temp, target)  # exclusive creation; never replace existing raw
            except FileExistsError:
                pass
            self.read(owner, digest)
        finally:
            os.unlink(temp)
        return digest

    def close(self) -> None:
        pass

    def _check_path(self, path: Path) -> None:
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ServiceError("RAW_PATH_INVALID", "原始资料存储路径不允许符号链接", 409)

    def read(self, owner: str, digest: str) -> bytes:
        path = self.path(owner, digest)
        self._check_path(path)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as stream:
                data = stream.read(131073)
        except OSError:
            raise ServiceError("RAW_UNAVAILABLE", "原始资料不可读取", 409) from None
        if hashlib.sha256(data).hexdigest() != digest:
            raise ServiceError("SOURCE_CHANGED", "原始资料校验失败，已阻止处理", 409)
        return data
