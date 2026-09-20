import json
import threading
import uuid
import time
from typing import Annotated
from pydantic import Field
from loguru import logger
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.browser.session import get_browser
from google_flow_mcp.models.project_cache import ProjectCache

from google_flow_mcp.tasks.manager import task_manager

# Reference to global jobs dictionary for backward compatibility
_jobs = task_manager.jobs

def apply_image_settings(page, aspect_ratio="16:9", model_name="Nano Banana Pro", quantity="x1"):
    # Wait for the page to be ready
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
    
    # img_tab = page.ele('tag:button@@text()=图片', timeout=1)
    img_tab = page.ele('xpath://span[text()="图片" and @class="toggle-text"]',timeout=2)
    if not img_tab:
        settings_btn = page.eles('tag:button@@text():🍌')
        if settings_btn:
            settings_btn[-1].click()
            time.sleep(1)
            img_tab = page.ele('tag:button@@text()=图片', timeout=2)
            
    if img_tab:
        img_tab.click()
        time.sleep(0.5)
        
    ratio_btn = page.ele(f'tag:button@@text():{aspect_ratio}', timeout=1)
    if ratio_btn:
        ratio_btn.click()
        time.sleep(0.5)
        
    dropdown = page.ele('tag:button@@text():arrow_drop_down', timeout=1)
    if dropdown:
        dropdown.click()
        time.sleep(0.5)
        pro_options = page.eles(f'tag:button@@text():{model_name}')
        # Click the one that doesn't have arrow_drop_down
        for opt in pro_options:
            if 'arrow_drop_down' not in opt.text:
                opt.click()
                time.sleep(0.5)
                break
                
    qty_btn = page.ele(f'tag:button@@text()={quantity}', timeout=1)
    if qty_btn:
        qty_btn.click()
        time.sleep(0.5)

    # Close settings panel by pressing ESC
    page.run_cdp('Input.dispatchKeyEvent', type='rawKeyDown', windowsVirtualKeyCode=27)
    page.run_cdp('Input.dispatchKeyEvent', type='keyUp', windowsVirtualKeyCode=27)
    time.sleep(0.8)
    if page.ele('.cdk-overlay-backdrop', timeout=0.5):
        page.run_cdp('Input.dispatchKeyEvent', type='rawKeyDown', windowsVirtualKeyCode=27)
        page.run_cdp('Input.dispatchKeyEvent', type='keyUp', windowsVirtualKeyCode=27)
        time.sleep(0.5)

