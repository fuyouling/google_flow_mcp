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
        
        from google_flow_mcp.tasks.manager import task_manager
        
        logger.info(f"Executing project_open for UUID: {project_id}")

        is_busy, busy_task = task_manager.is_browser_busy()
        if is_busy:
            job_id = busy_task.get("job_id", "unknown") if busy_task else "unknown"
            task_type = busy_task.get("task_type", "生成") if busy_task else "生成"
            error_msg = f"当前有后台{task_type}任务正在执行中 (job_id='{job_id}') 占用浏览器，暂无法跳转项目。请等待生成完成或使用 task_cancel(job_id='{job_id}') 取消后再操作。"
            logger.warning(f"project_open blocked: browser is busy with job {job_id}")
            return json.dumps({
                "success": False,
                "error": error_msg,
                "busy_job_id": job_id,
                "message": error_msg
            }, ensure_ascii=False)
        
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
