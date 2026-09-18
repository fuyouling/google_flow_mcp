import atexit
from loguru import logger
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.browser.session import close_browser
from google_flow_mcp.tools.website_open import register_website_open_tool
from google_flow_mcp.tools.project_list import register_project_list_tool
from google_flow_mcp.tools.project_open import register_project_open_tool
from google_flow_mcp.tools.project_rename import register_project_rename_tool
from google_flow_mcp.tools.project_create import register_project_create_tool
from google_flow_mcp.tools.character_create import (
    register_character_create_tool,
    register_character_status_tool,
)
from google_flow_mcp.tools.image_create import (
    register_image_create_tool,
    register_image_status_tool,
)
from google_flow_mcp.tools.video_create import (
    register_video_create_tool,
    register_video_status_tool,
)

mcp = FastMCP(
    name="google-flow-mcp",
    dependencies=["DrissionPage"],
    instructions="Google Agentspace Flow 网页端操作工具集",
)

# Register all MCP tools
register_website_open_tool(mcp)
register_project_list_tool(mcp)
register_project_open_tool(mcp)
register_project_rename_tool(mcp)
register_project_create_tool(mcp)
register_character_create_tool(mcp)
register_character_status_tool(mcp)
register_image_create_tool(mcp)
register_image_status_tool(mcp)
register_video_create_tool(mcp)
register_video_status_tool(mcp)


# Ensure browser is safely closed on process exit
atexit.register(close_browser)


def main() -> None:
    """Run the MCP server in stdio transport mode."""
    logger.info("Starting google-flow-mcp server (stdio mode)...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
