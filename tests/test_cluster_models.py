import pytest
from google_flow_mcp.cluster.models import (
    AssetMetadata,
    AssetType,
    TaskPayload,
    TaskResult,
    TaskStatus,
    TaskType,
    WorkerInfo,
    WorkerState,
)


def test_asset_metadata_defaults():
    meta = AssetMetadata(
        name="hero_stand",
        file_name="hero_stand.png",
        file_size=1024,
        sha256="abc123hash",
        created_by_worker="worker_1",
    )
    assert meta.name == "hero_stand"
    assert meta.asset_type == AssetType.IMAGE
    assert meta.file_size == 1024
    assert meta.created_at > 0


def test_task_payload_serialization():
    payload = TaskPayload(
        job_id="job-123",
        task_type=TaskType.VIDEO_CREATE,
        project_alias="the_secret_garden",
        params={"prompt": "A beautiful garden", "model_name": "Omni 1.1 Flash"},
        required_assets=["start_frame_img", "hero_char"],
    )
    data = payload.model_dump()
    assert data["job_id"] == "job-123"
    assert data["task_type"] == "video_create"
    assert data["project_alias"] == "the_secret_garden"
    assert len(data["required_assets"]) == 2

    deserialized = TaskPayload(**data)
    assert deserialized.job_id == payload.job_id
    assert deserialized.task_type == TaskType.VIDEO_CREATE


def test_task_result():
    res = TaskResult(
        job_id="job-123",
        worker_id="worker_pc2",
        status=TaskStatus.COMPLETED,
        result_data={"video_url": "https://flow.google.com/video/xyz"},
        produced_assets=[{"name": "output_vid", "type": "video", "local_path": "/tmp/v.mp4"}],
    )
    assert res.status == TaskStatus.COMPLETED
    assert res.worker_id == "worker_pc2"
    assert len(res.produced_assets) == 1


def test_worker_info():
    info = WorkerInfo(
        worker_id="worker_test",
        ip="192.168.1.50",
        account="user2@gmail.com",
        cached_assets={"hero_1", "scene_2"},
    )
    assert info.state == WorkerState.IDLE
    assert "hero_1" in info.cached_assets
    assert info.account == "user2@gmail.com"
