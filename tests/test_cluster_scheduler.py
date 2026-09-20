import time
import pytest
from google_flow_mcp.cluster.scheduler import ClusterScheduler
from google_flow_mcp.cluster.models import (
    TaskPayload,
    TaskResult,
    TaskStatus,
    TaskType,
    WorkerState,
)


def test_scheduler_worker_registration_and_heartbeat():
    scheduler = ClusterScheduler(heartbeat_timeout=1.0)
    try:
        messages = []
        sender = lambda msg: messages.append(msg)

        info = scheduler.register_worker(
            worker_id="worker_1",
            ip="192.168.1.10",
            account="user1@gmail.com",
            cached_assets={"asset_A", "asset_B"},
            sender=sender,
        )
        assert info.worker_id == "worker_1"
        assert len(scheduler.get_workers()) == 1

        scheduler.heartbeat("worker_1")
        assert scheduler.workers["worker_1"].last_heartbeat > 0
    finally:
        scheduler.stop()


def test_scheduler_affinity_routing():
    scheduler = ClusterScheduler()
    try:
        w1_msgs = []
        w2_msgs = []

        # Worker 1 has asset_A
        scheduler.register_worker(
            worker_id="w1",
            cached_assets={"asset_A"},
            sender=lambda m: w1_msgs.append(m),
        )
        # Worker 2 has asset_B and asset_C
        scheduler.register_worker(
            worker_id="w2",
            cached_assets={"asset_B", "asset_C"},
            sender=lambda m: w2_msgs.append(m),
        )

        # Submit task requiring asset_B and asset_C
        # Worker 2 has affinity score 2, Worker 1 has score 0 -> Worker 2 MUST be chosen!
        job_id = scheduler.submit_task(
            task_type=TaskType.VIDEO_CREATE,
            project_alias="my_proj",
            params={"prompt": "test video"},
            required_assets=["asset_B", "asset_C"],
        )

        assert len(w2_msgs) == 1
        assert w2_msgs[0]["action"] == "execute"
        assert w2_msgs[0]["payload"]["job_id"] == job_id
        assert len(w1_msgs) == 0

        assert scheduler.workers["w2"].state == WorkerState.BUSY
        assert scheduler.workers["w1"].state == WorkerState.IDLE
    finally:
        scheduler.stop()


def test_scheduler_failover_and_retry():
    scheduler = ClusterScheduler(max_retries=1)
    try:
        w1_msgs = []
        w2_msgs = []

        scheduler.register_worker(
            worker_id="w1",
            sender=lambda m: w1_msgs.append(m),
        )
        scheduler.register_worker(
            worker_id="w2",
            sender=lambda m: w2_msgs.append(m),
        )

        # Submit task
        job_id = scheduler.submit_task(
            task_type=TaskType.VIDEO_CREATE,
            project_alias="my_proj",
            params={"prompt": "failover test"},
        )

        # Should be assigned to one of the workers
        first_worker = "w1" if len(w1_msgs) == 1 else "w2"
        other_worker = "w2" if first_worker == "w1" else "w1"

        # Simulate failure on first worker
        scheduler.on_task_failed(job_id=job_id, error="Simulated GPU crash", worker_id=first_worker)

        # Task should be retried and automatically dispatched to other worker!
        other_msgs = w2_msgs if other_worker == "w2" else w1_msgs
        assert len(other_msgs) == 1
        assert other_msgs[0]["action"] == "execute"
        assert other_msgs[0]["payload"]["job_id"] == job_id
        assert other_msgs[0]["payload"]["retry_count"] == 1
    finally:
        scheduler.stop()


def test_scheduler_task_cancellation():
    scheduler = ClusterScheduler()
    try:
        # No workers registered -> task stays in queue
        job_id = scheduler.submit_task(
            task_type=TaskType.VIDEO_CREATE,
            project_alias="test_proj",
            params={"prompt": "cancel me"},
        )
        assert len(scheduler.pending_tasks) == 1

        success = scheduler.cancel_task(job_id)
        assert success is True
        assert len(scheduler.pending_tasks) == 0
        assert scheduler.jobs[job_id]["status"] == "cancelled"
    finally:
        scheduler.stop()
