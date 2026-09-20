import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.pages.flow_character_page import FlowCharacterPage
from google_flow_mcp.tools.character_create_by_upload import (
    register_character_create_by_upload_tool,
    format_character_name,
)
from google_flow_mcp.tasks.manager import task_manager


@pytest.fixture(autouse=True)
def clean_task_manager():
    """每个测试前后重置 task_manager 队列与任务状态"""
    task_manager.reset()
    yield
    task_manager.reset()


def test_format_character_name():
    assert format_character_name("Test Hero") == "Test_Hero"
    assert format_character_name("  Cyber   Warrior  ") == "Cyber_Warrior"
    assert format_character_name("Alice") == "Alice"
    assert format_character_name("Multiple   Spaces   In   Name") == "Multiple_Spaces_In_Name"


def test_character_create_by_upload_tool_schema():
    mcp = FastMCP("test_mcp")
    register_character_create_by_upload_tool(mcp)

    tool = mcp._tool_manager.get_tool("character_create_by_upload")
    assert tool is not None
    props = tool.parameters["properties"]
    assert "project_id" in props
    assert "character_name" in props
    assert "portrait_image_path" in props
    assert "fullbody_image_path" in props
    assert props["fullbody_image_path"]["default"] == ""
    assert "voice_name" in props
    assert props["voice_name"]["default"] == ""
    assert "voice_style" in props
    assert props["voice_style"]["default"] == ""
    assert "character_name" in tool.parameters["required"]


def test_character_create_by_upload_empty_name():
    mcp = FastMCP("test_mcp")
    register_character_create_by_upload_tool(mcp)

    tool = mcp._tool_manager.get_tool("character_create_by_upload")
    tool_fn = tool.fn

    res_str = tool_fn(
        project_id="proj_1",
        character_name="   ",
        portrait_image_path="some_path.png"
    )
    res = json.loads(res_str)
    assert res["status"] == "error"
    assert "cannot be empty" in res["error"]


def test_character_create_by_upload_file_not_found():
    mcp = FastMCP("test_mcp")
    register_character_create_by_upload_tool(mcp)

    tool = mcp._tool_manager.get_tool("character_create_by_upload")
    tool_fn = tool.fn

    # 1. Non-existent portrait file
    res_str = tool_fn(
        project_id="proj_1",
        character_name="Hero Name",
        portrait_image_path="non_existent_portrait_file_12345.png"
    )
    res = json.loads(res_str)
    assert res["status"] == "error"
    assert "not found" in res["error"]

    # 2. Existing portrait, non-existent fullbody file
    with tempfile.NamedTemporaryFile(suffix="_Portrait.jpeg", delete=False) as f:
        tmp_portrait = f.name

    try:
        res_str2 = tool_fn(
            project_id="proj_1",
            character_name="Hero Name",
            portrait_image_path=tmp_portrait,
            fullbody_image_path="non_existent_fullbody_file_99999.png"
        )
        res2 = json.loads(res_str2)
        assert res2["status"] == "error"
        assert "not found" in res2["error"]
    finally:
        Path(tmp_portrait).unlink(missing_ok=True)


def test_upload_portrait_page_method_success_with_dialog():
    mock_tab = MagicMock()
    mock_upload_btn = MagicMock()
    mock_agree_btn = MagicMock()
    mock_dl_btn = MagicMock()

    # Track how ele is queried:
    # 1. Look for upload button: //span[text()="上传"]
    # 2. Look for agreement popup: //span[text()="我同意，不再显示"]
    # 3. Look for download button: //button[@aria-label="下载图片"]
    def fake_ele(selector, timeout=0):
        if 'span[text()="上传"]' in selector:
            return mock_upload_btn
        elif '我同意' in selector:
            return mock_agree_btn
        elif '下载图片' in selector:
            return mock_dl_btn
        return None

    mock_tab.ele.side_effect = fake_ele
    page = FlowCharacterPage(mock_tab)

    with tempfile.NamedTemporaryFile(suffix="_Portrait.jpeg", delete=False) as f:
        tmp_file = f.name

    try:
        success = page.upload_portrait(tmp_file, timeout=5)
        assert success is True
        mock_tab.set.upload_files.assert_called_once_with(str(Path(tmp_file).resolve()))
        mock_upload_btn.click.assert_called_once()
        mock_agree_btn.click.assert_called_once()
    finally:
        Path(tmp_file).unlink(missing_ok=True)


