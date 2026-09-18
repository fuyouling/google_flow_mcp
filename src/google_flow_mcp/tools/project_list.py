from mcp.server.fastmcp import FastMCP
from typing import Annotated
from pydantic import Field
from loguru import logger
from google_flow_mcp.browser.session import get_browser
from google_flow_mcp.pages.flow_home_page import FlowHomePage

def register_project_list_tool(mcp: FastMCP) -> None:
    @mcp.tool()
    def project_list(
        force_refresh: Annotated[bool, Field(description="是否强制刷新。True: 抓取网页最新数据; False: 使用本地缓存(速度快)")] = False
    ) -> str:
        """
        列出当前账户下所有的 Google Flow 项目。
        默认从本地缓存读取以保证速度。如果刚创建/重命名了项目，可以传入 force_refresh=True 强制更新。
        """
        from google_flow_mcp.models.project_cache import ProjectCache
        import json
        
        logger.info(f"Executing project_list (force_refresh={force_refresh})")
        
        if not force_refresh:
            cache_data = ProjectCache.load()
            if cache_data and cache_data.get("projects"):
                return json.dumps(cache_data["projects"], ensure_ascii=False, indent=2)
                
        # Force refresh
        try:
            browser = get_browser()
            page = FlowHomePage(browser.latest_tab)
            page.open()
            projects = page.get_projects()
            return json.dumps(projects, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"project_list failed: {str(e)}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)
