import json
import uuid
from pathlib import Path
from typing import Annotated
from pydantic import Field
from loguru import logger
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.browser.session import get_browser
from google_flow_mcp.pages.flow_character_page import FlowCharacterPage
from google_flow_mcp.tasks.manager import task_manager


import re


def format_character_name(name: str) -> str:
    """
    Format character name by stripping whitespace and replacing spaces with underscores.
    e.g. 'Test Hero' -> 'Test_Hero'
    """
    clean_name = re.sub(r'\s+', '_', name.strip())
    return clean_name


def register_character_create_by_upload_tool(mcp: FastMCP) -> None:
    @mcp.tool()
    def character_create_by_upload(
        character_name: Annotated[str, Field(description="要创建的虚拟角色名称（必填项）。如果名称中包含空格，系统会自动将空格统一转换为下划线 '_' 进行保存（例如 'Test Hero' 将转为 'Test_Hero'）")],
        portrait_image_path: Annotated[str, Field(description="头像图片的本地绝对路径")],
        fullbody_image_path: Annotated[str, Field(description="全身像图片的本地绝对路径（可选），若提供则上传全身像")] = "",
        voice_name: Annotated[str, Field(description="角色的声音名称，例如 'Journey' 等，留空则不设置")] = "",
        voice_style: Annotated[str, Field(description="角色的声音风格，留空则不设置")] = "",
        project_name: Annotated[str, Field(description="Google Flow 项目的名称，留空则自动选用最近访问的项目")] = "",
    ) -> str:
        """
        通过上传本地已有图片在 Google Flow 中创建一个新的虚拟角色（头像必传，全身像选传）。
        
        特性与流程说明：
        1. 角色名称规范：角色名称为必填项。传入的角色名称中所有的空格均会自动统一转换为下划线 '_' 进行命名与保存（例如 'Test Hero' 将自动转为 'Test_Hero'）。
        2. 原生弹窗自动处理：底层采用 CDP 拦截技术直接注入文件路径，无需操作系统级文件选择弹窗交互。
        3. 自动协议同意：若上传过程中出现「此视频的使用权」协议弹窗，自动点击「我同意，不再显示」。
        4. 异步排队机制：任务接入后台任务队列统一串行调度，立即返回 job_id，请使用 `character_status` 工具轮询执行结果。
        """
        formatted_name = format_character_name(character_name)
        if not formatted_name:
            return json.dumps({
                "status": "error",
                "error": "Character name cannot be empty.",
                "message": "角色名称不能为空。"
            }, ensure_ascii=False)
        character_name = formatted_name

        # Validate local files exist before queuing
        p_path = Path(portrait_image_path)
        if not p_path.is_file():
            return json.dumps({
                "status": "error",
                "error": f"Portrait image file not found: {portrait_image_path}",
                "message": f"头像图片文件不存在: {portrait_image_path}"
            }, ensure_ascii=False)

        p_fullbody = Path(fullbody_image_path)
        if fullbody_image_path and not p_fullbody.is_file():
            return json.dumps({
                "status": "error",
                "error": f"Fullbody image file not found: {fullbody_image_path}",
                "message": f"待上传全身像图片文件不存在: {fullbody_image_path}"
            }, ensure_ascii=False)

        # 0. Resolve project_name
        from google_flow_mcp.models.project_cache import ProjectCache
        cache = ProjectCache.load()
        projects = cache.get("projects", {})
        
        if not project_name or not project_name.strip():
            if projects:
                project_name = max(
                    projects.keys(),
                    key=lambda k: projects[k].get("last_accessed", "")
                )
                logger.info(f"character_create_by_upload: project_name not provided, defaulting to latest project: {project_name}")
            else:
                project_name = "default"

        job_id = str(uuid.uuid4())
        initial_state = {
            "job_id": job_id,
            "status": "pending",
            "is_finished": False,
            "character_name": character_name,
            "message": "Character upload creation started in the background."
        }

        logger.info(
            f"Submitting character_create_by_upload task {job_id}: "
            f"project={project_name}, name={character_name}, "
            f"portrait={portrait_image_path}, fullbody={fullbody_image_path}"
        )

        def task_worker():
            try:
                browser = get_browser()
                page = FlowCharacterPage(browser.latest_tab)

                # Step 1 & 2: Navigate to characters page
                from google_flow_mcp.utils.project_utils import ensure_project_exists
                project_url = ensure_project_exists(project_name, browser)
                page.navigate_to_characters(project_url)

                # Step 3: Click 'New Character'
                if not page.click_new_character():
                    task_manager.jobs[job_id] = {
                        "job_id": job_id,
                        "status": "error",
                        "is_finished": True,
                        "error": "Failed to open character editor.",
                        "message": "打开角色编辑器失败。"
                    }
                    return

                # Step 4: Upload Portrait
                page.upload_portrait(portrait_image_path)

                # Step 5 & 6: Upload Fullbody if provided
                if fullbody_image_path:
                    page.upload_fullbody(fullbody_image_path)

                # Step 7: Configure Voice if provided
                if voice_name:
                    page.configure_voice(voice_name, voice_style)

                # Step 8: Rename character
                page.rename_character(character_name)

                # Step 9: Save Character
                page.save_character()

                msg = f"虚拟角色 {character_name} 上传创建成功。"
                task_manager.jobs[job_id] = {
                    "job_id": job_id,
                    "status": "completed",
                    "is_finished": True,
                    "character_name": character_name,
                    "portrait_image_path": str(Path(portrait_image_path).resolve()),
                    "fullbody_image_path": str(Path(fullbody_image_path).resolve()) if fullbody_image_path else "",
                    "message": msg
                }
                logger.info(f"Background character upload job {job_id} completed successfully for {character_name}")

            except Exception as e:
                logger.error(f"Background character upload job {job_id} failed: {str(e)}")
                task_manager.jobs[job_id] = {
                    "job_id": job_id,
                    "status": "error",
                    "is_finished": True,
                    "error": str(e),
                    "message": f"虚拟角色上传创建失败: {str(e)}"
                }

        task_params = {
            "project_name": project_name,
            "character_name": formatted_name,
            "portrait_image_path": portrait_image_path,
            "fullbody_image_path": fullbody_image_path,
            "voice_name": voice_name,
            "voice_style": voice_style,
        }
        submit_result = task_manager.submit_task(
            task_type="character_upload",
            job_id=job_id,
            initial_state=initial_state,
            worker_fn=task_worker,
            project_id=project_name,
            task_name=f"upload_{formatted_name}",
            params=task_params,
        )
        return json.dumps(submit_result, ensure_ascii=False)