def test_upload_portrait_page_method_timeout():
    mock_tab = MagicMock()
    mock_upload_btn = MagicMock()

    def fake_ele(selector, timeout=0):
        if 'span[text()="上传"]' in selector:
            return mock_upload_btn
        return None

    mock_tab.ele.side_effect = fake_ele
    page = FlowCharacterPage(mock_tab)

    with tempfile.NamedTemporaryFile(suffix="_Portrait.jpeg", delete=False) as f:
        tmp_file = f.name

    try:
        with pytest.raises(TimeoutError):
            page.upload_portrait(tmp_file, timeout=1)
    finally:
        Path(tmp_file).unlink(missing_ok=True)


def test_upload_fullbody_page_method_success():
    mock_tab = MagicMock()
    mock_fullbody_btn = MagicMock()
    mock_upload_btn = MagicMock()
    mock_dl_btn = MagicMock()

    def fake_ele(selector, timeout=0):
        if '全身像' in selector:
            return mock_fullbody_btn
        elif '上传' in selector:
            return mock_upload_btn
        return None

    # eles: initially 1 download button, then 2 download buttons
    call_count = {"dl": 0}
    def fake_eles(selector, timeout=0):
        if '下载图片' in selector:
            call_count["dl"] += 1
            if call_count["dl"] == 1:
                return [mock_dl_btn]
            return [mock_dl_btn, MagicMock()]
        return []

    mock_tab.ele.side_effect = fake_ele
    mock_tab.eles.side_effect = fake_eles
    page = FlowCharacterPage(mock_tab)

    with tempfile.NamedTemporaryFile(suffix="_Fullbody.jpeg", delete=False) as f:
        tmp_file = f.name

    try:
        success = page.upload_fullbody(tmp_file, timeout=5)
        assert success is True
        mock_tab.set.upload_files.assert_called_once_with(str(Path(tmp_file).resolve()))
        mock_fullbody_btn.click.assert_called_once()
        mock_upload_btn.click.assert_called_once()
    finally:
        Path(tmp_file).unlink(missing_ok=True)


def test_character_create_by_upload_worker_success():
    mcp = FastMCP("test_mcp")
    register_character_create_by_upload_tool(mcp)

    tool = mcp._tool_manager.get_tool("character_create_by_upload")
    tool_fn = tool.fn

    mock_page = MagicMock()
    mock_page.click_new_character.return_value = True

    mock_browser = MagicMock()
    mock_browser.latest_tab = MagicMock()

    with tempfile.NamedTemporaryFile(suffix="Test_Knight_Portrait.jpeg", delete=False) as f_p, \
         tempfile.NamedTemporaryFile(suffix="Test_Knight_Fullbody.jpeg", delete=False) as f_fb:
        p_path = f_p.name
        fb_path = f_fb.name

    try:
        with patch("google_flow_mcp.tools.character_create_by_upload.get_browser", return_value=mock_browser), \
             patch("google_flow_mcp.tools.character_create_by_upload.FlowCharacterPage", return_value=mock_page):

            res_json = tool_fn(
                project_id="proj_upload_1",
                character_name="Test Knight Hero",
                portrait_image_path=p_path,
                fullbody_image_path=fb_path,
                voice_name="Journey",
                voice_style="Cheerful"
            )
            res = json.loads(res_json)
            assert res["status"] in ("started", "pending", "queued")
            job_id = res["job_id"]

            # Wait for background thread to finish
            for _ in range(60):
                status = task_manager.get_task_status(job_id)
                if status.get("is_finished"):
                    break
                time.sleep(0.1)

            assert status["status"] == "completed"
            assert status["is_finished"] is True
            assert status["character_name"] == "Test_Knight_Hero"
            assert status["portrait_image_path"] == str(Path(p_path).resolve())
            assert status["fullbody_image_path"] == str(Path(fb_path).resolve())

            # Verify steps executed in order
            mock_page.navigate_to_characters.assert_called_once_with("proj_upload_1")
            mock_page.click_new_character.assert_called_once()
            mock_page.upload_portrait.assert_called_once_with(p_path)
            mock_page.upload_fullbody.assert_called_once_with(fb_path)
            mock_page.configure_voice.assert_called_once_with("Journey", "Cheerful")
            mock_page.rename_character.assert_called_once_with(status["character_name"])
            mock_page.save_character.assert_called_once()

    finally:
        Path(p_path).unlink(missing_ok=True)
        Path(fb_path).unlink(missing_ok=True)
