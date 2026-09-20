import io
import tempfile
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from google_flow_mcp.cluster.asset_hub import AssetHub
from google_flow_mcp.cluster.master_server import MasterServer
from google_flow_mcp.cluster.models import AssetType, TaskType
from google_flow_mcp.cluster.scheduler import ClusterScheduler


@pytest.fixture
def cluster_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        hub = AssetHub(base_dir=Path(tmp_dir))
        scheduler = ClusterScheduler()
        server = MasterServer(scheduler=scheduler, asset_hub=hub)
        client = TestClient(server.app)
        yield {
            "hub": hub,
            "scheduler": scheduler,
            "server": server,
            "client": client,
        }
        scheduler.stop()


def test_asset_upload_and_download_http(cluster_env):
    client = cluster_env["client"]
    hub = cluster_env["hub"]

    # 1. Upload asset via HTTP POST
    file_content = b"fake-png-data-for-cluster-test"
    response = client.post(
        "/api/assets/upload",
        data={"name": "test_asset_01", "asset_type": "image", "worker_id": "worker_lan_1"},
        files={"file": ("test_asset_01.png", io.BytesIO(file_content), "image/png")},
    )
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["success"] is True
    assert res_data["asset"]["name"] == "test_asset_01"

    # 2. Check asset info
    info_resp = client.get("/api/assets/info/test_asset_01")
    assert info_resp.status_code == 200
    assert info_resp.json()["exists"] is True

    # 3. Download asset via HTTP GET
    dl_resp = client.get("/api/assets/download/test_asset_01")
    assert dl_resp.status_code == 200
    assert dl_resp.content == file_content


def test_cluster_status_endpoint(cluster_env):
    client = cluster_env["client"]
    scheduler = cluster_env["scheduler"]

    scheduler.register_worker("worker_alpha", ip="192.168.1.101")

    resp = client.get("/api/cluster/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["worker_count"] == 1
    assert data["workers"][0]["worker_id"] == "worker_alpha"


def test_worker_websocket_lifecycle(cluster_env):
    client = cluster_env["client"]
    scheduler = cluster_env["scheduler"]

    with client.websocket_connect("/ws/worker") as ws:
        # 1. Registration handshake
        ws.send_json({
            "action": "register",
            "worker_id": "ws_worker_test",
            "account": "test@gmail.com",
            "cached_assets": ["cached_1"],
        })
        ack = ws.receive_json()
        assert ack["action"] == "registered"
        assert ack["worker_id"] == "ws_worker_test"

        # Check worker in scheduler
        workers = scheduler.get_workers()
        assert any(w.worker_id == "ws_worker_test" for w in workers)

        # 2. Submit task from Master and receive over WS
        job_id = scheduler.submit_task(
            task_type=TaskType.VIDEO_CREATE,
            project_alias="test_proj",
            params={"prompt": "generate flowers"},
        )

        task_msg = ws.receive_json()
        assert task_msg["action"] == "execute"
        assert task_msg["payload"]["job_id"] == job_id

        # 3. Report completion over WS
        ws.send_json({
            "action": "completed",
            "result": {
                "job_id": job_id,
                "worker_id": "ws_worker_test",
                "status": "completed",
                "result_data": {"video_url": "https://flow.google.com/vid/123"},
                "produced_assets": [],
            },
        })

        # Wait briefly for scheduler to process
        import time
        time.sleep(0.1)
        assert scheduler.jobs[job_id]["status"] == "completed"
