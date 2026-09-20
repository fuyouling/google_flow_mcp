import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.pages.flow_video_page import FlowVideoPage
from google_flow_mcp.tools.video_create_by_upload import (
    register_video_create_by_upload_tool,
    format_video_name,
)
from google_flow_mcp.tasks.manager import task_manager


@pytest.fixture(autouse=True)
def clean_task_manager():
    """每个测试前后重置 task_manager 队列与任务状态"""
    task_manager.reset()
    yield
    task_manager.reset()


def test_format_video_name():
    assert format_video_name("My Video") == "My_Video"
    assert format_video_name("  Epic   Trailer  ") == "Epic_Trailer"
    assert format_video_name("Intro") == "Intro"
    assert format_video_name("Multiple   Spaces   In   Video   Name") == "Multiple_Spaces_In_Video_Name"


def test_video_create_by_upload_tool_schema():
    mcp = FastMCP("test_mcp")
    register_video_create_by_upload_tool(mcp)

    tool = mcp._tool_manager.get_tool("video_create_by_upload")
    assert tool is not None
    props = tool.parameters["properties"]
    assert "project_id" in props
    assert "video_path" in props
    assert "video_name" in props
    assert "project_id" in tool.parameters["required"]
    assert "video_path" in tool.parameters["required"]
    assert "video_name" in tool.parameters["required"]


def test_video_create_by_upload_empty_name():
    mcp = FastMCP("test_mcp")
    register_video_create_by_upload_tool(mcp)

    tool = mcp._tool_manager.get_tool("video_create_by_upload")
    tool_fn = tool.fn

    res_str = tool_fn(
        project_id="proj_1",
        video_name="   ",
        video_path="sample.mp4"
    )
    res = json.loads(res_str)
    assert res["status"] == "error"
    assert "cannot be empty" in res["error"]


def test_video_create_by_upload_file_not_found():
    mcp = FastMCP("test_mcp")
    register_video_create_by_upload_tool(mcp)

    tool = mcp._tool_manager.get_tool("video_create_by_upload")
    tool_fn = tool.fn

    res_str = tool_fn(
        project_id="proj_1",
        video_name="My Video",
        video_path="non_existent_video_file_12345.mp4"
    )
    res = json.loads(res_str)
    assert res["status"] == "error"
    assert "not found" in res["error"]


def test_upload_video_on_project_page_success_with_dialog():
    mock_tab = MagicMock()
    mock_tab.url = "https://flow.google.com/project/proj_1"

    mock_add_btn = MagicMock()
    mock_upload_btn = MagicMock()
    mock_agree_btn = MagicMock()
    mock_first_span = MagicMock()
    mock_tile = MagicMock()

    with tempfile.NamedTemporaryFile(suffix="epic_clip.mp4", delete=False) as f:
        tmp_file = f.name
        stem = Path(tmp_file).stem

    mock_first_span.text = f"{stem}.mp4"

    def fake_ele(selector, timeout=0):
        if '添加媒体' in selector:
            return mock_add_btn
        elif 'span[text()="上传"]' in selector:
            return mock_upload_btn
        elif '我同意' in selector:
            return mock_agree_btn
        elif '(//flow-grid-tile-container)[1]//span' in selector:
            return mock_first_span
        elif '(//flow-grid-tile-container)[1]' in selector:
            return mock_tile
        return None

    mock_tab.ele.side_effect = fake_ele
    page = FlowVideoPage(mock_tab)

    try:
        success = page.upload_video_on_project_page("proj_1", tmp_file, timeout=5)
        assert success is True
        mock_tab.set.upload_files.assert_called_once_with(str(Path(tmp_file).resolve()))
        mock_add_btn.click.assert_called_once()
        mock_upload_btn.click.assert_called_once()
        mock_agree_btn.click.assert_called_once()
        mock_tile.click.assert_called_once()
    finally:
        Path(tmp_file).unlink(missing_ok=True)


def test_upload_video_on_project_page_timeout():
    mock_tab = MagicMock()
    mock_tab.url = "https://flow.google.com/project/proj_1"

    mock_add_btn = MagicMock()
    mock_upload_btn = MagicMock()

    with tempfile.NamedTemporaryFile(suffix="epic_clip.mp4", delete=False) as f:
        tmp_file = f.name

    def fake_ele(selector, timeout=0):
        if '添加媒体' in selector:
            return mock_add_btn
        elif 'span[text()="上传"]' in selector:
            return mock_upload_btn
        return None

    mock_tab.ele.side_effect = fake_ele
    page = FlowVideoPage(mock_tab)

    try:
        with pytest.raises(TimeoutError):
            page.upload_video_on_project_page("proj_1", tmp_file, timeout=1)
    finally:
        Path(tmp_file).unlink(missing_ok=True)


def test_rename_and_save_in_detail_success():
    mock_tab = MagicMock()
    mock_input = MagicMock()
    mock_save = MagicMock()

    def fake_ele(selector, timeout=0):
        if 'editable-text-input' in selector or 'input' in selector:
            return mock_input
        elif '保存' in selector:
            return mock_save
        return None

    mock_tab.ele.side_effect = fake_ele
    page = FlowVideoPage(mock_tab)

    success = page.rename_and_save_in_detail("Renamed_Video_1", timeout=2)
    assert success is True
    mock_input.click.assert_called_once()
    mock_input.input.assert_called_once_with("Renamed_Video_1")
    mock_save.click.assert_called_once()
    assert mock_tab.run_cdp.call_count >= 4


def test_video_create_by_upload_worker_success():
    mcp = FastMCP("test_mcp")
    register_video_create_by_upload_tool(mcp)

    tool = mcp._tool_manager.get_tool("video_create_by_upload")
    tool_fn = tool.fn

    mock_page = MagicMock()
    mock_page.upload_video_on_project_page.return_value = True
    mock_page.rename_and_save_in_detail.return_value = True

    mock_browser = MagicMock()
    mock_browser.latest_tab = MagicMock()

    with tempfile.NamedTemporaryFile(suffix="sample_clip.mp4", delete=False) as f:
        vid_path = f.name

    try:
        with patch("google_flow_mcp.tools.video_create_by_upload.get_browser", return_value=mock_browser), \
             patch("google_flow_mcp.tools.video_create_by_upload.FlowVideoPage", return_value=mock_page):

            res_json = tool_fn(
                project_id="proj_vid_upload_1",
                video_path=vid_path,
                video_name="Epic Trailer Video"
            )
            res = json.loads(res_json)
            assert res["status"] in ("started", "pending", "queued")
            job_id = res["job_id"]

            # Wait for background thread to complete
            for _ in range(60):
                status = task_manager.get_task_status(job_id)
                if status.get("is_finished"):
                    break
                time.sleep(0.1)

            assert status["status"] == "completed"
            assert status["is_finished"] is True
            assert status["video_name"] == "Epic_Trailer_Video"
            assert status["video_path"] == str(Path(vid_path).resolve())

            # Verify steps executed
            mock_page.upload_video_on_project_page.assert_called_once_with("proj_vid_upload_1", vid_path)
            mock_page.rename_and_save_in_detail.assert_called_once_with("Epic_Trailer_Video")

    finally:
        Path(vid_path).unlink(missing_ok=True)
