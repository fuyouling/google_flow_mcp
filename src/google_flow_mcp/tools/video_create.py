import json
import threading
import uuid
import time
from typing import Annotated
from pydantic import Field
from loguru import logger
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.browser.session import get_browser

# Global dictionary to store background video job status
_video_jobs = {}


def apply_video_settings(
    page,
    mode: str = "frame",
    aspect_ratio: str = "16:9",
    model_name: str = "Omni 1.1 Flash",
    resolution: str = "720p",
    duration: int = 8,
    quantity: str = "x1",
) -> None:
    """Apply video configuration in Google Flow settings panel."""
    time.sleep(2)

    # 1. Open settings panel
    settings_btn = page.ele('tag:button@@aria-label=设置触发器', timeout=2)
    if not settings_btn:
        s_candidates = page.eles('tag:button@@text():🍌')
        if s_candidates:
            settings_btn = s_candidates[-1]

    if settings_btn:
        settings_btn.click()
        time.sleep(1)

    # 2. Switch to '视频' tab
    # vid_tab = page.ele('tag:button@@text():视频', timeout=2)
    vid_tab = page.ele('xpath://span[text()="视频" and @class="toggle-text"]',timeout=2)
    if vid_tab:
        vid_tab.click()
        logger.info("Switched to '视频' tab")
        time.sleep(0.5)

    # 3. Switch to '帧' or '素材' sub-tab
    is_frame_mode = mode.lower() in ["frame", "frames", "帧"]
    target_subtab = "帧" if is_frame_mode else "素材"
    # subtab_btn = (
    #     page.ele(f'xpath://button[contains(., "{target_subtab}")]', timeout=2)
    #     or page.ele(f'xpath://mat-button-toggle[contains(., "{target_subtab}")]', timeout=1)
    #     or page.ele(f'xpath://*[contains(@class, "toggle") and contains(., "{target_subtab}")]', timeout=1)
    #     or page.ele(f'tag:button@@text():{target_subtab}', timeout=1)
    #     or page.ele(f'text:{target_subtab}', timeout=1)
    # )
    subtab_btn = page.ele(f'tag:span@@text():{target_subtab}',timeout=2)
    if subtab_btn:
        subtab_btn.click()
        logger.info(f"Switched to '{target_subtab}' sub-tab")
        time.sleep(0.5)

    # 4. Aspect Ratio (16:9 / 9:16)
    ratio_btn = page.ele(f'tag:button@@text():{aspect_ratio}', timeout=1)
    if ratio_btn:
        ratio_btn.click()
        logger.info(f"Set aspect ratio to {aspect_ratio}")
        time.sleep(0.5)

    # 5. Model Dropdown
    # Normalize model name
    m_lower = model_name.lower().strip()
    if "omni" in m_lower:
        target_model = "Omni 1.1 Flash"
    elif "lite" in m_lower or m_lower == "veo":
        target_model = "Veo 3.1 - Lite"
    elif "fast" in m_lower:
        target_model = "Veo 3.1 - Fast"
    elif "quality" in m_lower:
        target_model = "Veo 3.1 - Quality"
    else:
        target_model = model_name

    dropdown = page.ele('@@aria-label=选择模型系列', timeout=2) or page.ele('tag:button@@text():arrow_drop_down', timeout=2)
    if dropdown:
        dropdown.click()
        time.sleep(0.5)
        model_options = page.eles(f'tag:button@@text():{target_model}')
        for opt in model_options:
            if 'arrow_drop_down' not in (opt.text or ''):
                opt.click()
                logger.info(f"Selected model: {target_model}")
                time.sleep(0.5)
                break

    # 6. Resolution & Duration (Omni models only)
    if "omni" in target_model.lower():
        # Resolution
        res_btn = page.ele(f'tag:button@@text():{resolution}', timeout=1)
        if res_btn:
            res_btn.click()
            logger.info(f"Set resolution to {resolution}")
            time.sleep(0.5)

        # Duration
        dur_clean = str(duration).replace("秒", "").replace("s", "").strip()
        dur_target = f"{dur_clean} 秒"
        dur_btn = page.ele(f'tag:button@@text():{dur_target}', timeout=1)
        if dur_btn:
            dur_btn.click()
            logger.info(f"Set duration to {dur_target}")
            time.sleep(0.5)
    else:
        logger.info(f"Model {target_model} does not support resolution/duration selection; skipped.")

    # 7. Quantity (x1 ~ x4)
    qty_btn = page.ele(f'tag:button@@text()={quantity}', timeout=1)
    if qty_btn:
        qty_btn.click()
        logger.info(f"Set quantity to {quantity}")
        time.sleep(0.5)

    # 8. Close settings panel by pressing ESC
    page.run_cdp('Input.dispatchKeyEvent', type='rawKeyDown', windowsVirtualKeyCode=27)
    page.run_cdp('Input.dispatchKeyEvent', type='keyUp', windowsVirtualKeyCode=27)
    time.sleep(0.8)
    if page.ele('.cdk-overlay-backdrop', timeout=0.5):
        page.run_cdp('Input.dispatchKeyEvent', type='rawKeyDown', windowsVirtualKeyCode=27)
        page.run_cdp('Input.dispatchKeyEvent', type='keyUp', windowsVirtualKeyCode=27)
        time.sleep(0.5)


