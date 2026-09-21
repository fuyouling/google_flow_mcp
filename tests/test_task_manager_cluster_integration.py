import pytest
from google_flow_mcp.tasks.manager import TaskManager
from google_flow_mcp.cluster.scheduler import ClusterScheduler
from google_flow_mcp.cluster.models import TaskType, TaskResult, TaskStatus


@pytest.fixture(autouse=True)
def mock_account_cache(tmp_path, monkeypatch):
    test_file = str(tmp_path / "test_account_cache.json")
    monkeypatch.setattr("google_flow_mcp.models.account_cache.ACCOUNT_CACHE_FILE", test_file)


def test_task_manager_delegation_to_cluster():
    tm = TaskManager()
    scheduler = ClusterScheduler()
    try:
        tm.set_cluster_scheduler(scheduler)

        # Register a mock worker
        dispatched_msgs = []
        scheduler.register_worker(
            worker_id="worker_cluster_1",
            ip="192.168.1.88",
            account="user88@gmail.com",
            sender=lambda msg: dispatched_msgs.append(msg),
        )

        initial_state = {
            "job_id": "job-test-cluster",
            "status": "pending",
            "is_finished": False,
        }

        # Submit task through TaskManager
        res = tm.submit_task(
            task_type="video",
            job_id="job-test-cluster",
            initial_state=initial_state,
            worker_fn=lambda: None,
            project_id="test_project_alias",
            task_name="my_cluster_video",
            params={"prompt": "ocean waves", "model_name": "Omni 1.1 Flash"},
            required_assets=["ocean_keyframe"],
        )

        assert res["success"] is True
        assert res["job_id"] == "job-test-cluster"

        # Verify task was dispatched to worker_cluster_1
        assert len(dispatched_msgs) == 1
        assert dispatched_msgs[0]["action"] == "execute"
        assert dispatched_msgs[0]["payload"]["job_id"] == "job-test-cluster"

        # Check queue summary reflects cluster
        summary = tm.get_queue_summary()
        assert summary.get("cluster_mode") is True
        assert summary["worker_count"] == 1

        # Test cancel via task_manager
        cancel_res = tm.cancel_task("job-test-cluster")
        assert cancel_res["success"] is True
        assert cancel_res["status"] == "cancelled"

    finally:
        tm.stop()
        scheduler.stop()
