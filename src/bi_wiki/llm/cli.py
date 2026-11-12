"""Plain-text stdin/stdout adapter for locally configured model executables."""

import asyncio
import os
import signal
from collections.abc import Sequence

from bi_wiki.core.errors import ServiceError
from bi_wiki.llm.base import Message


class CliProvider:
    def __init__(
        self,
        command: Sequence[str],
        model: str,
        *,
        timeout_seconds: float = 120,
        max_response_bytes: int = 1_000_000,
    ):
        self._command = tuple(command)
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

    @property
    def ready(self) -> bool:
        return bool(self._command and self._command[0].strip() and self.model)

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_object: bool = False,
    ) -> str:
        if not self.ready:
            raise ServiceError("MODEL_NOT_CONFIGURED", "请先配置模型命令和模型名", 503)
        # Arbitrary CLIs have no common sampling flags. Configure those in command args;
        # max_tokens is not a hard limit here. Byte and time limits are enforced below.
        prompt = "\n\n".join(f"[{item['role']}]\n{item['content']}" for item in messages)
        if json_object:
            prompt += "\n\n只返回一个 JSON 对象，不要使用 Markdown 代码块。"
        process = None
        tasks = []
        try:
            async with asyncio.timeout(self.timeout_seconds):
                process = await asyncio.create_subprocess_exec(
                    *(arg.replace("{model}", self.model) for arg in self._command),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=(os.name == "posix"),
                )

                async def feed():
                    try:
                        process.stdin.write(prompt.encode("utf-8"))
                        await process.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    finally:
                        process.stdin.close()

                async def read(stream, *, keep):
                    data = bytearray()
                    size = 0
                    while chunk := await stream.read(65536):
                        size += len(chunk)
                        if size > self.max_response_bytes:
                            raise ServiceError(
                                "MODEL_RESPONSE_INVALID", "模型命令输出超过大小限制", 502
                            )
                        if keep:
                            data.extend(chunk)
                    return data

                tasks = [
                    asyncio.create_task(feed()),
                    asyncio.create_task(read(process.stdout, keep=True)),
                    asyncio.create_task(read(process.stderr, keep=False)),
                    asyncio.create_task(process.wait()),
                ]
                _, output, _, returncode = await asyncio.gather(*tasks)
                if returncode:
                    raise ServiceError(
                        "MODEL_CLI_FAILED", "模型命令执行失败，请检查服务端命令配置与授权", 503
                    )
                answer = output.decode("utf-8").strip()
                if not answer:
                    raise ServiceError("MODEL_RESPONSE_INVALID", "模型命令未返回有效文本", 502)
                return answer
        except TimeoutError:
            raise ServiceError("MODEL_TIMEOUT", "模型调用超时，请稍后重试", 504) from None
        except (OSError, ValueError):
            raise ServiceError("MODEL_CLI_FAILED", "模型命令不可用或输出编码无效", 503) from None
        finally:
            # Kill the process group as well as children holding inherited pipes.
            if process is not None:
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    elif process.returncode is None:
                        process.kill()
                except ProcessLookupError:
                    pass
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await process.wait()