def bind_frame_image(page, chip_label: str, image_name: str) -> None:
    """Bind start or end frame image in frame mode."""
    logger.info(f"Binding frame [{chip_label}] with image {image_name!r}")
    chip = page.ele(f'tag:button@@text():{chip_label}', timeout=2)
    if not chip:
        chips = page.eles('.empty-chip')
        if chip_label == "开始" and chips:
            chip = chips[0]
        elif chip_label == "结束" and len(chips) > 1:
            chip = chips[1]

    if not chip:
        raise Exception(f"未找到 [{chip_label}] 帧选择按钮")

    chip.click()
    time.sleep(1)

    # Search in overlay
    search_input = page.ele('tag:input@@placeholder:搜索资源', timeout=2) or page.ele('tag:input@@placeholder:搜索', timeout=2)
    if not search_input:
        page.run_cdp('Input.dispatchKeyEvent', type='keyDown', windowsVirtualKeyCode=27)
        raise Exception("未找到画面图像搜索输入框")

    search_input.clear()
    search_input.input(image_name)
    logger.info(f"Searching for frame image: {image_name!r}")
    time.sleep(1.5)

    add_btn = page.ele('tag:button@@text():添加到提示', timeout=2)
    if add_btn:
        add_btn.click()
        logger.info(f"Added frame image {image_name!r} to prompt")
        time.sleep(1)
    else:
        page.run_cdp('Input.dispatchKeyEvent', type='keyDown', windowsVirtualKeyCode=27)
        time.sleep(0.5)
        raise Exception(f"未找到添加按钮或图片: {image_name!r}")


def add_asset_to_prompt(page, asset: str) -> None:
    """Add a reference material to prompt in asset mode."""
    add_btn = page.ele('@@aria-label=在提示框中添加素材', timeout=2)
    if add_btn:
        add_btn.click()
        logger.info("Clicked '在提示框中添加素材' button")
        time.sleep(1)
    else:
        logger.warning(f"'添加素材' button not found, skipping asset: {asset}")
        return
        
    search_input = page.ele('xpath://input[@class="search-input" and @placeholder="搜索资源"]', timeout=2)

    if search_input:
        search_input.clear()
        search_input.input(asset)
        logger.info(f"Searching for asset: {asset!r}")
        time.sleep(1.5)

        add_to_prompt_btn = page.ele('tag:button@@text():添加到提示', timeout=2)
        if add_to_prompt_btn:
            add_to_prompt_btn.click()
            logger.info(f"Clicked '添加到提示' for asset: {asset!r}")
            time.sleep(1)
        else:
            logger.warning(f"Asset result or add button not found for: {asset!r}")
            page.run_cdp('Input.dispatchKeyEvent', type='keyDown', windowsVirtualKeyCode=27)
            time.sleep(0.5)
    else:
        logger.warning(f"Search input not found for asset: {asset!r}")


