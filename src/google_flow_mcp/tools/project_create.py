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
        返回新项目的 project_name 和 url。
        """
        from google_flow_mcp.models.project_cache import ProjectCache
        from google_flow_mcp.config import get_settings
        from google_flow_mcp.tasks.manager import task_manager
        
        logger.info(f"Executing project_create with title='{title}'")

        is_busy, busy_task = task_manager.is_browser_busy()
        if is_busy:
            job_id = busy_task.get("job_id", "unknown") if busy_task else "unknown"
            task_type = busy_task.get("task_type", "生成") if busy_task else "生成"
            error_msg = f"当前有后台{task_type}任务正在执行中 (job_id='{job_id}') 占用浏览器，暂无法创建新项目。请等待生成完成或使用 task_cancel(job_id='{job_id}') 取消后再操作。"
            logger.warning(f"project_create blocked: browser is busy with job {job_id}")
            return json.dumps({
                "success": False,
                "error": error_msg,
                "busy_job_id": job_id,
                "message": error_msg
            }, ensure_ascii=False)
        
        try:
            browser = get_browser()
            page = FlowHomePage(browser.latest_tab)
            page.open()
            
            new_id = page.create_project()
            url = f"https://flow.google.com/project/{new_id}"
            final_title = "Untitled project"
            
            if title:
                logger.info(f"Navigating back to home to rename new project to '{title}'")
                page.open()
                success = page.rename_project(new_title=title, old_title="Untitled project")
                if not success:
                    return json.dumps({
                        "warning": "Project created but rename failed.",
                        "project_name": final_title,
                        "url": url
                    }, ensure_ascii=False)
                final_title = title
            
            ProjectCache.update_project(final_title, url)
                    
            return json.dumps({
                "success": True, 
                "project_name": final_title, 
                "url": url
            }, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"project_create failed: {str(e)}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)
