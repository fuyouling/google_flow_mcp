import os
import pytest
from google_flow_mcp.cluster.scheduler import ClusterScheduler
from google_flow_mcp.cluster.models import TaskType, WorkerState
from google_flow_mcp.models.account_cache import AccountCache


from google_flow_mcp.models.db import init_db

@pytest.fixture(autouse=True)
def clean_cache_db(tmp_path, monkeypatch):
    db_path = tmp_path / "flow_cache.db"
    monkeypatch.setenv("FLOW_CACHE_DB", str(db_path))
    monkeypatch.setattr("google_flow_mcp.models.db.DB_FILE", str(db_path))
    init_db()
    yield db_path
    if db_path.exists():
        try:
            db_path.unlink()
        except:
            pass



def test_scheduler_tier1_over_tier2_and_tier3():
    """
    Worker 1: Tier 1 (daily_free=50, balance=100)
    Worker 2: Tier 2 (daily_free=8, balance=500)
    Worker 3: Tier 3 (daily_free=0, balance=1000)
    Task cost: Omni 720p = 12 credits.
    Worker 1 MUST be selected because daily_free (50) >= 12.
    """
    AccountCache.update("user1@example.com", credits=100, worker_id="w1")
    AccountCache.ensure_daily_grant("user1@example.com")

    AccountCache.update("user2@example.com", credits=500, worker_id="w2")
    AccountCache.ensure_daily_grant("user2@example.com")
    AccountCache.deduct_credits("user2@example.com", cost=42)  # 50 - 42 = 8 left

    AccountCache.update("user3@example.com", credits=1000, worker_id="w3")
    AccountCache.ensure_daily_grant("user3@example.com")
    AccountCache.deduct_credits("user3@example.com", cost=50)  # 50 - 50 = 0 left

    scheduler = ClusterScheduler()
    try:
        w1_msgs = []
        w2_msgs = []
        w3_msgs = []

        scheduler.register_worker("w1", account="user1@example.com", sender=lambda m: w1_msgs.append(m))
        scheduler.register_worker("w2", account="user2@example.com", sender=lambda m: w2_msgs.append(m))
        scheduler.register_worker("w3", account="user3@example.com", sender=lambda m: w3_msgs.append(m))

        job_id = scheduler.submit_task(
            task_type=TaskType.VIDEO_CREATE,
            project_alias="test_p",
            params={"model_name": "Omni 1.1 Flash", "resolution": "720p", "quantity": "x1"},
        )

        assert len(w1_msgs) == 1
        assert len(w2_msgs) == 0
        assert len(w3_msgs) == 0
        assert w1_msgs[0]["payload"]["job_id"] == job_id

        # Worker 1 credits should have been deducted 12 daily_free
        acc1 = AccountCache.get("user1@example.com")
        assert acc1["daily_free_credits_remaining"] == 38
        assert acc1["credits"] == 100
    finally:
        scheduler.stop()


def test_scheduler_tier2_over_tier3():
    """
    No Tier 1 workers available for a 12-credit task.
    Worker 2: Tier 2 (daily_free=8, balance=500)
    Worker 3: Tier 3 (daily_free=0, balance=1000)
    Worker 2 MUST be selected for partial combo deduction!
    """
    AccountCache.update("user2@example.com", credits=500, worker_id="w2")
    AccountCache.ensure_daily_grant("user2@example.com")
    AccountCache.deduct_credits("user2@example.com", cost=42)  # 8 left

    AccountCache.update("user3@example.com", credits=1000, worker_id="w3")
    AccountCache.ensure_daily_grant("user3@example.com")
    AccountCache.deduct_credits("user3@example.com", cost=50)  # 0 left

    scheduler = ClusterScheduler()
    try:
        w2_msgs = []
        w3_msgs = []

        scheduler.register_worker("w2", account="user2@example.com", sender=lambda m: w2_msgs.append(m))
        scheduler.register_worker("w3", account="user3@example.com", sender=lambda m: w3_msgs.append(m))

        job_id = scheduler.submit_task(
            task_type=TaskType.VIDEO_CREATE,
            project_alias="test_p",
            params={"model_name": "Omni 1.1 Flash", "resolution": "720p", "quantity": "x1"},
        )

        assert len(w2_msgs) == 1
        assert len(w3_msgs) == 0

        # Worker 2 deducted 8 free + 4 balance
        acc2 = AccountCache.get("user2@example.com")
        assert acc2["daily_free_credits_remaining"] == 0
        assert acc2["credits"] == 496
    finally:
        scheduler.stop()


def test_scheduler_refund_on_failure():
    """
    When worker fails before generating, deducted credits MUST be refunded!
    """
    AccountCache.update("user1@example.com", credits=100, worker_id="w1")
    AccountCache.ensure_daily_grant("user1@example.com")

    scheduler = ClusterScheduler(max_retries=0)
    try:
        w1_msgs = []
        scheduler.register_worker("w1", account="user1@example.com", sender=lambda m: w1_msgs.append(m))

        job_id = scheduler.submit_task(
            task_type=TaskType.VIDEO_CREATE,
            project_alias="test_p",
            params={"model_name": "Omni 1.1 Flash", "resolution": "720p"},
        )
        assert len(w1_msgs) == 1
        acc1 = AccountCache.get("user1@example.com")
        assert acc1["daily_free_credits_remaining"] == 38

        # Simulate failure before generation
        scheduler.on_task_failed(job_id, error="CDP connection failed before launch", worker_id="w1")

        # Credits must be refunded
        acc1_after = AccountCache.get("user1@example.com")
        assert acc1_after["daily_free_credits_remaining"] == 50
        assert acc1_after["credits"] == 100
    finally:
        scheduler.stop()
