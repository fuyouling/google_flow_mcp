from mcp.server.fastmcp import FastMCP
from typing import Annotated
from pydantic import Field
from loguru import logger
from google_flow_mcp.browser.session import get_browser

def register_project_open_tool(mcp: FastMCP) -> None:
    @mcp.tool()
    def project_open(
        project_id: Annotated[str, Field(description="要打开的 Google Flow 项目的唯一 ID (UUID)")]
    ) -> str:
        """
        直接根据项目 ID 在浏览器中打开对应的 Google Flow 项目。
        它会利用本地缓存快速定位并加载页面。如果提示找不到，请先执行 `project_list` 刷新缓存。
        """
        from google_flow_mcp.models.project_cache import ProjectCache
        import json
        
        logger.info(f"Executing project_open for UUID: {project_id}")
        
        proj = ProjectCache.get_project_by_id(project_id)
        if not proj:
            return json.dumps({"error": f"Project {project_id} not found in cache. Run project_list with force_refresh=True first."}, ensure_ascii=False)
            
        url = proj.get("url")
        if not url:
            url = f"https://flow.google.com/project/{project_id}"
            
        try:
            browser = get_browser()
            browser.latest_tab.get(url)
            # Wait for some common project element
            browser.latest_tab.ele('css:flow-project-header', timeout=15)
            
            # Update last accessed in cache
            ProjectCache.update_project(project_id, proj.get("name", "Unknown"), url)
            return json.dumps({"success": True, "url": url}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"project_open failed: {str(e)}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)
