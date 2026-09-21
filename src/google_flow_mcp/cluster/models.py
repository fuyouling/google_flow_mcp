import time
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field


class TaskType(str, Enum):
    VIDEO_CREATE = "video_create"
    VIDEO_CREATE_BY_UPLOAD = "video_create_by_upload"
    IMAGE_CREATE = "image_create"
    IMAGE_CREATE_BY_UPLOAD = "image_create_by_upload"
    CHARACTER_CREATE = "character_create"
    CHARACTER_CREATE_BY_UPLOAD = "character_create_by_upload"
    PROJECT_CREATE = "project_create"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    ASSIGNED = "assigned"
    SYNCING_ASSETS = "syncing_assets"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkerState(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    DISCONNECTED = "disconnected"
    UNHEALTHY = "unhealthy"


class AssetType(str, Enum):
    IMAGE = "image"
    CHARACTER = "character"
    VIDEO = "video"


class AssetMetadata(BaseModel):
    name: str
    asset_type: AssetType = AssetType.IMAGE
    file_name: str
    file_path: str = ""
    file_size: int = 0
    sha256: str = ""
    created_by_worker: str = ""
    created_at: float = Field(default_factory=time.time)


class TaskPayload(BaseModel):
    job_id: str
    task_type: TaskType
    project_alias: str
    params: Dict[str, Any] = Field(default_factory=dict)
    required_assets: List[str] = Field(default_factory=list)
    cost_credits: int = 0
    deducted_daily_free: int = 0
    deducted_balance: int = 0
    created_at: float = Field(default_factory=time.time)
    retry_count: int = 0
    target_worker_id: Optional[str] = None


class TaskResult(BaseModel):
    job_id: str
    worker_id: str
    status: TaskStatus
    result_data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    produced_assets: List[Dict[str, Any]] = Field(default_factory=list)
    completed_at: float = Field(default_factory=time.time)


class WorkerInfo(BaseModel):
    worker_id: str
    ip: str = "127.0.0.1"
    account: str = ""
    credits: Optional[int] = None
    daily_free_remaining: int = 50
    state: WorkerState = WorkerState.IDLE
    current_job_id: Optional[str] = None
    project_mappings: Dict[str, str] = Field(default_factory=dict)
    cached_assets: Set[str] = Field(default_factory=set)
    last_heartbeat: float = Field(default_factory=time.time)
    consecutive_failures: int = 0
