import json
from typing import Annotated
from pydantic import Field
from loguru import logger
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.browser.session import get_browser
from google_flow_mcp.pages.flow_video_page import FlowVideoPage
from google_flow_mcp.models.project_cache import ProjectCache
from google_flow_mcp.tasks.manager import task_manager


def register_video_list_tool(mcp: FastMCP) -> None:
    @mcp.tool()
    def video_list(
        project_name: Annotated[
            str,
            Field(description="Google Flow 项目的名称。留空则自动从浏览器当前所在的项目页面中提取视频列表。")
        ] = ""
    ) -> str:
        """
        查看并列出 Google Flow 项目中的所有视频（包括视频总数、视频名称与预览图）。
        
        特性：
        1. 若传入 project_name，则自动定位/跳转至该项目页面；若留空，则直接查看当前正在浏览器中打开的项目。
        2. 导航栏检查：通过 //mat-list-item//span[text()="视频"] 判断，若该按钮不存在则说明项目中没有视频，直接返回空列表。
        3. 自动进行并发冲突保护：若当前后台有生成任务正在占用浏览器，工具会避免打断当前任务，并降级尝试返回此前本地缓存的视频数据。
        4. 每次成功抓取后，会自动同步更新本地缓存 projects_cache.json。
        """
        logger.info(f"Executing video_list (project_name='{project_name}')")

        # 1. 检查浏览器是否被后台生成任务占用
        is_busy, busy_task = task_manager.is_browser_busy()
        if is_busy:
            job_id = busy_task.get("job_id", "unknown") if busy_task else "unknown"
            task_type = busy_task.get("task_type", "生成") if busy_task else "生成"
            busy_msg = f"当前有后台{task_type}任务正在执行中 (job_id='{job_id}') 占用浏览器，暂无法操作浏览器刷新视频。"
            logger.warning(f"video_list blocked: browser is busy with job {job_id}")

            # 尝试降级读取本地缓存
            cached_videos = None
            if project_name:
                cached_videos = ProjectCache.get_project_videos(project_name)
            else:
                cache_data = ProjectCache.load()
                # If no project_name provided, grab the first one that has videos
                for pname, pdata in cache_data.get("projects", {}).items():
                    if pdata.get("videos") is not None:
                        cached_videos = pdata.get("videos")
                        project_name = pname
                        break

            if cached_videos is not None:
                return json.dumps({
                    "success": True,
                    "warning": busy_msg + " 已降级返回本地历史缓存数据。",
                    "is_cached": True,
                    "project_name": project_name,
                    "total": len(cached_videos),
                    "videos": cached_videos
                }, ensure_ascii=False, indent=2)

            return json.dumps({
                "success": False,
                "error": busy_msg + " 且未找到本地缓存的视频数据。请等待生成任务完成后再试。",
                "busy_job_id": job_id
            }, ensure_ascii=False)

        # 2. 获取浏览器并执行视频提取
        try:
            browser = get_browser()
            tab = browser.latest_tab
            
            project_url = ""
            effective_project_name = project_name.strip()
            
            if effective_project_name:
                proj = ProjectCache.get_project_by_name(effective_project_name)
                if proj and "url" in proj:
                    project_url = proj["url"]
                else:
                    logger.warning(f"Project '{effective_project_name}' not found in cache or missing URL.")
            else:
                # If not provided, we just use the current tab without navigating,
                # but we can try to figure out which project this is from the URL
                # However, our cache maps names to URLs. We can reverse lookup the name by URL.
                current_url = tab.url or ""
                cache_data = ProjectCache.load()
                for pname, pdata in cache_data.get("projects", {}).items():
                    if pdata.get("url") and pdata["url"] in current_url:
                        effective_project_name = pname
                        break

            page = FlowVideoPage(tab)
            videos = page.list_videos(project_url=project_url)

            # 3. 同步至本地缓存
            if effective_project_name:
                ProjectCache.update_project_videos(effective_project_name, videos)

            return json.dumps({
                "success": True,
                "project_name": effective_project_name,
                "total": len(videos),
                "videos": videos
            }, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"video_list failed: {str(e)}")
            return json.dumps({
                "success": False,
                "error": f"获取视频列表失败: {str(e)}"
            }, ensure_ascii=False)
