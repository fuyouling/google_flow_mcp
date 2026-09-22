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
from google_flow_mcp.pages.flow_image_page import FlowImagePage
from google_flow_mcp.tasks.manager import task_manager


def format_image_name(name: str) -> str:
    """
    Format image name by stripping whitespace and replacing spaces with underscores.
    e.g. 'My Picture' -> 'My_Picture'
    """
    clean_name = re.sub(r'\s+', '_', name.strip())
    return clean_name


def register_image_create_by_upload_tool(mcp: FastMCP) -> None:
    @mcp.tool()
    def image_create_by_upload(
        project_name: Annotated[str, Field(description="Google Flow 项目的名称，留空则自动选用最近访问的项目")],
        image_path: Annotated[str, Field(description="待上传图片的本地绝对路径")],
        image_name: Annotated[str, Field(description="上传后的图片重命名名称（必填项）。名称中的所有空格将被自动统一替换为下划线 '_' 进行保存（例如 'My Picture' 将转为 'My_Picture'）")],
    ) -> str:
        """
        通过在项目主页上传本地已有图片创建图片媒体资产并重命名保存。
        
        特性与流程说明：
        1. 流程步骤：进入项目首页 -> 点击「添加媒体」-> 自动注入文件触发上传 -> 检测网格卡片上传完成 -> 点击进入详情界面 -> 重命名为规范名称并回车自动保存。
        2. 命名规范：图片名称为必填项。传入的 image_name 中所有空格均会自动统一转换为下划线 '_' 进行保存（例如 'My Picture' 将转为 'My_Picture'）。
        3. 原生弹窗自动处理：底层采用 CDP 拦截技术直接注入文件路径，无需操作系统级文件选择弹窗交互。
        4. 自动协议同意：若上传过程中出现「此视频的使用权」协议弹窗，自动点击「我同意，不再显示」。
        5. 异步排队机制：任务接入后台任务队列统一串行调度，立即返回 job_id，请使用 `image_status` 工具轮询执行结果。
        """
        formatted_name = format_image_name(image_name)
        if not formatted_name:
            return json.dumps({
                "status": "error",
                "error": "Image name cannot be empty.",
                "message": "图片名称不能为空。"
            }, ensure_ascii=False)
        image_name = formatted_name

        p_path = Path(image_path)
        if not p_path.is_file():
            return json.dumps({
                "status": "error",
                "error": f"Image file not found: {image_path}",
                "message": f"待上传图片文件不存在: {image_path}"
            }, ensure_ascii=False)

        # 0. Resolve project_name to project_url
        from google_flow_mcp.models.project_cache import ProjectCache
        if not project_name or not project_name.strip():
            projects = ProjectCache.get_all_projects()
            if projects:
                default_proj = max(projects, key=lambda p: p.get("last_accessed", ""))
                project_name = default_proj["name"]
                logger.info(f"image_create_by_upload: project_name not provided, defaulting to latest project: {project_name}")
            else:
                project_name = "default"

        job_id = str(uuid.uuid4())
        initial_state = {
            "job_id": job_id,
            "status": "pending",
            "is_finished": False,
            "image_name": image_name,
            "message": "Image upload started in the background."
        }

        logger.info(
            f"Submitting image_create_by_upload task {job_id}: "
            f"project={project_name}, name={image_name}, path={image_path}"
        )

        def task_worker():
            try:
                browser = get_browser()
                page = FlowImagePage(browser.latest_tab)

                from google_flow_mcp.utils.project_utils import ensure_project_exists
                project_url = ensure_project_exists(project_name, browser)
                if page.url != project_url:
                    page.get(project_url)
                    time.sleep(4)
                
                # If cached URL is invalid, we might be redirected away from the project page
                if "/project/" not in page.url:
                    logger.warning(f"Cached URL {project_url} seems invalid. Forcing sync...")
                    project_url = ensure_project_exists(project_name, browser, force_sync=True)

                # Step 1 ~ 3: Upload image from project home page and navigate to details
                page.upload_image_on_project_page(project_url, image_path)

                # Step 4 & 5: Rename in details view and auto-save via Enter
                page.rename_and_save_in_detail(image_name)

                msg = f"图片 {image_name} 上传创建并保存成功。"
                task_manager.jobs[job_id].update({
                    "job_id": job_id,
                    "status": "completed",
                    "is_finished": True,
                    "image_name": image_name,
                    "image_path": str(p_path.resolve()),
                    "message": msg
                })
                logger.info(f"Background image upload job {job_id} completed successfully for {image_name}")

            except Exception as e:
                logger.error(f"Background image upload job {job_id} failed: {str(e)}")
                task_manager.jobs[job_id].update({
                    "job_id": job_id,
                    "status": "error",
                    "is_finished": True,
                    "error": str(e),
                    "message": f"图片上传创建失败: {str(e)}"
                })

        task_params = {
            "project_name": project_name,
            "image_path": image_path,
            "image_name": formatted_name,
        }
        submit_result = task_manager.submit_task(
            task_type="image_upload",
            job_id=job_id,
            initial_state=initial_state,
            worker_fn=task_worker,
            project_name=project_name,
            task_name=f"upload_{formatted_name}",
            params=task_params,
        )
        return json.dumps(submit_result, ensure_ascii=False)
