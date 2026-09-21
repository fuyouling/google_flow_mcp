from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class WorkerMessage(_message.Message):
    __slots__ = ("register", "heartbeat", "progress", "completed", "failed", "project_mapping", "account_info")
    REGISTER_FIELD_NUMBER: _ClassVar[int]
    HEARTBEAT_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_FIELD_NUMBER: _ClassVar[int]
    FAILED_FIELD_NUMBER: _ClassVar[int]
    PROJECT_MAPPING_FIELD_NUMBER: _ClassVar[int]
    ACCOUNT_INFO_FIELD_NUMBER: _ClassVar[int]
    register: RegisterRequest
    heartbeat: HeartbeatRequest
    progress: TaskProgressReport
    completed: TaskCompletedReport
    failed: TaskFailedReport
    project_mapping: ProjectMappingUpdate
    account_info: AccountInfoUpdate
    def __init__(self, register: _Optional[_Union[RegisterRequest, _Mapping]] = ..., heartbeat: _Optional[_Union[HeartbeatRequest, _Mapping]] = ..., progress: _Optional[_Union[TaskProgressReport, _Mapping]] = ..., completed: _Optional[_Union[TaskCompletedReport, _Mapping]] = ..., failed: _Optional[_Union[TaskFailedReport, _Mapping]] = ..., project_mapping: _Optional[_Union[ProjectMappingUpdate, _Mapping]] = ..., account_info: _Optional[_Union[AccountInfoUpdate, _Mapping]] = ...) -> None: ...

class RegisterRequest(_message.Message):
    __slots__ = ("worker_id", "account", "project_mappings", "cached_assets")
    class ProjectMappingsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    ACCOUNT_FIELD_NUMBER: _ClassVar[int]
    PROJECT_MAPPINGS_FIELD_NUMBER: _ClassVar[int]
    CACHED_ASSETS_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    account: str
    project_mappings: _containers.ScalarMap[str, str]
    cached_assets: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, worker_id: _Optional[str] = ..., account: _Optional[str] = ..., project_mappings: _Optional[_Mapping[str, str]] = ..., cached_assets: _Optional[_Iterable[str]] = ...) -> None: ...

class HeartbeatRequest(_message.Message):
    __slots__ = ("worker_id",)
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    def __init__(self, worker_id: _Optional[str] = ...) -> None: ...

class TaskProgressReport(_message.Message):
    __slots__ = ("job_id", "status", "message", "progress_percent", "progress_text", "elapsed_seconds", "next_action")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_PERCENT_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_TEXT_FIELD_NUMBER: _ClassVar[int]
    ELAPSED_SECONDS_FIELD_NUMBER: _ClassVar[int]
    NEXT_ACTION_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    status: str
    message: str
    progress_percent: int
    progress_text: str
    elapsed_seconds: float
    next_action: str
    def __init__(self, job_id: _Optional[str] = ..., status: _Optional[str] = ..., message: _Optional[str] = ..., progress_percent: _Optional[int] = ..., progress_text: _Optional[str] = ..., elapsed_seconds: _Optional[float] = ..., next_action: _Optional[str] = ...) -> None: ...

class TaskCompletedReport(_message.Message):
    __slots__ = ("job_id", "worker_id", "status", "result_json")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    RESULT_JSON_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    worker_id: str
    status: str
    result_json: str
    def __init__(self, job_id: _Optional[str] = ..., worker_id: _Optional[str] = ..., status: _Optional[str] = ..., result_json: _Optional[str] = ...) -> None: ...

class TaskFailedReport(_message.Message):
    __slots__ = ("job_id", "worker_id", "error")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    worker_id: str
    error: str
    def __init__(self, job_id: _Optional[str] = ..., worker_id: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class ProjectMappingUpdate(_message.Message):
    __slots__ = ("worker_id", "project_alias", "local_uuid")
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    PROJECT_ALIAS_FIELD_NUMBER: _ClassVar[int]
    LOCAL_UUID_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    project_alias: str
    local_uuid: str
    def __init__(self, worker_id: _Optional[str] = ..., project_alias: _Optional[str] = ..., local_uuid: _Optional[str] = ...) -> None: ...

class AccountInfoUpdate(_message.Message):
    __slots__ = ("worker_id", "email", "credits")
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    CREDITS_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    email: str
    credits: int
    def __init__(self, worker_id: _Optional[str] = ..., email: _Optional[str] = ..., credits: _Optional[int] = ...) -> None: ...

class MasterMessage(_message.Message):
    __slots__ = ("registered", "execute", "cancel")
    REGISTERED_FIELD_NUMBER: _ClassVar[int]
    EXECUTE_FIELD_NUMBER: _ClassVar[int]
    CANCEL_FIELD_NUMBER: _ClassVar[int]
    registered: RegisterResponse
    execute: ExecuteTask
    cancel: CancelTask
    def __init__(self, registered: _Optional[_Union[RegisterResponse, _Mapping]] = ..., execute: _Optional[_Union[ExecuteTask, _Mapping]] = ..., cancel: _Optional[_Union[CancelTask, _Mapping]] = ...) -> None: ...

class RegisterResponse(_message.Message):
    __slots__ = ("worker_id", "success")
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    success: bool
    def __init__(self, worker_id: _Optional[str] = ..., success: _Optional[bool] = ...) -> None: ...

class ExecuteTask(_message.Message):
    __slots__ = ("payload_json",)
    PAYLOAD_JSON_FIELD_NUMBER: _ClassVar[int]
    payload_json: str
    def __init__(self, payload_json: _Optional[str] = ...) -> None: ...

class CancelTask(_message.Message):
    __slots__ = ("job_id",)
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    def __init__(self, job_id: _Optional[str] = ...) -> None: ...
