import json
import threading
import uuid
from typing import Annotated
from pydantic import Field
from loguru import logger
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.browser.session import get_browser
from google_flow_mcp.pages.flow_character_page import FlowCharacterPage
from google_flow_mcp.models.project_cache import ProjectCache

# Global dictionary to store background job status
_jobs = {}

def register_character_create_tool(mcp: FastMCP) -> None:
    @mcp.tool()
    def character_create(
        project_id: Annotated[str, Field(description="Google Flow 项目的唯一 ID")],
        character_name: Annotated[str, Field(description="要创建的虚拟角色名称")],
        portrait_prompt: Annotated[str, Field(description="生成角色头像（肖像）的提示词。你必须严格使用全英文并且遵守以下模板且为了保持头像与全身像的同一性服装的描述必须一致，仅替换中括号里的主体描述：'Medium studio shot of a [主体外貌、穿着特征描述]. perfectly centered, forward-facing. Captured with a Hasselblad H6D-100c and a 50mm lens. The skin is rendered with biological realism, featuring natural textures. Clamshell lighting with a bottom silver reflector creates a luminous glow. The composition is a head and shoulders shot with clear headroom, ensuring the character's full head is entirely within the frame and not cropped by the top border against a seamless, solid white background.'")],
        fullbody_prompt: Annotated[str, Field(description="生成角色全身像的提示词，留空则不生成且为了保持头像与全身像的同一性服装的描述必须一致。如果需要生成，必须严格使用全英文并且遵守以下模板，仅替换中括号里的主体描述（描述需与头像主体一致）：'Full-body character design sheet, featuring a triptych of three different angles: front view, three-quarter view, and back view. High resolution, flat studio lighting, consistent body proportions across all views, solid white background. [主体外貌、穿着特征描述]'")] = "",
        voice_name: Annotated[str, Field(description="角色的声音名称，例如 'Journey' 等，留空则不设置")] = "",
        voice_style: Annotated[str, Field(description="角色的声音风格，留空则不设置")] = "",
        model_name: Annotated[str, Field(description="用于生成图片的模型名称")] = "Nano banana pro"
    ) -> str:
        """
        在 Google Flow 中创建一个新的虚拟角色，并为其生成头像、全身像以及配置声音。
        
        注意：
        1. 由于生成过程需要几分钟，此工具会在后台启动任务，并立即返回一个 job_id。
        2. 你**必须**使用 `character_status` 工具轮询这个 job_id 来获取最终的生成结果（包含图片 base64 数据）。
        """
        job_id = str(uuid.uuid4())
        _jobs[job_id] = {
            "status": "pending",
            "message": "Character creation started in the background."
        }
        
        logger.info(f"Starting character_create background job {job_id}: project={project_id}, name={character_name}")
        
        def task_worker():
            try:
                browser = get_browser()
                page = FlowCharacterPage(browser.latest_tab)
                
                # Step 1 & 2: Navigate
                page.navigate_to_characters(project_id)
                
                # Step 3: New Character
                if not page.click_new_character():
                    _jobs[job_id] = {"status": "error", "error": "Failed to open character editor."}
                    return
                    
                # Step 4-6: Generate Portrait
                portrait_base64 = page.generate_portrait(portrait_prompt, model_name=model_name)
                
                # Step 6.5: Rename character after generation
                page.rename_character(character_name)
                
                # Step 7: Voice Configuration
                if voice_name:
                    page.configure_voice(voice_name, voice_style)
                
                # Step 8: Generate Fullbody
                fullbody_base64 = ""
                if fullbody_prompt:
                    fullbody_base64 = page.generate_fullbody(character_name, fullbody_prompt, model_name=model_name)
                    
                # Step 9: Save Character
                page.save_character()
                
                _jobs[job_id] = {
                    "status": "completed",
                    "character_name": character_name,
                    "portrait_image_base64": portrait_base64,
                    "fullbody_image_base64": fullbody_base64
                }
                logger.info(f"Background job {job_id} completed successfully.")
                
            except Exception as e:
                logger.error(f"Background job {job_id} failed: {str(e)}")
                _jobs[job_id] = {"status": "error", "error": str(e)}

        # Start background thread
        thread = threading.Thread(target=task_worker, daemon=True)
        thread.start()
        
        return json.dumps({
            "success": True,
            "status": "started",
            "job_id": job_id,
            "message": "Job is running in background. Poll using character_status tool."
        }, ensure_ascii=False)


def register_character_status_tool(mcp: FastMCP) -> None:
    @mcp.tool()
    def character_status(job_id: str) -> str:
        """
        Check the status of a background character creation job.
        Returns the job state, including images if completed.
        Once a completed or error state is read, the job is removed from memory.
        """
        if job_id not in _jobs:
            return json.dumps({"error": f"Job ID {job_id} not found."})
            
        state = _jobs[job_id]
        
        # Clean up memory if the job has finished
        if state.get("status") in ["completed", "error"]:
            del _jobs[job_id]
            
        return json.dumps(state, ensure_ascii=False)
