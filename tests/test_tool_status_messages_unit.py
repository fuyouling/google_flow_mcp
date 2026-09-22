import json
import pytest
from mcp.server.fastmcp import FastMCP
from google_flow_mcp.tools.image_create import _jobs, register_image_create_tool, register_image_status_tool
from google_flow_mcp.tools.video_create import _video_jobs, register_video_create_tool, register_video_status_tool


from google_flow_mcp.tasks.manager import task_manager


from unittest.mock import patch


@pytest.fixture
def mcp_server():
    task_manager.reset()
    server = FastMCP("test_status_server")
    register_image_create_tool(server)
    register_image_status_tool(server)
    register_video_create_tool(server)
    register_video_status_tool(server)
    
    orig_submit = task_manager.submit_task

    def dummy_submit(task_type, job_id, initial_state, worker_fn, **kwargs):
        return orig_submit(
            task_type=task_type,
            job_id=job_id,
            initial_state=initial_state,
            worker_fn=lambda: None,
            **kwargs
        )

    with patch.object(task_manager, "submit_task", side_effect=dummy_submit):
        yield server

    task_manager.reset()


def get_tool(server: FastMCP, tool_name: str):
    for tool in server._tool_manager.list_tools():
        if tool.name == tool_name:
            return tool.fn
    raise ValueError(f"Tool {tool_name} not registered")


def test_image_create_invalid_download(mcp_server):
    image_create_fn = get_tool(mcp_server, "image_create")
    res_raw = image_create_fn(
        project_name="proj_1",
        prompt="A cute cat",
        download="4K"
    )
    res = json.loads(res_raw)
    assert res["success"] is False
    assert res["status"] == "error"
    assert res["is_finished"] is True
    assert "不支持的下载分辨率" in res["message"]
    assert "next_action" in res


def test_image_create_and_status_lifecycle(mcp_server):
    image_create_fn = get_tool(mcp_server, "image_create")
    image_status_fn = get_tool(mcp_server, "image_status")

    # 1. Start job
    res_raw = image_create_fn(
        project_name="proj_1",
        prompt="A beautiful sunrise",
        download="1K"
    )
    res = json.loads(res_raw)
    assert res["success"] is True
    assert res["status"] == "started"
    assert res["is_finished"] is False
    assert "job_id" in res
    job_id = res["job_id"]
    assert "image_status" in res["message"]
    assert "next_action" in res

    # 2. Check pending state via image_status
    status_raw = image_status_fn(job_id=job_id)
    status_data = json.loads(status_raw)
    assert status_data["job_id"] == job_id
    assert status_data["status"] == "pending"
    assert status_data["is_finished"] is False
    assert status_data["progress_percent"] == 0
    assert "next_action" in status_data

    # 3. Simulate generating state
    _jobs[job_id].update({
        "status": "generating",
        "is_finished": False,
        "progress": 45,
        "progress_percent": 45,
        "progress_text": "45%",
        "elapsed_seconds": 12.5,
        "message": "图片生成中：45%（已用时 13s）",
        "next_action": f"任务正在生成中（45%），尚未完成。请等待 5 秒后继续调用 image_status(job_id='{job_id}') 检查进度。"
    })
    status_raw2 = image_status_fn(job_id=job_id)
    status_data2 = json.loads(status_raw2)
    assert status_data2["status"] == "generating"
    assert status_data2["is_finished"] is False
    assert status_data2["progress_percent"] == 45
    assert "45%" in status_data2["message"]

    # 4. Simulate completed state
    _jobs[job_id] = {
        "job_id": job_id,
        "status": "completed",
        "is_finished": True,
        "progress": 100,
        "progress_percent": 100,
        "progress_text": "100%",
        "elapsed_seconds": 25.0,
        "message": "图片生成成功，已重命名为 test_img，1K 图片已下载至 /tmp/test.png",
        "next_action": "任务已顺利完成，智能体请停止轮询，可直接向用户展示图片结果及相关信息。",
        "image_name": "test_img",
        "image_url": "https://example.com/test.png",
        "image_local_path": "/tmp/test.png",
        "rename_success": True
    }
    status_raw3 = image_status_fn(job_id=job_id)
    status_data3 = json.loads(status_raw3)
    assert status_data3["status"] == "completed"
    assert status_data3["is_finished"] is True
    assert status_data3["progress_percent"] == 100
    assert "停止轮询" in status_data3["next_action"]

    # 5. Verify repeated calls still return completed state (not deleted)
    status_raw4 = image_status_fn(job_id=job_id)
    status_data4 = json.loads(status_raw4)
    assert status_data4["status"] == "completed"
    assert status_data4["is_finished"] is True


def test_image_status_not_found(mcp_server):
    image_status_fn = get_tool(mcp_server, "image_status")
    res_raw = image_status_fn(job_id="non_existent_id")
    res = json.loads(res_raw)
    assert res["status"] == "error"
    assert res["is_finished"] is True
    assert "未找到任务 ID" in res["error"]
    assert "停止轮询" in res["next_action"]


