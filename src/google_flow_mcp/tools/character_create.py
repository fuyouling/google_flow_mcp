import json
import uuid
from typing import Annotated
from pydantic import Field
from loguru import logger
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.browser.session import get_browser
from google_flow_mcp.pages.flow_character_page import FlowCharacterPage
from google_flow_mcp.models.project_cache import ProjectCache

from google_flow_mcp.tasks.manager import task_manager

# Reference to global jobs dictionary for backward compatibility
_jobs = task_manager.jobs

def register_character_create_tool(mcp: FastMCP) -> None:
    @mcp.tool()
    def character_create(
        character_name: Annotated[str, Field(description="要创建的虚拟角色名称")],
        portrait_prompt: Annotated[str, Field(description="生成角色头像（肖像）的提示词。你必须严格使用全英文并且遵守以下模板且为了保持头像与全身像的同一性服装的描述必须一致，仅替换中括号里的主体描述：'Medium studio shot of a [主体外貌、穿着特征描述]. perfectly centered, forward-facing. Captured with a Hasselblad H6D-100c and a 50mm lens. The skin is rendered with biological realism, featuring natural textures. Clamshell lighting with a bottom silver reflector creates a luminous glow. The composition is a head and shoulders shot with clear headroom, ensuring the character's full head is entirely within the frame and not cropped by the top border against a seamless, solid white background.'")],
        project_name: Annotated[str, Field(description="Google Flow 项目的名称，留空则自动选用最近访问的项目")] = "",
        fullbody_prompt: Annotated[str, Field(description="生成角色全身像的提示词，留空则不生成且为了保持头像与全身像的同一性服装的描述必须一致。如果需要生成，必须严格使用全英文并且遵守以下模板，仅替换中括号里的主体描述（描述需与头像主体一致）：'Full-body character design sheet, featuring a triptych of three different angles: front view, three-quarter view, and back view. High resolution, flat studio lighting, consistent body proportions across all views, solid white background. [主体外貌、穿着特征描述]'")] = "",
        voice_name: Annotated[str, Field(description="角色的声音名称，例如 'Journey' 等，留空则不设置")] = "",
        voice_style: Annotated[str, Field(description="角色的声音风格，留空则不设置")] = "",
        model_name: Annotated[str, Field(description="用于生成图片的模型名称")] = "Nano banana pro",
        download: Annotated[bool, Field(description="是否自动下载生成的角色头像及全身像图片，默认为 False")] = False,
        image_base64: Annotated[bool, Field(description="是否返回 base64 格式的图片数据，默认为 False 不返回")] = False
    ) -> str:
        """
        在 Google Flow 中创建一个新的虚拟角色，并为其生成头像、全身像以及配置声音。
        
        注意：
        1. 由于生成过程需要几分钟，此工具会在后台启动任务，并立即返回一个 job_id。
        2. 若当前已有生成任务进行中，该任务将自动进入全局排队队列。
        3. 你**必须**使用 `character_status` 工具轮询这个 job_id 来获取最终的生成结果（包含本地下载路径，若 image_base64=True 还包含图片 base64 数据）。
        """
        # 0. Resolve project_name
        cache = ProjectCache.load()
        projects = cache.get("projects", {})
        
        if not project_name or not project_name.strip():
            if projects:
                project_name = max(
                    projects.keys(),
                    key=lambda k: projects[k].get("last_accessed", "")
                )
                logger.info(f"character_create: project_name not provided, defaulting to latest project: {project_name}")
            else:
                project_name = "default"

        job_id = str(uuid.uuid4())
        initial_state = {
            "job_id": job_id,
            "status": "pending",
            "is_finished": False,
            "character_name": character_name,
            "message": "Character creation started in the background."
        }
        
        logger.info(f"Submitting character_create task {job_id}: project={project_name}, name={character_name}, download={download}, image_base64={image_base64}")
        
        def task_worker():
            try:
                browser = get_browser()
                page = FlowCharacterPage(browser.latest_tab)
                
                # Step 1 & 2: Navigate
                from google_flow_mcp.utils.project_utils import ensure_project_exists
                project_url = ensure_project_exists(project_name, browser)
                page.navigate_to_characters(project_url)
                
                # Step 3: New Character
                if not page.click_new_character():
                    task_manager.jobs[job_id] = {
                        "job_id": job_id,
                        "status": "error",
                        "is_finished": True,
                        "error": "Failed to open character editor.",
                        "message": "Failed to open character editor."
                    }
                    return
                    
                # Step 4-6: Generate Portrait
                portrait_base64 = page.generate_portrait(portrait_prompt, model_name=model_name)
                
                # Step 6.5: Rename character after generation
                page.rename_character(character_name)
                
                portrait_local_path = ""
                fullbody_local_path = ""
                download_warning = False

                # Step 6.6: Download portrait if requested
                if download:
                    p_path = page.download_character_image(f"{character_name}_Portrait")
                    if p_path:
                        portrait_local_path = p_path
                    else:
                        download_warning = True
                
                # Step 7: Voice Configuration
                if voice_name:
                    page.configure_voice(voice_name, voice_style)
                
                # Step 8: Generate Fullbody
                fullbody_base64 = ""
                if fullbody_prompt:
                    fullbody_base64 = page.generate_fullbody(character_name, fullbody_prompt, model_name=model_name)
                    
                    # Step 8.5: Download fullbody before saving character if requested
                    if download:
                        fb_path = page.download_character_image(f"{character_name}_Fullbody")
                        if fb_path:
                            fullbody_local_path = fb_path
                        else:
                            download_warning = True
                    
                # Step 9: Save Character
                page.save_character()
                
                if download_warning:
                    status = "completed_with_download_warning"
                    msg = f"虚拟角色 {character_name} 创建成功，但部分图片下载失败或超时。"
                    if portrait_local_path:
                        msg += f" 头像已下载至: {portrait_local_path}。"
                    if fullbody_local_path:
                        msg += f" 全身像已下载至: {fullbody_local_path}。"
                else:
                    status = "completed"
                    msg = f"虚拟角色 {character_name} 创建成功。"
                    if download:
                        if portrait_local_path:
                            msg += f" 头像已下载至: {portrait_local_path}。"
                        if fullbody_local_path:
                            msg += f" 全身像已下载至: {fullbody_local_path}。"

                task_manager.jobs[job_id] = {
                    "job_id": job_id,
                    "status": status,
                    "is_finished": True,
                    "character_name": character_name,
                    "portrait_image_base64": portrait_base64 if image_base64 else "",
                    "fullbody_image_base64": fullbody_base64 if image_base64 else "",
                    "portrait_local_path": portrait_local_path,
                    "fullbody_local_path": fullbody_local_path,
                    "message": msg
                }
                logger.info(f"Background job {job_id} completed successfully with status: {status}")
                
            except Exception as e:
                logger.error(f"Background job {job_id} failed: {str(e)}")
                task_manager.jobs[job_id] = {
                    "job_id": job_id,
                    "status": "error",
                    "is_finished": True,
                    "error": str(e),
                    "message": f"虚拟角色创建失败: {str(e)}"
                }

        task_params = {
            "project_name": project_name,
            "character_name": character_name,
            "portrait_prompt": portrait_prompt,
            "fullbody_prompt": fullbody_prompt,
            "voice_name": voice_name,
            "voice_style": voice_style,
            "model_name": model_name,
            "download": download,
            "image_base64": image_base64,
        }
        submit_result = task_manager.submit_task(
            task_type="character",
            job_id=job_id,
            initial_state=initial_state,
            worker_fn=task_worker,
            project_id=project_name,
            task_name=character_name,
            params=task_params,
        )
        return json.dumps(submit_result, ensure_ascii=False)


def register_character_status_tool(mcp: FastMCP) -> None:
    @mcp.tool()
    def character_status(job_id: str) -> str:
        """
        Check the status of a background character creation job.
        Returns the job state, including images (base64 if requested) and local download paths if completed.
        Supports status polling and queue position tracking.
        """
        state = task_manager.get_task_status(job_id)
        return json.dumps(state, ensure_ascii=False)