def input_prompt(page, prompt: str) -> None:
    """Enter prompt into flow-rich-text-editor."""
    # flow-rich-text-editor contains a ProseMirror div[contenteditable="true"].
    # Ensure any open popups or overlays are closed before focusing.
    prompt_entered = False
    if page.ele('.cdk-overlay-backdrop', timeout=0.5):
        page.run_cdp('Input.dispatchKeyEvent', type='rawKeyDown', windowsVirtualKeyCode=27)
        page.run_cdp('Input.dispatchKeyEvent', type='keyUp', windowsVirtualKeyCode=27)
        time.sleep(0.5)

    editor = page.ele('xpath://flow-rich-text-editor[@class="prompt-input"]//div[@contenteditable="true"]', timeout=3)
    if not editor:
        editor = page.ele('xpath://flow-rich-text-editor[@class="prompt-input"]', timeout=2)

    if editor:
        editor.click()
        time.sleep(0.3)

        # Strategy 1: CDP Input.insertText — fires real browser input events into ProseMirror
        try:
            page.run_cdp('Input.insertText', text=prompt)
            time.sleep(0.5)
            pm_text = page.run_js("return (document.querySelector('flow-rich-text-editor.prompt-input div[contenteditable=\"true\"]') || {}).innerText || '';")
            if prompt.strip() in pm_text.strip():
                prompt_entered = True
                logger.info("Prompt entered via CDP Input.insertText and verified")
            else:
                logger.warning(f"CDP Input.insertText executed but text not verified in editor (got {pm_text!r}), trying JS clipboard fallback")
        except Exception as e:
            logger.warning(f"CDP Input.insertText failed: {e!r}, trying JS clipboard fallback")

        # Strategy 2: JS set clipboard + CDP Ctrl+V (fallback)
        if not prompt_entered:
            try:
                page.run_js("""
                    (function(text) {
                        navigator.clipboard.writeText(text).catch(function() {
                            // Sync fallback via execCommand on a temp textarea
                            var ta = document.createElement('textarea');
                            ta.value = text;
                            document.body.appendChild(ta);
                            ta.select();
                            document.execCommand('copy');
                            document.body.removeChild(ta);
                        });
                    })(arguments[0]);
                """, prompt)
                time.sleep(0.2)
                editor.click()
                time.sleep(0.1)
                # Ctrl+V via CDP key events
                page.run_cdp('Input.dispatchKeyEvent', type='keyDown',
                             modifiers=2, windowsVirtualKeyCode=86, key='v', code='KeyV')
                page.run_cdp('Input.dispatchKeyEvent', type='keyUp',
                             modifiers=2, windowsVirtualKeyCode=86, key='v', code='KeyV')
                time.sleep(0.5)
                pm_text = page.run_js("return (document.querySelector('flow-rich-text-editor.prompt-input div[contenteditable=\"true\"]') || {}).innerText || '';")
                if prompt.strip() in pm_text.strip():
                    prompt_entered = True
                    logger.info("Prompt entered via JS clipboard + CDP Ctrl+V and verified")
            except Exception as e2:
                logger.warning(f"JS clipboard fallback failed: {e2!r}")

        # Strategy 3: DrissionPage input fallback
        if not prompt_entered:
            try:
                editor.input(prompt)
                time.sleep(0.5)
                pm_text = page.run_js("return (document.querySelector('flow-rich-text-editor.prompt-input div[contenteditable=\"true\"]') || {}).innerText || '';")
                if prompt.strip() in pm_text.strip():
                    prompt_entered = True
                    logger.info("Prompt entered via editor.input() fallback and verified")
            except Exception as e3:
                logger.warning(f"editor.input() fallback failed: {e3!r}")

        time.sleep(1)

    if not prompt_entered:
        raise Exception("Could not find prompt input field on the page or prompt could not be entered")


