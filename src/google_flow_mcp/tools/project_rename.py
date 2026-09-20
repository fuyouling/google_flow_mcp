from mcp.server.fastmcp import FastMCP
from typing import Annotated
from pydantic import Field
from loguru import logger
from google_flow_mcp.browser.session import get_browser
from google_flow_mcp.pages.flow_home_page import FlowHomePage
import json

def register_project_rename_tool(mcp: FastMCP) -> None:
    @mcp.tool()
    def project_rename(
        project_id: Annotated[str, Field(description="需要重命名的 Google Flow 项目的 ID")],
        new_name: Annotated[str, Field(description="项目的新名称")]
    ) -> str:
        """
        在 Google Flow 首页将指定的项目重命名。
        注意：这需要在 UI 层面操作，请确保项目 ID 存在。
        """
        from google_flow_mcp.models.project_cache import ProjectCache
        
        from google_flow_mcp.tasks.manager import task_manager
        
        logger.info(f"Executing project_rename for {project_id} -> {new_name}")

        is_busy, busy_task = task_manager.is_browser_busy()
        if is_busy:
            job_id = busy_task.get("job_id", "unknown") if busy_task else "unknown"
            task_type = busy_task.get("task_type", "生成") if busy_task else "生成"
            error_msg = f"当前有后台{task_type}任务正在执行中 (job_id='{job_id}') 占用浏览器，暂无法重命名项目。请等待生成完成或使用 task_cancel(job_id='{job_id}') 取消后再操作。"
            logger.warning(f"project_rename blocked: browser is busy with job {job_id}")
            return json.dumps({
                "success": False,
                "error": error_msg,
                "busy_job_id": job_id,
                "message": error_msg
            }, ensure_ascii=False)
        
        proj = ProjectCache.get_project_by_id(project_id)
        if not proj:
            return json.dumps({"error": f"Project {project_id} not found in cache. Run project_list first."}, ensure_ascii=False)
            
        old_name = proj.get("name")
        
        try:
            browser = get_browser()
            page = FlowHomePage(browser.latest_tab)
            page.open()
            
            success = page.rename_project(project_id, old_name, new_name)
            if success:
                return json.dumps({"success": True, "project_id": project_id, "new_name": new_name}, ensure_ascii=False)
            else:
                return json.dumps({"error": "Failed to rename project via UI."}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"project_rename failed: {str(e)}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)
