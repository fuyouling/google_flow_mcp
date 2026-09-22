import json
import re
import time
import uuid
from pathlib import Path
from typing import Annotated
from pydantic import Field
from loguru import logger
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.browser.session import get_browser
from google_flow_mcp.pages.flow_video_page import FlowVideoPage
from google_flow_mcp.tasks.manager import task_manager


def format_video_name(name: str) -> str:
    """
    Format video name by stripping whitespace and replacing spaces with underscores.
    e.g. 'My Video' -> 'My_Video'
    """
    clean_name = re.sub(r'\s+', '_', name.strip())
    return clean_name


def register_video_create_by_upload_tool(mcp: FastMCP) -> None:
    @mcp.tool()
    def video_create_by_upload(
        project_name: Annotated[str, Field(description="Google Flow 项目的名称，留空则自动选用最近访问的项目")],
        video_path: Annotated[str, Field(description="待上传视频的本地绝对路径")],
        video_name: Annotated[str, Field(description="上传后的视频重命名名称（必填项）。名称中的所有空格将被自动统一替换为下划线 '_' 进行保存（例如 'My Video' 将转为 'My_Video'）")],
    ) -> str:
        """
        通过在项目主页上传本地已有视频文件创建视频媒体资产并重命名保存。
        
        特性与流程说明：
        1. 流程步骤：进入项目首页 -> 点击「添加媒体」-> 自动注入视频文件触发上传 -> 检测网格卡片上传完成 -> 点击进入详情界面 -> 重命名为规范名称并回车自动保存。
        2. 命名规范：视频名称为必填项。传入的 video_name 中所有空格均会自动统一转换为下划线 '_' 进行保存（例如 'My Video' 将转为 'My_Video'）。
        3. 原生弹窗自动处理：底层采用 CDP 拦截技术直接注入文件路径，无需操作系统级文件选择弹窗交互。
        4. 自动协议同意：若上传过程中出现「此视频的使用权」协议弹窗，自动点击「我同意，不再显示」。
        5. 异步排队机制：任务接入后台任务队列统一串行调度，立即返回 job_id，请使用 `video_status` 工具轮询执行结果。
        """
        formatted_name = format_video_name(video_name)
        if not formatted_name:
            return json.dumps({
                "status": "error",
                "error": "Video name cannot be empty.",
                "message": "视频名称不能为空。"
            }, ensure_ascii=False)
        video_name = formatted_name

        p_path = Path(video_path)
        if not p_path.is_file():
            return json.dumps({
                "status": "error",
                "error": f"Video file not found: {video_path}",
                "message": f"待上传视频文件不存在: {video_path}"
            }, ensure_ascii=False)

        # 0. Resolve project_name to project_url
        from google_flow_mcp.models.project_cache import ProjectCache
        if not project_name or not project_name.strip():
            projects = ProjectCache.get_all_projects()
            if projects:
                default_proj = max(projects, key=lambda p: p.get("last_accessed", ""))
                project_name = default_proj["name"]
                logger.info(f"video_create_by_upload: project_name not provided, defaulting to latest project: {project_name}")
            else:
                return json.dumps({
                    "success": False,
                    "status": "error",
                    "is_finished": True,
                    "error_type": "ValidationError",
                    "error": "未提供 project_name，且本地缓存中没有最近访问的项目，无法创建视频。",
                    "message": "未提供 project_name，且本地缓存中没有最近访问的项目，无法创建视频。",
                    "next_action": "参数缺失，任务未启动，智能体请要求用户提供有效的项目名称后重试。"
                }, ensure_ascii=False)

        job_id = str(uuid.uuid4())
        initial_state = {
            "job_id": job_id,
            "status": "pending",
            "is_finished": False,
            "video_name": video_name,
            "message": "Video upload started in the background."
        }

        logger.info(
            f"Submitting video_create_by_upload task {job_id}: "
            f"project={project_name}, name={video_name}, path={video_path}"
        )

        def task_worker():
            try:
                browser = get_browser()
                
                from google_flow_mcp.utils.project_utils import ensure_project_exists
                project_url = ensure_project_exists(project_name, browser)
                
                page = FlowVideoPage(browser.latest_tab)
                if page.url != project_url:
                    page.get(project_url)
                    time.sleep(4)
                
                # If cached URL is invalid, we might be redirected away from the project page
                if "/project/" not in page.url:
                    logger.warning(f"Cached URL {project_url} seems invalid. Forcing sync...")
                    project_url = ensure_project_exists(project_name, browser, force_sync=True)
                    if page.url != project_url:
                        page.get(project_url)
                        time.sleep(4)

                # Step 1 ~ 3: Upload video from project home page and navigate to details
                page.upload_video_on_project_page(project_url, video_path)

                # Step 4 & 5: Rename in details view and auto-save via Enter
                page.rename_and_save_in_detail(video_name)

                msg = f"视频 {video_name} 上传创建并保存成功。"
                task_manager.jobs[job_id].update({
                    "job_id": job_id,
                    "status": "completed",
                    "is_finished": True,
                    "video_name": video_name,
                    "video_path": str(p_path.resolve()),
                    "message": msg
                })
                logger.info(f"Background video upload job {job_id} completed successfully for {video_name}")

            except Exception as e:
                logger.error(f"Background video upload job {job_id} failed: {str(e)}")
                task_manager.jobs[job_id].update({
                    "job_id": job_id,
                    "status": "error",
                    "is_finished": True,
                    "error": str(e),
                    "message": f"视频上传创建失败: {str(e)}"
                })

        task_params = {
            "project_name": project_name,
            "video_path": video_path,
            "video_name": formatted_name,
        }
        submit_result = task_manager.submit_task(
            task_type="video_upload",
            job_id=job_id,
            initial_state=initial_state,
            worker_fn=task_worker,
            project_name=project_name,
            task_name=f"upload_{formatted_name}",
            params=task_params,
        )
        return json.dumps(submit_result, ensure_ascii=False)
