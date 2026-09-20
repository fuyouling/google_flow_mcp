import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.pages.flow_image_page import FlowImagePage
from google_flow_mcp.tools.image_create_by_upload import (
    register_image_create_by_upload_tool,
    format_image_name,
)
from google_flow_mcp.tasks.manager import task_manager


@pytest.fixture(autouse=True)
def clean_task_manager():
    """每个测试前后重置 task_manager 队列与任务状态"""
    task_manager.reset()
    yield
    task_manager.reset()


def test_format_image_name():
    assert format_image_name("My Picture") == "My_Picture"
    assert format_image_name("  Cool   Landscape  ") == "Cool_Landscape"
    assert format_image_name("Banner") == "Banner"
    assert format_image_name("Multiple   Spaces   In   Name") == "Multiple_Spaces_In_Name"


def test_image_create_by_upload_tool_schema():
    mcp = FastMCP("test_mcp")
    register_image_create_by_upload_tool(mcp)

    tool = mcp._tool_manager.get_tool("image_create_by_upload")
    assert tool is not None
    props = tool.parameters["properties"]
    assert "project_id" in props
    assert "image_path" in props
    assert "image_name" in props
    assert "project_id" in tool.parameters["required"]
    assert "image_path" in tool.parameters["required"]
    assert "image_name" in tool.parameters["required"]


def test_image_create_by_upload_empty_name():
    mcp = FastMCP("test_mcp")
    register_image_create_by_upload_tool(mcp)

    tool = mcp._tool_manager.get_tool("image_create_by_upload")
    tool_fn = tool.fn

    res_str = tool_fn(
        project_id="proj_1",
        image_name="   ",
        image_path="sample.png"
    )
    res = json.loads(res_str)
    assert res["status"] == "error"
    assert "cannot be empty" in res["error"]


def test_image_create_by_upload_file_not_found():
    mcp = FastMCP("test_mcp")
    register_image_create_by_upload_tool(mcp)

    tool = mcp._tool_manager.get_tool("image_create_by_upload")
    tool_fn = tool.fn

    res_str = tool_fn(
        project_id="proj_1",
        image_name="My Image",
        image_path="non_existent_image_file_12345.png"
    )
    res = json.loads(res_str)
    assert res["status"] == "error"
    assert "not found" in res["error"]


def test_upload_image_on_project_page_success_with_dialog():
    mock_tab = MagicMock()
    mock_tab.url = "https://flow.google.com/project/proj_1"

    mock_add_btn = MagicMock()
    mock_upload_btn = MagicMock()
    mock_agree_btn = MagicMock()
    mock_first_span = MagicMock()
    mock_tile = MagicMock()

    with tempfile.NamedTemporaryFile(suffix="nature_view.jpeg", delete=False) as f:
        tmp_file = f.name
        stem = Path(tmp_file).stem

    mock_first_span.text = f"{stem}.jpeg"

    # Define fake ele queries
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
    page = FlowImagePage(mock_tab)

    try:
        success = page.upload_image_on_project_page("proj_1", tmp_file, timeout=5)
        assert success is True
        mock_tab.set.upload_files.assert_called_once_with(str(Path(tmp_file).resolve()))
        mock_add_btn.click.assert_called_once()
        mock_upload_btn.click.assert_called_once()
        mock_agree_btn.click.assert_called_once()
        mock_tile.click.assert_called_once()
    finally:
        Path(tmp_file).unlink(missing_ok=True)


def test_upload_image_on_project_page_timeout():
    mock_tab = MagicMock()
    mock_tab.url = "https://flow.google.com/project/proj_1"

    mock_add_btn = MagicMock()
    mock_upload_btn = MagicMock()

    with tempfile.NamedTemporaryFile(suffix="nature_view.jpeg", delete=False) as f:
        tmp_file = f.name

    def fake_ele(selector, timeout=0):
        if '添加媒体' in selector:
            return mock_add_btn
        elif 'span[text()="上传"]' in selector:
            return mock_upload_btn
        return None

    mock_tab.ele.side_effect = fake_ele
    page = FlowImagePage(mock_tab)

    try:
        with pytest.raises(TimeoutError):
            page.upload_image_on_project_page("proj_1", tmp_file, timeout=1)
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
    page = FlowImagePage(mock_tab)

    success = page.rename_and_save_in_detail("Renamed_Image_1", timeout=2)
    assert success is True
    mock_input.click.assert_called_once()
    mock_input.input.assert_called_once_with("Renamed_Image_1")
    mock_save.click.assert_called_once()
    assert mock_tab.run_cdp.call_count >= 4


def test_image_create_by_upload_worker_success():
    mcp = FastMCP("test_mcp")
    register_image_create_by_upload_tool(mcp)

    tool = mcp._tool_manager.get_tool("image_create_by_upload")
    tool_fn = tool.fn

    mock_page = MagicMock()
    mock_page.upload_image_on_project_page.return_value = True
    mock_page.rename_and_save_in_detail.return_value = True

    mock_browser = MagicMock()
    mock_browser.latest_tab = MagicMock()

    with tempfile.NamedTemporaryFile(suffix="sample_landscape.jpeg", delete=False) as f:
        img_path = f.name

    try:
        with patch("google_flow_mcp.tools.image_create_by_upload.get_browser", return_value=mock_browser), \
             patch("google_flow_mcp.tools.image_create_by_upload.FlowImagePage", return_value=mock_page):

            res_json = tool_fn(
                project_id="proj_img_upload_1",
                image_path=img_path,
                image_name="Sunset Beach Landscape"
            )
            res = json.loads(res_json)
            assert res["status"] in ("started", "pending", "queued")
            job_id = res["job_id"]

            # Wait for background thread to complete
            for _ in range(30):
                status = task_manager.get_task_status(job_id)
                if status.get("is_finished"):
                    break
                time.sleep(0.1)

            assert status["status"] == "completed"
            assert status["is_finished"] is True
            assert status["image_name"] == "Sunset_Beach_Landscape"
            assert status["image_path"] == str(Path(img_path).resolve())

            # Verify steps executed
            mock_page.upload_image_on_project_page.assert_called_once_with("proj_img_upload_1", img_path)
            mock_page.rename_and_save_in_detail.assert_called_once_with("Sunset_Beach_Landscape")

    finally:
        Path(img_path).unlink(missing_ok=True)
