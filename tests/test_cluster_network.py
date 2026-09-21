import asyncio
import io
import json
import tempfile
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from google_flow_mcp.cluster.asset_hub import AssetHub
from google_flow_mcp.cluster.master_server import MasterServer
from google_flow_mcp.cluster.models import AssetType, TaskType, TaskPayload
from google_flow_mcp.cluster.scheduler import ClusterScheduler
from google_flow_mcp.cluster.proto import cluster_pb2


@pytest.fixture
def cluster_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        hub = AssetHub(base_dir=Path(tmp_dir))
        scheduler = ClusterScheduler()
        # Fast startup using port 0 for random free port allocation
        server = MasterServer(
            scheduler=scheduler,
            asset_hub=hub,
            host="127.0.0.1",
            grpc_port=0,
            http_port=0,
        )
        # Note: We must use a real server start to get the actual ports allocated
        server.start()
        time.sleep(0.5)

        client = TestClient(server._fastapi_app)
        yield {
            "hub": hub,
            "scheduler": scheduler,
            "server": server,
            "client": client,
        }
        
        server.stop()
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