def register_video_create_tool(mcp: FastMCP) -> None:
    @mcp.tool()
    def video_create(
        project_id: Annotated[str, Field(description="Google Flow 项目的唯一 ID，视频将创建在该项目内")],
        prompt: Annotated[str, Field(description="视频生成的提示词 (Prompt)，详细描述视频画面、主体动作、镜头运镜及光影风格")],
        video_name: Annotated[str, Field(description="生成的视频重命名名称，便于在项目素材库中检索与引用。留空则自动生成随机名称")] = "",
        model_name: Annotated[str, Field(description="生成视频的模型名称。可选: 'Omni 1.1 Flash' (支持调节分辨率与时长), 'Veo 3.1 - Lite', 'Veo 3.1 - Fast', 'Veo 3.1 - Quality' (电影级高画质与运镜)")] = "Omni 1.1 Flash",
        mode: Annotated[str, Field(description="生成模式: 'frame' (首尾帧模式，需提供 start_frame 和 end_frame) 或 'asset' (素材参考/纯文本模式，可提供 assets，若 assets 留空则为纯文生视频)")] = "frame",
        start_frame: Annotated[str, Field(description="[仅帧模式] 首帧图片名称，必须为该项目中已存在的图片资源")] = "",
        end_frame: Annotated[str, Field(description="[仅帧模式] 尾帧图片名称，必须为该项目中已存在的图片资源")] = "",
        assets: Annotated[str, Field(description="[仅素材模式] 逗号分隔的参考素材名称列表(项目中已有资源)。若留空则表示纯文本生视频")] = "",
        aspect_ratio: Annotated[str, Field(description="视频宽高比: '16:9' (横屏，适用于桌面/影视) 或 '9:16' (竖屏，适用于移动端短视频)")] = "16:9",
        resolution: Annotated[str, Field(description="视频分辨率 (仅 Omni 1.1 Flash 模型生效): 可选 '360p' 或 '720p'")] = "720p",
        duration: Annotated[int, Field(description="视频时长，单位为秒 (仅 Omni 1.1 Flash 模型生效): 例如 8")] = 8,
        quantity: Annotated[int, Field(description="单次并发生成的视频数量: 可选 1, 2, 3, 4 (对应界面 x1 ~ x4)")] = 1,
        download: Annotated[str, Field(description="可选下载清晰度: '270p', '720p', '1080p'。指定后将自动下载至本地目录并重命名，留空则不下载")] = "",
    ) -> str:
        """
        在 Google Flow 中发起后台视频生成任务。
        
        【一、 核心工作流与异步架构】
        1. 前置条件：必须提供有效的 project_id；若使用首尾帧或参考素材，该图片/素材必须已存在于该项目中。
        2. 异步执行：本工具在后台异步执行生成任务，立即返回任务启动信息与唯一 job_id（此时 is_finished=False）。
        3. 状态轮询：视频生成通常耗时 1~3 分钟（最大超时 5 分钟），智能体【必须】使用返回的 job_id 定期调用 `video_status` 工具轮询状态（建议每隔 5~10 秒轮询一次）。
        4. 结束判定：智能体必须根据 `video_status` 返回的 `is_finished` 字段判定任务是否结束：
           - 若 `is_finished == False`：任务仍在生成中，智能体【严禁】停止轮询或向用户提前下结论，必须等待 5-10 秒后继续调用 `video_status` 查询。
           - 若 `is_finished == True`：任务已彻底完成（或失败），智能体方可停止轮询，并向用户展示视频链接、本地下载文件路径或错误信息。
        
        【二、 两大生成模式与参数互斥规则】
        1. 首尾帧模式 (mode='frame')：
           - 适用场景：指定起始图与结束图，让 AI 生成两张图之间的动作过渡/插值动画。
           - 必需参数：必须同时提供 start_frame 和 end_frame（项目内已有的图片资源名称）。
           - 互斥限制：【严禁】传递 assets 参数（否则触发 ValidationError 报错）。
        2. 素材参考 / 纯文本模式 (mode='asset')：
           - 纯文本生视频 (Text-to-Video)：mode='asset' 且 assets="" 留空，仅依靠 prompt 纯文本描述生成。
           - 素材参考生视频 (Asset-to-Video)：mode='asset' 且 assets 提供逗号分隔的已有素材名称（作为主体或风格参考）。
           - 互斥限制：【严禁】传递 start_frame 或 end_frame 参数（否则触发 ValidationError 报错）。
        
        【三、 支持的模型系列与参数差异】
        1. 'Omni 1.1 Flash'：
           - 独占特性：支持在设置面板中指定分辨率 resolution ('360p', '720p') 与视频时长 duration (例如 8 秒)。响应快，适合快速预览。
        2. 'Veo 3.1 - Lite', 'Veo 3.1 - Fast', 'Veo 3.1 - Quality'：
           - 独占特性：电影级运镜与光影质感。不支持设置 resolution 与 duration（传入将被自动忽略）。推荐追求高质量画面时使用。
        
        【四、 画面外观与产物控制】
        - aspect_ratio：'16:9' (标准横屏) 或 '9:16' (移动端竖屏短视频)。
        - quantity：单次生成数量，支持 1 ~ 4 (对应界面 x1 ~ x4)。
        - video_name：生成完毕后自动进入详情页重命名该视频卡片，便于素材库归档管理。留空则默认为 video_{job_id[:8]}。
        - download：指定 '270p', '720p', '1080p' 后，自动触发本地下载并重命名为 {video_name}.mp4，完成后在 video_status 中返回本地文件绝对路径 video_local_path。
        
        【五、 智能体典型调用场景示例】
        - 场景 1：纯文生视频 (Omni 720p 8秒横屏 + 本地 1080p 下载)
          video_create(project_id="...", prompt="...", model_name="Omni 1.1 Flash", mode="asset", assets="", aspect_ratio="16:9", resolution="720p", duration=8, download="1080p")
        - 场景 2：首尾帧过渡视频 (Veo 3.1 Fast 帧动画)
          video_create(project_id="...", prompt="...", model_name="Veo 3.1 - Fast", mode="frame", start_frame="sunny_landscape", end_frame="snowy_landscape", aspect_ratio="16:9")
        - 场景 3：参考已有素材生视频 (Veo 3.1 Quality 竖屏)
          video_create(project_id="...", prompt="...", model_name="Veo 3.1 - Quality", mode="asset", assets="hero_portrait", aspect_ratio="9:16")
        """
        # 1. Parameter validation
        if download and download.strip().lower() not in ("270p", "720p", "1080p"):
            return json.dumps({
                "success": False,
                "status": "error",
                "is_finished": True,
                "error_type": "ValidationError",
                "error": f"不支持的下载清晰度: {download!r}。仅支持 '270p', '720p', '1080p' 或留空不下载。",
                "message": f"不支持的下载清晰度: {download!r}。仅支持 '270p', '720p', '1080p' 或留空不下载。",
                "next_action": "参数错误，任务未启动，智能体请修正 download 参数后重新调用。"
            }, ensure_ascii=False)
        download = download.strip().lower() if download else ""

        is_frame_mode = mode.lower() in ["frame", "frames", "帧"]
        if is_frame_mode:
            if not start_frame or not end_frame:
                return json.dumps({
                    "success": False,
                    "status": "error",
                    "is_finished": True,
                    "error_type": "ValidationError",
                    "error": "在帧模式(frame)下，必须同时提供视频的首帧图片(start_frame)和尾帧图片(end_frame)。",
                    "message": "在帧模式(frame)下，必须同时提供视频的首帧图片(start_frame)和尾帧图片(end_frame)。",
                    "next_action": "参数缺失，任务未启动，智能体请同时提供 start_frame 和 end_frame 后重试。"
                }, ensure_ascii=False)
            if assets and assets.strip():
                return json.dumps({
                    "success": False,
                    "status": "error",
                    "is_finished": True,
                    "error_type": "ValidationError",
                    "error": "在帧模式(frame)下不能选择其它素材(assets)，仅支持首帧与尾帧。",
                    "message": "在帧模式(frame)下不能选择其它素材(assets)，仅支持首帧与尾帧。",
                    "next_action": "参数冲突，帧模式不支持 assets 参数，智能体请清空 assets 后重试。"
                }, ensure_ascii=False)
        else:
            if start_frame or end_frame:
                return json.dumps({
                    "success": False,
                    "status": "error",
                    "is_finished": True,
                    "error_type": "ValidationError",
                    "error": "在素材模式(asset)下不支持首尾帧(start_frame/end_frame)，如需使用首尾帧请指定 mode='frame'。",
                    "message": "在素材模式(asset)下不支持首尾帧(start_frame/end_frame)，如需使用首尾帧请指定 mode='frame'。",
                    "next_action": "参数冲突，素材模式不支持首尾帧参数，智能体请指定 mode='frame' 或移除首尾帧参数后重试。"
                }, ensure_ascii=False)

        job_id = str(uuid.uuid4())
        _video_jobs[job_id] = {
            "job_id": job_id,
            "status": "pending",
            "is_finished": False,
            "progress": 0,
            "progress_percent": 0,
            "progress_text": "0%",
            "elapsed_seconds": 0,
            "message": "视频创建任务已在后台启动，超时时间为 5 分钟 (300s)，正在准备参数并导航至项目...",
            "next_action": f"任务初始化中（尚未完成），请等待 5-10 秒后继续调用 video_status(job_id='{job_id}') 检查进度。",
            "details": {
                "project_id": project_id,
                "model_name": model_name,
                "mode": mode,
                "start_frame": start_frame,
                "end_frame": end_frame,
                "assets": assets,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "duration": duration,
                "quantity": quantity,
                "download": download,
            }
        }

        logger.info(f"Starting video_create background job {job_id}: project={project_id}, mode={mode}")

        def task_worker():
            t0 = time.time()
            try:
                browser = get_browser()
                page = browser.latest_tab

                # 1. Navigate to project
                url = f"https://flow.google.com/project/{project_id}"
                if page.url != url:
                    page.get(url)
                    time.sleep(4)

                # 2. Apply settings
                qty_str = f"x{quantity}"
                apply_video_settings(
                    page=page,
                    mode=mode,
                    aspect_ratio=aspect_ratio,
                    model_name=model_name,
                    resolution=resolution,
                    duration=duration,
                    quantity=qty_str,
                )

                # 3. Add frames or assets
                if is_frame_mode:
                    bind_frame_image(page, "开始", start_frame)
                    bind_frame_image(page, "结束", end_frame)
                elif assets:
                    asset_list = [a.strip() for a in assets.split(',') if a.strip()]
                    for a in asset_list:
                        add_asset_to_prompt(page, a)

                # 4. Enter prompt
                input_prompt(page, prompt)
                time.sleep(1)

                # 5. Wait for generate button
                for _ in range(10):
                    btns = page.eles('tag:button')
                    gen_candidates = [b for b in btns if 'generate-icon-button' in (b.attr('class') or '')]
                    if gen_candidates and not gen_candidates[0].attr('disabled'):
                        break
                    time.sleep(0.5)

                gen_btn = None
                for b in page.eles('tag:button'):
                    if 'generate-icon-button' in (b.attr('class') or ''):
                        gen_btn = b
                        break

                if not gen_btn:
                    raise Exception("Generate button not found")

                # Click generate button
                gen_btn.click(by_js=True)
                logger.info(f"Video job {job_id}: Clicked generate button.")

                _video_jobs[job_id].update({
                    "job_id": job_id,
                    "status": "generating",
                    "is_finished": False,
                    "progress": 0,
                    "progress_percent": 0,
                    "progress_text": "0%",
                    "elapsed_seconds": 0,
                    "message": "已点击生成，等待开始生成...",
                    "next_action": f"任务已提交，等待开始生成，请等待 5-10 秒后继续调用 video_status(job_id='{job_id}') 检查进度。",
                })

                # 1. Wait for loading-percentage element to appear (up to 40s)
                loading_xpath = 'xpath://div[@class="loading-percentage"]'
                start_time = time.time()
                loading_appeared = False

                for _ in range(80):  # 80 * 0.5s = 40s
                    if page.ele(loading_xpath, timeout=0.5):
                        loading_appeared = True
                        logger.info("Found loading-percentage element, video generation started.")
                        break
                    time.sleep(0.5)

                if not loading_appeared:
                    raise Exception("等待生成进度标签 (//div[@class='loading-percentage']) 超时（40 秒内未出现），生成可能未启动或失败")

                # 2. Wait for loading-percentage element to disappear (generation complete)
                total_timeout = 300  # 5 minutes
                import re as _re
                while time.time() - start_time < total_timeout:
                    els = page.eles(loading_xpath)
                    if not els:
                        # Check for generation errors first
                        error_el = page.ele('xpath://div[@class="error-title"]', timeout=0)
                        if error_el:
                            error_msg = error_el.text or "发生未知错误"
                            raise Exception(f"视频生成失败: {error_msg}")

                        logger.info(f"loading-percentage element disappeared. Video generation complete! (elapsed {time.time() - start_time:.1f}s)")
                        break

                    progress_texts = []
                    max_percent = None
                    for el in els:
                        t = (el.text or '').strip()
                        if t:
                            progress_texts.append(t)
                            m = _re.search(r'(\d{1,3})', t)
                            if m:
                                p = int(m.group(1))
                                if max_percent is None or p > max_percent:
                                    max_percent = p

                    percent = max_percent if max_percent is not None else 0
                    text = ' / '.join(progress_texts) if progress_texts else f"{percent}%"
                    elapsed = time.time() - start_time
                    _video_jobs[job_id].update({
                        "job_id": job_id,
                        "status": "generating",
                        "is_finished": False,
                        "progress": percent,
                        "progress_percent": percent,
                        "progress_text": text,
                        "elapsed_seconds": round(elapsed, 1),
                        "message": f"视频生成中：{text}（已用时 {round(elapsed)}s）",
                        "next_action": f"视频正在生成中（进度 {text}），尚未完成。请等待 5-10 秒后继续调用 video_status(job_id='{job_id}') 检查进度。",
                    })
                    logger.info(f"Background job {job_id}: Progress {text} ({percent}%), elapsed {elapsed:.1f}s")
                    time.sleep(5)
                else:
                    raise Exception(f"视频生成超时（超过 {total_timeout} 秒未完成）")

                # 3. Get video URL directly from the list view
                time.sleep(2)
                video_url = ""
                video_tag = page.ele('xpath:(//video)[1]', timeout=5)
                if video_tag:
                    video_url = video_tag.attr('src') or ""
                    logger.info(f"Extracted video URL: {video_url}")

                # 4. Locate the newest tile and click to enter details
                tile_xpath = 'xpath://flow-grid-tile-container[1]'
                tile = page.ele(tile_xpath, timeout=10)
                if not tile:
                    raise Exception("未找到最新生成的视频容器 (//flow-grid-tile-container[1])")

                logger.info("Clicking newest tile //flow-grid-tile-container[1] to enter detail view...")
                try:
                    tile.click()
                except Exception as e:
                    logger.warning(f"Direct click on tile failed: {e}, trying click(by_js=True)")
                    tile.click(by_js=True)

                time.sleep(3)

                from google_flow_mcp.pages.video_edit_page import VideoEditPage
                edit_page = VideoEditPage(page)
                
                rename_name = video_name if video_name else f"video_{job_id[:8]}"
                rename_success = edit_page.rename(rename_name)
                
                # Handle video download if requested
                video_local_path = ""
                download_warning = False
                if download:
                    local_path = edit_page.download_video(resolution=download, expected_prefix=rename_name, timeout=120)
                    if local_path:
                        video_local_path = local_path
                    else:
                        download_warning = True
                        logger.warning(f"Failed or timed out downloading {download} video for job {job_id}")

                edit_page.save_and_close()
                
                total_time = round(time.time() - t0, 1)

                if not rename_success:
                    status = "completed_with_rename_warning"
                    msg = "视频生成成功，但重命名失败"
                elif download_warning:
                    status = "completed_with_download_warning"
                    msg = f"视频生成成功，已重命名为 {rename_name}，但 {download} 下载超时或失败"
                else:
                    status = "completed"
                    msg = f"视频生成成功，已重命名为 {rename_name}"
                    if download and video_local_path:
                        msg += f"，{download} 视频已下载至 {video_local_path}"

                _video_jobs[job_id] = {
                    "job_id": job_id,
                    "status": status,
                    "is_finished": True,
                    "progress": 100,
                    "progress_percent": 100,
                    "progress_text": "100%",
                    "message": msg,
                    "next_action": "任务已顺利完成，智能体请停止轮询，可直接向用户汇报视频链接及本地文件。",
                    "video_name": rename_name,
                    "video_url": video_url,
                    "video_local_path": video_local_path,
                    "rename_success": rename_success,
                    "elapsed_seconds": total_time,
                    "details": {
                        "project_id": project_id,
                        "model_name": model_name,
                        "mode": mode,
                        "start_frame": start_frame,
                        "end_frame": end_frame,
                        "aspect_ratio": aspect_ratio,
                        "resolution": resolution,
                        "duration": duration,
                        "quantity": quantity,
                        "download": download,
                    }
                }
                logger.info(f"Video job {job_id} completed with status {status} in {total_time}s")

            except Exception as e:
                total_time = round(time.time() - t0, 1)
                logger.error(f"Video job {job_id} failed: {e}")
                _video_jobs[job_id] = {
                    "job_id": job_id,
                    "status": "error",
                    "is_finished": True,
                    "error": str(e),
                    "message": f"视频生成任务失败: {str(e)}",
                    "elapsed_seconds": total_time,
                    "next_action": "任务执行失败，智能体请停止轮询，可向用户汇报具体失败原因。"
                }

        thread = threading.Thread(target=task_worker, daemon=True)
        thread.start()

        return json.dumps({
            "success": True,
            "status": "started",
            "is_finished": False,
            "job_id": job_id,
            "message": f"视频创建任务已在后台启动，超时时间为 5 分钟 (300s)。请调用 video_status(job_id='{job_id}') 轮询结果。",
            "next_action": f"请等待 5-10 秒后调用 video_status(job_id='{job_id}') 查询进度，依据返回的 is_finished 字段判断是否完成。",
            "params": {
                "project_id": project_id,
                "prompt": prompt,
                "video_name": video_name,
                "model_name": model_name,
                "mode": mode,
                "start_frame": start_frame,
                "end_frame": end_frame,
                "assets": assets,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "duration": duration,
                "quantity": quantity,
                "download": download,
            }
        }, ensure_ascii=False)


