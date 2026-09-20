import json
import time
from unittest.mock import MagicMock, patch
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.tools.character_create import register_character_create_tool
from google_flow_mcp.tasks.manager import task_manager


def test_character_create_image_base64_false():
    mcp = FastMCP("test_mcp")
    register_character_create_tool(mcp)

    tool = mcp._tool_manager.get_tool("character_create")
    tool_fn = tool.fn

    mock_page = MagicMock()
    mock_page.click_new_character.return_value = True
    mock_page.generate_portrait.return_value = "raw_portrait_base64_data"
    mock_page.generate_fullbody.return_value = "raw_fullbody_base64_data"

    mock_browser = MagicMock()
    mock_browser.latest_tab = MagicMock()

    with patch("google_flow_mcp.tools.character_create.get_browser", return_value=mock_browser), \
         patch("google_flow_mcp.tools.character_create.FlowCharacterPage", return_value=mock_page):

        # Call with default image_base64=False
        res_json = tool_fn(
            project_id="proj_1",
            character_name="Arthur",
            portrait_prompt="portrait prompt",
            fullbody_prompt="fullbody prompt",
            image_base64=False
        )
        res = json.loads(res_json)
        job_id = res["job_id"]

        for _ in range(20):
            status = task_manager.get_task_status(job_id)
            if status.get("is_finished"):
                break
            time.sleep(0.1)

        assert status["status"] == "completed"
        assert status["is_finished"] is True
        # base64 should NOT be returned
        assert status["portrait_image_base64"] == ""
        assert status["fullbody_image_base64"] == ""


def test_character_create_image_base64_true():
    mcp = FastMCP("test_mcp")
    register_character_create_tool(mcp)

    tool = mcp._tool_manager.get_tool("character_create")
    tool_fn = tool.fn

    mock_page = MagicMock()
    mock_page.click_new_character.return_value = True
    mock_page.generate_portrait.return_value = "raw_portrait_base64_data"
    mock_page.generate_fullbody.return_value = "raw_fullbody_base64_data"

    mock_browser = MagicMock()
    mock_browser.latest_tab = MagicMock()

    with patch("google_flow_mcp.tools.character_create.get_browser", return_value=mock_browser), \
         patch("google_flow_mcp.tools.character_create.FlowCharacterPage", return_value=mock_page):

        # Call with image_base64=True
        res_json = tool_fn(
            project_id="proj_1",
            character_name="Arthur",
            portrait_prompt="portrait prompt",
            fullbody_prompt="fullbody prompt",
            image_base64=True
        )
        res = json.loads(res_json)
        job_id = res["job_id"]

        for _ in range(20):
            status = task_manager.get_task_status(job_id)
            if status.get("is_finished"):
                break
            time.sleep(0.1)

        assert status["status"] == "completed"
        assert status["is_finished"] is True
        # base64 SHOULD be returned
        assert status["portrait_image_base64"] == "raw_portrait_base64_data"
        assert status["fullbody_image_base64"] == "raw_fullbody_base64_data"
