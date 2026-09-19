import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from google_flow_mcp.pages.video_edit_page import VideoEditPage
from google_flow_mcp.tools.video_create import _video_jobs, register_video_create_tool, register_video_status_tool
from mcp.server.fastmcp import FastMCP


def test_video_create_download_validation():
    mcp = FastMCP("test_mcp")
    register_video_create_tool(mcp)

    # Find the tool function
    tool_fn = None
    for tool in mcp._tool_manager.list_tools():
        if tool.name == "video_create":
            tool_fn = tool.fn
            break

    assert tool_fn is not None, "video_create tool not registered"

    # Test invalid download resolution
    res_invalid = tool_fn(
        project_id="test_proj",
        prompt="test prompt",
        mode="frame",
        start_frame="frame1",
        end_frame="frame2",
        download="4K",
    )
    data = json.loads(res_invalid)
    assert data["success"] is False
    assert data["error_type"] == "ValidationError"
    assert "不支持的下载清晰度" in data["error"]

    # Test valid download resolution
    res_valid = tool_fn(
        project_id="test_proj",
        prompt="test prompt",
        mode="frame",
        start_frame="frame1",
        end_frame="frame2",
        download="720p",
    )
    data = json.loads(res_valid)
    assert data["success"] is True
    assert data["status"] == "started"
    assert "job_id" in data
    job_id = data["job_id"]
    assert _video_jobs[job_id]["details"]["download"] == "720p"


def test_video_edit_page_download_video_invalid_resolution():
    mock_tab = MagicMock()
    page = VideoEditPage(mock_tab)

    # Unsupported resolution should return None immediately without touching tab
    res = page.download_video(resolution="4K", expected_prefix="test")
    assert res is None
    assert mock_tab.ele.call_count == 0


def test_video_edit_page_download_video_success():
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_settings = MagicMock()
        mock_settings.chrome_download_dir = tmp_dir

        mock_tab = MagicMock()
        mock_download_btn = MagicMock()
        mock_res_btn = MagicMock()

        def ele_side_effect(selector, timeout=0):
            if '下载媒体内容' in selector:
                return mock_download_btn
            if '720p' in selector:
                return mock_res_btn
            return None

        mock_tab.ele.side_effect = ele_side_effect

        page = VideoEditPage(mock_tab)

        with patch("google_flow_mcp.pages.video_edit_page.get_settings", return_value=mock_settings):
            # Create the file after download is triggered
            def click_res():
                target_file = Path(tmp_dir) / "test_video_123.mp4"
                target_file.write_bytes(b"\x00" * 1024)

            mock_res_btn.click.side_effect = click_res

            downloaded_path = page.download_video(
                resolution="720p",
                expected_prefix="test_video",
                timeout=5,
            )

            assert downloaded_path is not None
            assert Path(downloaded_path).name == "test_video_123.mp4"
            assert mock_download_btn.click.called
            assert mock_res_btn.click.called


if __name__ == "__main__":
    test_video_create_download_validation()
    test_video_edit_page_download_video_invalid_resolution()
    test_video_edit_page_download_video_success()
    print("All unit tests passed successfully!")
