import json
import re
from typing import Annotated
from pydantic import Field
from loguru import logger
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.browser.session import get_browser
from google_flow_mcp.pages.flow_character_page import FlowCharacterPage
from google_flow_mcp.models.project_cache import ProjectCache
from google_flow_mcp.tasks.manager import task_manager


def register_character_list_tool(mcp: FastMCP) -> None:
    @mcp.tool()
    def character_list(
        project_id: Annotated[
            str,
            Field(description="Google Flow 项目的唯一 ID (UUID)。留空则自动从浏览器当前所在的项目页面中提取角色列表。")
        ] = ""
    ) -> str:
        """
        查看并列出 Google Flow 项目中的所有虚拟角色（包括角色总数、角色名称与头像缩略图）。
        
        特性：
        1. 若传入 project_id，则自动定位/跳转至该项目角色管理页；若留空，则直接查看当前正在浏览器中打开的项目。
        2. 自动进行并发冲突保护：若当前后台有生成任务正在占用浏览器，工具会避免打断当前任务，并降级尝试返回此前本地缓存的角色数据。
        3. 每次成功抓取角色后，会自动同步更新本地缓存 projects_cache.json。
        """
        logger.info(f"Executing character_list (project_id='{project_id}')")

        # 1. 检查浏览器是否被后台生成任务占用
        is_busy, busy_task = task_manager.is_browser_busy()
        if is_busy:
            job_id = busy_task.get("job_id", "unknown") if busy_task else "unknown"
            task_type = busy_task.get("task_type", "生成") if busy_task else "生成"
            busy_msg = f"当前有后台{task_type}任务正在执行中 (job_id='{job_id}') 占用浏览器，暂无法操作浏览器刷新角色。"
            logger.warning(f"character_list blocked: browser is busy with job {job_id}")
            
            # 尝试降级读取本地缓存
            cached_chars = None
            if project_id:
                cached_chars = ProjectCache.get_project_characters(project_id)
            else:
                # 尝试从缓存中最近访问的项目提取
                cache_data = ProjectCache.load()
                for pid, pdata in cache_data.get("projects", {}).items():
                    if pdata.get("characters"):
                        cached_chars = pdata.get("characters")
                        project_id = pid
                        break
                        
            if cached_chars is not None:
                return json.dumps({
                    "success": True,
                    "warning": busy_msg + " 已降级返回本地历史缓存数据。",
                    "is_cached": True,
                    "project_id": project_id,
                    "total": len(cached_chars),
                    "characters": cached_chars
                }, ensure_ascii=False, indent=2)

            return json.dumps({
                "success": False,
                "error": busy_msg + " 且未找到本地缓存的角色数据。请等待生成任务完成后再试。",
                "busy_job_id": job_id
            }, ensure_ascii=False)

        # 2. 获取浏览器并执行角色提取
        try:
            browser = get_browser()
            tab = browser.latest_tab

            # 若未提供 project_id，尝试从当前 tab.url 自动推断
            effective_project_id = project_id.strip()
            if not effective_project_id:
                current_url = tab.url or ""
                match = re.search(r'/project/([a-zA-Z0-9\-]+)', current_url)
                if match:
                    effective_project_id = match.group(1)
                    logger.info(f"Inferred project_id from current tab URL: {effective_project_id}")

            page = FlowCharacterPage(tab)
            characters = page.list_characters(project_id=effective_project_id)

            # 3. 同步至本地缓存
            if effective_project_id:
                ProjectCache.update_project_characters(effective_project_id, characters)

            return json.dumps({
                "success": True,
                "project_id": effective_project_id,
                "total": len(characters),
                "characters": characters
            }, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"character_list failed: {str(e)}")
            return json.dumps({
                "success": False,
                "error": f"获取角色列表失败: {str(e)}"
            }, ensure_ascii=False)