def register_video_status_tool(mcp: FastMCP) -> None:
    @mcp.tool()
    def video_status(job_id: str) -> str:
        """
        查询 Google Flow 后台视频生成任务的当前状态与生成结果。
        
        【智能体调用与状态判定准则】
        1. 核心结束判定依据：`is_finished` (bool)
           - 当 `is_finished == False`：任务仍在后台生成处理中（处于 pending 或 generating 状态）。视频生成通常耗时 1~3 分钟，智能体【绝不能】停止轮询或向用户谎称已完成，必须等待 5~10 秒后继续调用本工具查询。
           - 当 `is_finished == True`：任务已彻底完成或出错。智能体【必须停止轮询】，直接获取视频 URL、本地下载文件等数据向用户汇报。
        2. `status` 状态枚举说明：
           - 'pending': 任务排队中，正在初始化页面或配置参数（is_finished=False）。
           - 'generating': 视频正在生成中，可查看 progress_text（如 '45%'）、progress_percent（数值 45）及 elapsed_seconds 已耗时（is_finished=False）。
           - 'completed': 视频生成成功且重命名完成。若设置了 download，将返回 video_local_path 本地文件绝对路径（is_finished=True）。
           - 'completed_with_rename_warning': 视频生成成功，但重命名未成功（is_finished=True）。
           - 'completed_with_download_warning': 视频生成与重命名成功，但视频下载超时或失败（仍包含 video_url 线上链接）（is_finished=True）。
           - 'error': 任务失败，详细原因见 error 字段（is_finished=True）。
        3. 建议行动：直接参考返回的 `next_action` 字段进行下一步操作（继续轮询等待或汇报结果）。
        """
        if job_id not in _video_jobs:
            return json.dumps({
                "job_id": job_id,
                "status": "error",
                "is_finished": True,
                "error": f"未找到任务 ID: {job_id}。任务可能不存在或服务已重启。",
                "message": f"未找到任务 ID: {job_id}。任务可能不存在或服务已重启。",
                "next_action": "未找到任务记录，智能体请停止轮询，请核对 job_id 或重新发起任务。"
            }, ensure_ascii=False)

        state = _video_jobs[job_id]
        return json.dumps(state, ensure_ascii=False)
