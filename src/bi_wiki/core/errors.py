from dataclasses import dataclass


@dataclass
class ServiceError(Exception):
    code: str
    message: str
    status_code: int


class RunNotFound(ServiceError):
    def __init__(self) -> None:
        super().__init__("RUN_NOT_FOUND", "任务不存在", 404)


class InvalidTransition(ServiceError):
    def __init__(self) -> None:
        super().__init__("INVALID_RUN_TRANSITION", "任务状态不允许此转换", 409)


class RunConflict(ServiceError):
    def __init__(self) -> None:
        super().__init__("RUN_VERSION_CONFLICT", "任务已发生变化，请重新读取", 409)
