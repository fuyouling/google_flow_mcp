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
        
        from google_flow_mcp.config import get_settings
        
        if not force_refresh:
            projects = ProjectCache.get_all_projects()
            worker_projects = [p["name"] for p in projects]
            return json.dumps(worker_projects, ensure_ascii=False, indent=2)
                
        # Force refresh
        from google_flow_mcp.tasks.manager import task_manager
        is_busy, busy_task = task_manager.is_browser_busy()
        if is_busy:
            job_id = busy_task.get("job_id", "unknown") if busy_task else "unknown"
            task_type = busy_task.get("task_type", "生成") if busy_task else "生成"
            error_msg = f"当前有后台{task_type}任务正在执行中 (job_id='{job_id}') 占用浏览器，暂无法强制刷新抓取网页。请等待生成完成，或使用 force_refresh=False 读取本地缓存。"
            logger.warning(f"project_list(force_refresh=True) blocked: browser is busy with job {job_id}")
            projects = ProjectCache.get_all_projects()
            if projects:
                worker_projects = [p["name"] for p in projects]
                return json.dumps({
                    "warning": error_msg,
                    "projects": worker_projects
                }, ensure_ascii=False, indent=2)
            return json.dumps({"error": error_msg, "busy_job_id": job_id}, ensure_ascii=False)

        try:
            browser = get_browser()
            page = FlowHomePage(browser.latest_tab)
            page.open()
            projects = page.get_projects()
            
            # Synchronize to ProjectCache
            for title, data in projects.items():
                ProjectCache.update_project(title, data["url"])
            
            return json.dumps(list(projects.keys()), ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"project_list failed: {str(e)}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)