def register_image_create_tool(mcp: FastMCP) -> None:
    @mcp.tool()
    def image_create(
        project_id: Annotated[str, Field(description="Google Flow 项目的唯一 ID")],
        prompt: Annotated[str, Field(description="生成图片的提示词")],
        assets: Annotated[str, Field(description="可选的参考素材名称，多个用逗号分隔")] = "",
        image_name: Annotated[str, Field(description="生成后的图片重命名名称，留空则自动生成")] = "",
        aspect_ratio: Annotated[str, Field(description="图片宽高比，例如 '16:9' 或 '9:16'")] = "16:9",
        model_name: Annotated[str, Field(description="使用的模型名称")] = "Nano Banana Pro",
        quantity: Annotated[int, Field(description="生成的图片数量，通常为 1-4")] = 1,
        download: Annotated[str, Field(description="可选下载分辨率，可选 '1K' 或 '2K'，留空则不下载")] = ""
    ) -> str:
        """
        在 Google Flow 中发起后台图片生成任务。
        
        【重要执行规则与状态轮询机制】
        1. 异步执行与全局队列：本工具在后台异步执行生成任务。由于浏览器单一，全服务所有生成任务（涵盖图片/视频/角色）共用全局单任务队列串行执行。若当前空闲则立即启动（status='started'）；若已有任务在生成中，将自动进入全局 FIFO 排队队列（status='queued'），前置任务完成后自动顺序执行。智能体【严禁】因看到 queued 而重复调用创建工具！
        2. 必须轮询：调用成功后，智能体【必须】使用返回的 `job_id` 定期调用 `image_status` 工具查询任务最新进度与最终结果。
        3. 结束判定：智能体必须根据 `image_status` 返回的 `is_finished` 字段判定任务是否结束：
           - 若 `is_finished == False`：表示任务正在排队中（queued）或正在生成中（pending/generating），智能体【严禁】提前向用户宣称完成，必须等待 5 秒后继续调用 `image_status` 轮询。
           - 若 `is_finished == True`：表示任务彻底结束（成功完成或发生异常），智能体方可停止轮询，并向用户展示生成的图片结果或错误说明。
        4. 全局查看与取消：可随时调用 `task_queue_status` 工具查看全局排队概览；使用 `task_cancel(job_id)` 可取消排队或中断任务。
        """
        if download and download not in ("1K", "2K"):
            return json.dumps({
                "success": False,
                "status": "error",
                "is_finished": True,
                "error": f"Invalid download resolution: {download!r}. Only '1K' and '2K' are supported.",
                "message": f"不支持的下载分辨率: {download!r}。仅支持 '1K' 或 '2K'，留空则不下载。",
                "next_action": "参数错误，任务未启动，智能体请修正 download 参数后重新调用。"
            }, ensure_ascii=False)

        job_id = str(uuid.uuid4())
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "pending",
            "is_finished": False,
            "progress": 0,
            "progress_percent": 0,
            "progress_text": "0%",
            "elapsed_seconds": 0,
            "message": "图片生成任务已在后台启动，正在初始化页面及参数设置...",
            "next_action": f"任务初始化中（尚未完成），请等待 5 秒后继续调用 image_status(job_id='{job_id}') 检查进度。"
        }
        
        logger.info(f"Starting image_create background job {job_id}: project={project_id}, download={download!r}")
        
        def task_worker():
            try:
                browser = get_browser()
                page = browser.latest_tab
                
                # Navigate to project
                url = f"https://flow.google.com/project/{project_id}"
                if page.url != url:
                    page.get(url)
                    time.sleep(4)
                
                # Apply settings
                qty_str = f"x{quantity}"
                apply_image_settings(page, aspect_ratio, model_name, qty_str)
                
                # Add assets FIRST (before entering prompt)
                if assets:
                    asset_list = [a.strip() for a in assets.split(',') if a.strip()]
                    for asset in asset_list:
                        # 1. Click "添加素材" button (aria-label='在提示框中添加素材')
                        add_btn = page.ele('@@aria-label=在提示框中添加素材', timeout=2)
                        if add_btn:
                            add_btn.click()
                            logger.info("Clicked '在提示框中添加素材' button")
                            time.sleep(1)
                        else:
                            logger.warning("'添加素材' button not found, skipping asset: " + asset)
                            continue
                        
                        search_input = page.ele('xpath://input[@class="search-input" and @placeholder="搜索资源"]', timeout=2)

                        # 2. Search for the asset
                        if search_input:
                            search_input.clear()
                            search_input.input(asset)
                            logger.info(f"Searching for asset: {asset!r}")
                            time.sleep(1.5)  # Wait for search results

                            # 3. Click '添加到提示' (Add to prompt) directly
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

                # Input prompt (after assets)
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

                time.sleep(1)

                # Wait for generate button to become enabled (up to 5s)
                for _ in range(10):
                    btns = page.eles('tag:button')
                    gen_candidates = [b for b in btns if 'generate-icon-button' in (b.attr('class') or '')]
                    if gen_candidates and not gen_candidates[0].attr('disabled'):
                        break
                    time.sleep(0.5)
                else:
                    logger.warning("Generate button still disabled after waiting; attempting click anyway")

                # Click generate button
                gen_btn = None
                btns = page.eles('tag:button')
                for b in btns:
                    cls = b.attr('class') or ''
                    if 'generate-icon-button' in cls:
                        gen_btn = b
                        break
                
                if not gen_btn:
                    raise Exception("Generate button not found")
                    
                # Click generate button
                gen_btn.click(by_js=True)
                logger.info(f"Background job {job_id}: Clicked generate button.")
                
                _jobs[job_id] = {
                    "job_id": job_id,
                    "status": "generating",
                    "is_finished": False,
                    "progress": 0,
                    "progress_percent": 0,
                    "progress_text": "0%",
                    "elapsed_seconds": 0,
                    "message": "已点击生成，等待开始生成...",
                    "next_action": f"任务已提交，等待开始生成，请等待 5 秒后继续调用 image_status(job_id='{job_id}') 检查进度。"
                }

                # 1. Wait for loading-percentage element to appear (up to 40s)
                loading_xpath = 'xpath://div[@class="loading-percentage"]'
                start_time = time.time()
                loading_appeared = False

                for _ in range(80):  # 80 * 0.5s = 40s
                    if page.ele(loading_xpath, timeout=0.5):
                        loading_appeared = True
                        logger.info("Found loading-percentage element, image generation started.")
                        break
                    time.sleep(0.5)

                if not loading_appeared:
                    raise Exception("等待生成进度标签 (//div[@class='loading-percentage']) 超时（40 秒内未出现），生成可能未启动或失败")

                # 2. Wait for loading-percentage element to disappear (generation complete)
                total_timeout = 180  # 3 minutes
                while time.time() - start_time < total_timeout:

                    els = page.eles(loading_xpath)
                    if not els:
                        # Check for generation errors first
                        error_el = page.ele('xpath://div[@class="error-title"]', timeout=0)
                        if error_el:
                            error_msg = error_el.text or "发生未知错误"
                            raise Exception(f"图片生成失败: {error_msg}")

                        logger.info(f"loading-percentage element disappeared. Image generation complete! (elapsed {time.time() - start_time:.1f}s)")
                        break

                    text = els[0].text or ''
                    import re as _re
                    m = _re.search(r'(\d{1,3})', text)
                    percent = int(m.group(1)) if m else 0
                        
                    elapsed = time.time() - start_time
                    _jobs[job_id].update({
                        "job_id": job_id,
                        "status": "generating",
                        "is_finished": False,
                        "progress": percent,
                        "progress_percent": percent,
                        "progress_text": text if text else f"{percent}%",
                        "elapsed_seconds": round(elapsed, 1),
                        "message": f"图片生成中：{text}（已用时 {round(elapsed)}s）",
                        "next_action": f"任务正在生成中（{text}），尚未完成。请等待 5 秒后继续调用 image_status(job_id='{job_id}') 检查进度。"
                    })
                    logger.info(f"Background job {job_id}: Progress {text} ({percent}%), elapsed {elapsed:.1f}s")
                    time.sleep(5)
                else:
                    raise Exception(f"图片生成超时（超过 {total_timeout} 秒未完成）")

                # 3. Locate the newest tile and click to enter details
                time.sleep(2)
                tile_xpath = 'xpath://flow-grid-tile-container[1]'
                tile = page.ele(tile_xpath, timeout=10)
                if not tile:
                    raise Exception("未找到最新生成的图片容器 (//flow-grid-tile-container[1])")

                logger.info("Clicking newest tile //flow-grid-tile-container[1] to enter detail view...")
                try:
                    tile.click()
                except Exception as e:
                    logger.warning(f"Direct click on tile failed: {e}, trying click(by_js=True)")
                    tile.click(by_js=True)

                time.sleep(3)

                from google_flow_mcp.pages.image_edit_page import ImageEditPage
                edit_page = ImageEditPage(page)
                    
                rename_name = image_name if image_name else f"image_{job_id[:8]}"
                rename_success = edit_page.rename(rename_name)
                
                img_url = edit_page.get_media_url()
                b64_data = edit_page.get_base64()
                
                # Handle image download if requested
                image_local_path = ""
                download_warning = False
                if download in ("1K", "2K"):
                    local_path = edit_page.download_image(resolution=download, expected_prefix=rename_name)
                    if local_path:
                        image_local_path = local_path
                    else:
                        download_warning = True
                        logger.warning(f"Failed or timed out downloading {download} image for job {job_id}")

                edit_page.save_and_close()
                
                total_time = round(time.time() - start_time, 1)

                if not rename_success:
                    status = "completed_with_rename_warning"
                    msg = "图片生成成功，但重命名失败"
                elif download_warning:
                    status = "completed_with_download_warning"
                    msg = f"图片生成成功，已重命名为 {rename_name}，但 {download} 图片下载失败或超时"
                else:
                    status = "completed"
                    msg = f"图片生成成功，已重命名为 {rename_name}"
                    if download in ("1K", "2K") and image_local_path:
                        msg += f"，{download} 图片已下载至 {image_local_path}"

                _jobs[job_id] = {
                    "job_id": job_id,
                    "status": status,
                    "is_finished": True,
                    "progress": 100,
                    "progress_percent": 100,
                    "progress_text": "100%",
                    "elapsed_seconds": total_time,
                    "message": msg,
                    "next_action": "任务已顺利完成，智能体请停止轮询，可直接向用户展示图片结果及相关信息。",
                    "image_name": rename_name,
                    "image_url": img_url,
                    "image_base64": b64_data,
                    "base64": b64_data,
                    "image_local_path": image_local_path,
                    "rename_success": rename_success
                }
                logger.info(f"Background job {job_id} completed with status: {status}")
                
            except Exception as e:
                total_time = round(time.time() - start_time, 1) if 'start_time' in locals() else 0
                logger.error(f"Background job {job_id} failed: {str(e)}")
                _jobs[job_id] = {
                    "job_id": job_id,
                    "status": "error",
                    "is_finished": True,
                    "error": str(e),
                    "message": f"图片生成任务失败: {str(e)}",
                    "elapsed_seconds": total_time,
                    "next_action": "任务执行失败，智能体请停止轮询，可向用户汇报具体失败原因。"
                }

        submit_res = task_manager.submit_task(
            task_type="image",
            job_id=job_id,
            initial_state=_jobs[job_id],
            worker_fn=task_worker,
            project_id=project_id,
            task_name=image_name or f"image_{job_id[:8]}"
        )
        if submit_res.get("status") == "started":
            submit_res.update({
                "message": f"图片生成任务已在后台启动。请调用 image_status(job_id='{job_id}') 轮询任务状态（建议每 5 秒轮询一次）。",
                "next_action": f"请等待 5 秒后调用 image_status(job_id='{job_id}') 查询任务进度，依据返回的 is_finished 字段判断是否完成。"
            })
        return json.dumps(submit_res, ensure_ascii=False)

