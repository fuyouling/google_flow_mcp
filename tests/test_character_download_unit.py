import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.pages.flow_character_page import FlowCharacterPage
from google_flow_mcp.tools.character_create import register_character_create_tool, register_character_status_tool
from google_flow_mcp.tasks.manager import task_manager


def test_character_create_tool_schema():
    mcp = FastMCP("test_mcp")
    register_character_create_tool(mcp)

    tool = mcp._tool_manager.get_tool("character_create")
    assert tool is not None
    props = tool.parameters["properties"]
    assert "download" in props
    assert props["download"]["type"] == "boolean"
    assert props["download"]["default"] is False
    assert "image_base64" in props
    assert props["image_base64"]["type"] == "boolean"
    assert props["image_base64"]["default"] is False


def test_download_character_image_button_not_found():
    mock_tab = MagicMock()
    mock_tab.ele.return_value = None
    page = FlowCharacterPage(mock_tab)

    res = page.download_character_image("Test_Portrait")
    assert res is None
    mock_tab.ele.assert_called_once_with('xpath://button[@aria-label="下载图片"]', timeout=5)


def test_download_character_image_success_and_overwrite():
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_settings = MagicMock()
        mock_settings.chrome_download_dir = tmp_dir

        mock_tab = MagicMock()
        mock_btn = MagicMock()
        mock_tab.ele.return_value = mock_btn

        page = FlowCharacterPage(mock_tab)

        with patch("google_flow_mcp.pages.flow_character_page.get_settings", return_value=mock_settings):
            # Create an existing file that should be overwritten
            existing_target = Path(tmp_dir) / "Hero_Portrait.png"
            existing_target.write_text("old content")

            # Simulate download trigger creating a file named '图片_20260321.png'
            def fake_click():
                dl_file = Path(tmp_dir) / "图片_20260321.png"
                dl_file.write_text("new image content")

            mock_btn.click.side_effect = fake_click

            result_path = page.download_character_image("Hero_Portrait", timeout=5)

            assert result_path is not None
            assert Path(result_path).name == "Hero_Portrait.png"
            assert Path(result_path).read_text() == "new image content"
            assert not (Path(tmp_dir) / "图片_20260321.png").exists()


def test_download_character_image_ignores_crdownload():
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_settings = MagicMock()
        mock_settings.chrome_download_dir = tmp_dir

        mock_tab = MagicMock()
        mock_btn = MagicMock()
        mock_tab.ele.return_value = mock_btn

        page = FlowCharacterPage(mock_tab)

        with patch("google_flow_mcp.pages.flow_character_page.get_settings", return_value=mock_settings):
            # Create a .crdownload file, should not be treated as finished
            cr_file = Path(tmp_dir) / "图片_12345.crdownload"
            cr_file.write_text("incomplete")

            result_path = page.download_character_image("Hero_Portrait", timeout=2)
            assert result_path is None


def test_character_create_worker_with_download():
    mcp = FastMCP("test_mcp")
    register_character_create_tool(mcp)

    tool = mcp._tool_manager.get_tool("character_create")
    tool_fn = tool.fn

    mock_page = MagicMock()
    mock_page.click_new_character.return_value = True
    mock_page.generate_portrait.return_value = "portrait_b64"
    mock_page.generate_fullbody.return_value = "fullbody_b64"

    # Simulate download paths
    def fake_download(stem, timeout=60):
        return f"/downloads/{stem}.png"

    mock_page.download_character_image.side_effect = fake_download

    mock_browser = MagicMock()
    mock_browser.latest_tab = MagicMock()

    with patch("google_flow_mcp.tools.character_create.get_browser", return_value=mock_browser), \
         patch("google_flow_mcp.utils.project_utils.ensure_project_exists", return_value="TestProject"), \
         patch("google_flow_mcp.tools.character_create.FlowCharacterPage", return_value=mock_page):

        # Call with download=True and fullbody_prompt provided
        res_json = tool_fn(
            project_name="proj_1",
            character_name="Arthur",
            portrait_prompt="portrait prompt",
            fullbody_prompt="fullbody prompt",
            download=True,
            image_base64=False
        )
        res = json.loads(res_json)
        job_id = res["job_id"]

        # Wait briefly for worker thread to complete
        for _ in range(100):
            status = task_manager.get_task_status(job_id)
            if status.get("is_finished"):
                break
            time.sleep(0.1)

        assert status["status"] == "completed"
        assert status["is_finished"] is True
        assert status["portrait_local_path"] == "/downloads/Arthur_Portrait.png"
        assert status["fullbody_local_path"] == "/downloads/Arthur_Fullbody.png"
        assert "/downloads/Arthur_Portrait.png" in status["message"]
        assert "/downloads/Arthur_Fullbody.png" in status["message"]

        # Verify calls to download_character_image
        calls = [c[0][0] for c in mock_page.download_character_image.call_args_list]
        assert calls == ["Arthur_Portrait", "Arthur_Fullbody"]
