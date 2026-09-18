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

# Global dictionary to store background job status
_jobs = {}

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
        quantity: Annotated[int, Field(description="生成的图片数量，通常为 1-4")] = 1
    ) -> str:
        """
        在 Google Flow 中发起后台图片生成任务。
        
        注意：
        1. 此工具会在后台启动生成任务并立即返回一个 job_id。
        2. 你**必须**使用 `image_status` 工具轮询该 job_id 以获取最终结果和生成的图片。
        """
        job_id = str(uuid.uuid4())
        _jobs[job_id] = {
            "status": "pending",
            "message": "Image creation started in the background."
        }
        
        logger.info(f"Starting image_create background job {job_id}: project={project_id}")
        
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
                    "status": "generating",
                    "progress_percent": 0,
                    "progress_text": "0%",
                    "elapsed_seconds": 0,
                    "message": "已点击生成，等待开始生成..."
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
                        
                    elapsed = time.time() - start_time
                    _jobs[job_id].update({
                        "status": "generating",
                        "progress_text": text,
                        "elapsed_seconds": round(elapsed, 1),
                        "message": f"图片生成中：{text}（已用时 {round(elapsed)}s）",
                    })
                    logger.info(f"Background job {job_id}: Progress {text} , elapsed {elapsed:.1f}s")
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
                
                edit_page.save_and_close()
                
                _jobs[job_id] = {
                    "status": "completed" if rename_success else "completed_with_rename_warning",
                    "message": f"Image generated and renamed to {rename_name}" if rename_success else f"Image generated but rename failed.",
                    "image_name": rename_name,
                    "image_url": img_url,
                    "image_base64": b64_data,
                    "base64": b64_data,
                    "rename_success": rename_success
                }
                logger.info(f"Background job {job_id} completed successfully.")
                
            except Exception as e:
                logger.error(f"Background job {job_id} failed: {str(e)}")
                _jobs[job_id] = {"status": "error", "error": str(e)}

        thread = threading.Thread(target=task_worker, daemon=True)
        thread.start()
        
        return json.dumps({
            "success": True,
            "status": "started",
            "job_id": job_id,
            "message": "Job is running in background. Poll using image_status tool."
        }, ensure_ascii=False)

def register_image_status_tool(mcp: FastMCP) -> None:
    @mcp.tool()
    def image_status(job_id: str) -> str:
        """
        Check the status of a background image creation job.
        """
        if job_id not in _jobs:
            return json.dumps({"error": f"Job ID {job_id} not found."})
            
        state = _jobs[job_id]
        if state.get("status") in ["completed", "error"]:
            del _jobs[job_id]
            
        return json.dumps(state, ensure_ascii=False)
