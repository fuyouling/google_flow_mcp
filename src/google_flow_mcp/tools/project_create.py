from mcp.server.fastmcp import FastMCP
from typing import Annotated
from pydantic import Field
from loguru import logger
from google_flow_mcp.browser.session import get_browser
from google_flow_mcp.pages.flow_home_page import FlowHomePage
import json

def register_project_create_tool(mcp: FastMCP) -> None:
    @mcp.tool()
    def project_create(
        title: Annotated[str, Field(description="新项目的名称，留空则为 'Untitled project'")] = ""
    ) -> str:
        """
        在 Google Flow 中创建一个新项目，并可选择性地重命名。
        返回新项目的 project_id 和 url。
        """
        from google_flow_mcp.models.project_cache import ProjectCache
        
        logger.info(f"Executing project_create with title='{title}'")
        
        try:
            browser = get_browser()
            page = FlowHomePage(browser.latest_tab)
            page.open()
            
            new_id = page.create_project()
            
            # Extract new URL from cache
            proj = ProjectCache.get_project_by_id(new_id)
            url = proj["url"] if proj else f"https://flow.google.com/project/{new_id}"
            
            if title:
                # We are already in the project editor after create_project,
                # but rename_project expects to be on the home page.
                # So we navigate back to home page to rename it via UI
                # (unless there's a way to rename from the editor, but the home page is currently reliable).
                logger.info(f"Navigating back to home to rename new project {new_id} to '{title}'")
                page.open()
                success = page.rename_project(new_id, "Untitled project", title)
                if not success:
                    return json.dumps({
                        "warning": "Project created but rename failed.",
                        "project_id": new_id,
                        "url": url
                    }, ensure_ascii=False)
                    
            return json.dumps({
                "success": True, 
                "project_id": new_id, 
                "name": title or "Untitled project", 
                "url": url
            }, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"project_create failed: {str(e)}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)