def register_image_status_tool(mcp: FastMCP) -> None:
    @mcp.tool()
    def image_status(job_id: str) -> str:
        """
        查询 Google Flow 后台图片生成任务的当前状态与生成结果。
        
        【智能体调用与状态判定准则】
        1. 核心结束判定依据：`is_finished` (bool)
           - 当 `is_finished == False`：任务仍在后台处理中（处于 pending 或 generating 状态）。智能体【绝不能】停止轮询，必须等待 5 秒后继续调用本工具查询。
           - 当 `is_finished == True`：任务已彻底完成或出错。智能体【必须停止轮询】，直接获取结果数据向用户汇报。
        2. `status` 状态枚举说明：
           - 'pending': 任务排队中，正在初始化页面或配置参数（is_finished=False）。
           - 'generating': 图片正在生成中，可查看 progress_text / progress_percent（is_finished=False）。
           - 'completed': 图片生成成功且重命名完成（is_finished=True）。
           - 'completed_with_rename_warning': 图片生成成功，但重命名未成功（is_finished=True）。
           - 'completed_with_download_warning': 图片生成成功，但高清图片下载超时或失败（is_finished=True）。
           - 'error': 任务失败，详细原因见 error 字段（is_finished=True）。
        3. 建议行动：直接参考返回的 `next_action` 字段进行下一步操作。
        """
        state = task_manager.get_task_status(job_id)
        return json.dumps(state, ensure_ascii=False)
