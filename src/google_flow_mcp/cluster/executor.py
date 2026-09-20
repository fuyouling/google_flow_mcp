import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from loguru import logger

from google_flow_mcp.cluster.models import TaskPayload, TaskType
from google_flow_mcp.pages.flow_character_page import FlowCharacterPage
from google_flow_mcp.pages.flow_image_page import FlowImagePage
from google_flow_mcp.pages.flow_video_page import FlowVideoPage
from google_flow_mcp.pages.video_edit_page import VideoEditPage


def execute_cluster_task(
    tab,
    project_id: str,
    task: TaskPayload,
    progress_callback: Optional[Callable[[str, str], None]] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Execute a cluster task on the local browser tab.
    Returns: (result_data_dict, produced_assets_list)
    """
    task_type = task.task_type
    params = task.params
    job_id = task.job_id

    def update_progress(status: str, msg: str):
        if progress_callback:
            progress_callback(status, msg)

    # ─────────────────────────────────────────────────────────
    # 1. VIDEO_CREATE
    # ─────────────────────────────────────────────────────────
    if task_type == TaskType.VIDEO_CREATE:
        from google_flow_mcp.tools.video_create import (
            apply_video_settings,
            bind_frame_image,
            add_asset_to_prompt,
            input_prompt,
        )

        prompt = params.get("prompt", "")
        video_name = params.get("video_name", "")
        model_name = params.get("model_name", "Omni 1.1 Flash")
        mode = params.get("mode", "frame")
        start_frame = params.get("start_frame", "")
        end_frame = params.get("end_frame", "")
        assets = params.get("assets", "")
        aspect_ratio = params.get("aspect_ratio", "16:9")
        resolution = params.get("resolution", "720p")
        duration = params.get("duration", 8)
        quantity = params.get("quantity", 1)
        download = params.get("download", "")

        is_frame_mode = mode.lower() in ["frame", "frames", "帧"]

        # Navigate to project
        url = f"https://flow.google.com/project/{project_id}"
        if tab.url != url:
            tab.get(url)
            time.sleep(4)

        # Apply settings
        apply_video_settings(
            page=tab,
            mode=mode,
            aspect_ratio=aspect_ratio,
            model_name=model_name,
            resolution=resolution,
            duration=duration,
            quantity=f"x{quantity}",
        )

        # Add frames or assets
        if is_frame_mode:
            bind_frame_image(tab, "开始", start_frame)
            bind_frame_image(tab, "结束", end_frame)
        elif assets:
            asset_list = [a.strip() for a in assets.split(",") if a.strip()]
            for a in asset_list:
                add_asset_to_prompt(tab, a)

        # Enter prompt
        input_prompt(tab, prompt)
        time.sleep(1)

        # Click generate
        gen_btn = None
        for _ in range(10):
            btns = tab.eles("tag:button")
            candidates = [b for b in btns if "generate-icon-button" in (b.attr("class") or "")]
            if candidates and not candidates[0].attr("disabled"):
                gen_btn = candidates[0]
                break
            time.sleep(0.5)

        if not gen_btn:
            raise Exception("Generate button not found")

        gen_btn.click(by_js=True)
        update_progress("generating", "已点击生成，等待开始生成...")

        # Wait for loading indicator
        loading_xpath = 'xpath://div[@class="loading-percentage"]'
        loading_appeared = False
        for _ in range(80):
            if tab.ele(loading_xpath, timeout=0.5):
                loading_appeared = True
                break
            time.sleep(0.5)

        if not loading_appeared:
            raise Exception("等待生成进度标签超时（40 秒内未出现）")

        # Wait for completion
        start_time = time.time()
        total_timeout = 300
        while time.time() - start_time < total_timeout:
            els = tab.eles(loading_xpath)
            if not els:
                error_el = tab.ele('xpath://div[@class="error-title"]', timeout=0)
                if error_el:
                    raise Exception(f"视频生成失败: {error_el.text or '未知错误'}")
                break

            progress_texts = []
            max_percent = None
            for el in els:
                t = (el.text or "").strip()
                if t:
                    progress_texts.append(t)
                    m = re.search(r"(\d{1,3})", t)
                    if m:
                        p = int(m.group(1))
                        if max_percent is None or p > max_percent:
                            max_percent = p

            percent = max_percent if max_percent is not None else 0
            text = " / ".join(progress_texts) if progress_texts else f"{percent}%"
            update_progress("generating", f"视频生成中：{text}")
            time.sleep(5)
        else:
            raise Exception(f"视频生成超时（超过 {total_timeout} 秒未完成）")

        # Extract URL
        time.sleep(2)
        video_url = ""
        video_tag = tab.ele("xpath:(//video)[1]", timeout=5)
        if video_tag:
            video_url = video_tag.attr("src") or ""

        # Rename & download
        tile = tab.ele("xpath://flow-grid-tile-container[1]", timeout=10)
        if tile:
            try:
                tile.click()
            except Exception:
                tile.click(by_js=True)

        time.sleep(3)
        edit_page = VideoEditPage(tab)
        rename_name = video_name if video_name else f"video_{job_id[:8]}"
        rename_success = edit_page.rename(rename_name)

        video_local_path = ""
        if download:
            local_path = edit_page.download_video(
                resolution=download, expected_prefix=rename_name, timeout=120
            )
            if local_path:
                video_local_path = local_path

        edit_page.save_and_close()

        result_data = {
            "video_name": rename_name,
            "video_url": video_url,
            "video_local_path": video_local_path,
            "rename_success": rename_success,
            "project_id": project_id,
        }
        produced_assets = []
        if video_local_path and Path(video_local_path).exists():
            produced_assets.append({
                "name": rename_name,
                "type": "video",
                "local_path": video_local_path,
            })

        return result_data, produced_assets

    # ─────────────────────────────────────────────────────────
    # 2. IMAGE_CREATE_BY_UPLOAD
    # ─────────────────────────────────────────────────────────
    elif task_type == TaskType.IMAGE_CREATE_BY_UPLOAD:
        img_page = FlowImagePage(tab)
        image_path = params.get("image_path")
        image_name = params.get("image_name")
        img_page.upload_image_on_project_page(project_id, image_path)
        img_page.rename_and_save_in_detail(image_name)
        return (
            {"image_name": image_name, "project_id": project_id},
            [{"name": image_name, "type": "image", "local_path": image_path}],
        )

    # ─────────────────────────────────────────────────────────
    # 3. VIDEO_CREATE_BY_UPLOAD
    # ─────────────────────────────────────────────────────────
    elif task_type == TaskType.VIDEO_CREATE_BY_UPLOAD:
        vid_page = FlowVideoPage(tab)
        video_path = params.get("video_path")
        video_name = params.get("video_name")
        vid_page.upload_video_on_project_page(project_id, video_path)
        vid_page.rename_and_save_in_detail(video_name)
        return (
            {"video_name": video_name, "project_id": project_id},
            [{"name": video_name, "type": "video", "local_path": video_path}],
        )

    # ─────────────────────────────────────────────────────────
    # 4. CHARACTER_CREATE_BY_UPLOAD
    # ─────────────────────────────────────────────────────────
    elif task_type == TaskType.CHARACTER_CREATE_BY_UPLOAD:
        char_page = FlowCharacterPage(tab)
        char_name = params.get("character_name")
        portrait = params.get("portrait_image_path")
        fullbody = params.get("fullbody_image_path", "")
        char_page.navigate_to_characters(project_id)
        if not char_page.click_new_character():
            raise Exception("Failed to open character editor in Flow")
        char_page.upload_portrait(portrait)
        if fullbody:
            char_page.upload_fullbody(fullbody)
        char_page.rename_character(char_name)
        char_page.save_character()
        return (
            {"character_name": char_name, "project_id": project_id},
            [{"name": char_name, "type": "character", "local_path": portrait}],
        )

    else:
        raise NotImplementedError(f"Task type {task_type} execution not implemented.")