def test_video_create_validation_and_lifecycle(mcp_server):
    video_create_fn = get_tool(mcp_server, "video_create")
    video_status_fn = get_tool(mcp_server, "video_status")

    # 1. Validation error: missing start_frame in frame mode
    res_raw = video_create_fn(
        project_name="proj_1",
        prompt="A dog running",
        mode="frame",
        start_frame="",
        end_frame="frame2"
    )
    res = json.loads(res_raw)
    assert res["success"] is False
    assert res["status"] == "error"
    assert res["is_finished"] is True
    assert "首帧图片" in res["message"]
    assert "next_action" in res

    # 2. Validation error: invalid download resolution
    res_raw = video_create_fn(
        project_name="proj_1",
        prompt="A dog running",
        mode="frame",
        start_frame="f1",
        end_frame="f2",
        download="4K"
    )
    res = json.loads(res_raw)
    assert res["success"] is False
    assert res["status"] == "error"
    assert res["is_finished"] is True
    assert "不支持的下载清晰度" in res["message"]

    # 3. Valid job start
    res_raw = video_create_fn(
        project_name="proj_1",
        prompt="A cinematic drone shot",
        mode="frame",
        start_frame="f1",
        end_frame="f2",
        download="720p"
    )
    res = json.loads(res_raw)
    assert res["success"] is True
    assert res["status"] == "started"
    assert res["is_finished"] is False
    assert "job_id" in res
    job_id = res["job_id"]
    assert "video_status" in res["message"]
    assert "next_action" in res

    # 4. Check pending state via video_status
    status_raw = video_status_fn(job_id=job_id)
    status_data = json.loads(status_raw)
    assert status_data["job_id"] == job_id
    assert status_data["status"] == "pending"
    assert status_data["is_finished"] is False
    assert "next_action" in status_data

    # 5. Simulate generating state
    _video_jobs[job_id].update({
        "status": "generating",
        "is_finished": False,
        "progress": 60,
        "progress_percent": 60,
        "progress_text": "60%",
        "elapsed_seconds": 35.0,
        "message": "视频生成中：60%（已用时 35s）",
        "next_action": f"视频正在生成中（进度 60%），尚未完成。请等待 5-10 秒后继续调用 video_status(job_id='{job_id}') 检查进度。"
    })
    status_raw2 = video_status_fn(job_id=job_id)
    status_data2 = json.loads(status_raw2)
    assert status_data2["status"] == "generating"
    assert status_data2["is_finished"] is False
    assert status_data2["progress_percent"] == 60
    assert "60%" in status_data2["message"]

    # 6. Simulate completed state
    _video_jobs[job_id] = {
        "job_id": job_id,
        "status": "completed",
        "is_finished": True,
        "progress": 100,
        "progress_percent": 100,
        "progress_text": "100%",
        "message": "视频生成成功，已重命名为 test_vid，720p 视频已下载至 /tmp/vid.mp4",
        "next_action": "任务已顺利完成，智能体请停止轮询，可直接向用户汇报视频链接及本地文件。",
        "video_name": "test_vid",
        "video_url": "https://example.com/vid.mp4",
        "video_local_path": "/tmp/vid.mp4",
        "rename_success": True,
        "elapsed_seconds": 55.0
    }
    status_raw3 = video_status_fn(job_id=job_id)
    status_data3 = json.loads(status_raw3)
    assert status_data3["status"] == "completed"
    assert status_data3["is_finished"] is True
    assert status_data3["progress_percent"] == 100
    assert "停止轮询" in status_data3["next_action"]

    # 7. Repeated call
    status_raw4 = video_status_fn(job_id=job_id)
    status_data4 = json.loads(status_raw4)
    assert status_data4["status"] == "completed"
    assert status_data4["is_finished"] is True


def test_video_status_not_found(mcp_server):
    video_status_fn = get_tool(mcp_server, "video_status")
    res_raw = video_status_fn(job_id="non_existent_id")
    res = json.loads(res_raw)
    assert res["status"] == "error"
    assert res["is_finished"] is True
    assert "未找到任务 ID" in res["error"]
    assert "停止轮询" in res["next_action"]


def test_video_create_veo_asset_warning(mcp_server):
    video_create_fn = get_tool(mcp_server, "video_create")
    res_raw = video_create_fn(
        project_name="proj_1",
        prompt="A dog playing in the garden",
        model_name="Veo 3.1 - Quality",
        mode="asset",
        assets="dog_character",
    )
    res = json.loads(res_raw)
    assert res["success"] is True
    assert res["status"] == "started"
    assert "warning" in res
    assert "不会引用参考素材" in res["warning"]
    assert "Veo 模型在素材模式下不会引用参考素材" in res["message"]

