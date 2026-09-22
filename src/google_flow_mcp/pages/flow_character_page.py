import time
import shutil
from pathlib import Path
from loguru import logger
from google_flow_mcp.pages.base_page import BasePage
from google_flow_mcp.config import get_settings


class FlowCharacterPage(BasePage):
    """
    Page Object Model for Character Creation in Google Flow.
    """
    def __init__(self, tab):
        super().__init__(tab)

    def navigate_to_characters(self, project_url: str):
        """Step 1 & 2: Navigate to characters page for a project."""
        logger.info(f"Navigating to project characters page at {project_url}...")
        self.tab.get(project_url)
        time.sleep(4)
        
        char_btn = self.tab.ele('xpath://mat-list-item[.//span[contains(text(), "角色") or contains(text(), "Character")]]', timeout=3)
        if char_btn:
            char_btn.click()
            time.sleep(3)
        else:
            logger.warning("Character button not found in sidebar.")
        logger.info("Character page loaded.")

    def click_new_character(self):
        """Step 3: Click 'New Character' button."""
        logger.info("Clicking 'New Character' button...")
        new_btn = self.tab.ele('xpath://button[contains(., "新角色") or contains(., "新建角色") or contains(., "创建角色") or contains(., "New Character")]', timeout=3)
        if new_btn:
            new_btn.click()
            time.sleep(2.5)
            logger.info("Clicked New Character.")
        else:
            logger.warning("New Character button not found. Checking if editor is ready.")
        
        # Verify editor is ready
        if not self.tab.ele('css:.ProseMirror', timeout=3) and not self.tab.ele('css:textarea', timeout=1):
            logger.error("Editor not found after clicking New Character.")
            return False
        return True

    def _wait_for_generation_complete(self, max_wait=300):
        """Wait for image generation to complete and return the base64 or URL."""
        logger.info("Waiting for generation to complete...")
        
        # 记录初始的图片数量，用于判断是否生成了新图片
        initial_imgs = self.tab.eles('css:img[src*="flow-content.google/image/"]')
        initial_count = len(initial_imgs) if initial_imgs else 0
        
        start_time = time.time()
        while time.time() - start_time < max_wait:
            # Check for error
            err = self.tab.ele('css:.error-message', timeout=0)
            if err and ("失败" in err.text or "failed" in err.text.lower() or "error" in err.text.lower()):
                retry = self.tab.ele('xpath://button[contains(., "重试") or contains(., "Retry") or contains(., "重新生成")]', timeout=0)
                if retry:
                    logger.warning("Generation failed, clicking retry...")
                    retry.click()
                    time.sleep(2)
                    continue
                else:
                    raise Exception(f"Generation failed without retry button: {err.text}")

            # 检查是否有新图片生成
            current_imgs = self.tab.eles('css:img[src*="flow-content.google/image/"]')
            current_count = len(current_imgs) if current_imgs else 0
            
            if current_count > initial_count:
                logger.info("Generation complete! New image detected.")
                # 获取最新生成的图片
                new_img = current_imgs[-1]
                time.sleep(1) # Wait a bit for rendering
                try:
                    base64_data = new_img.get_screenshot(as_base64='png')
                    if base64_data:
                        return base64_data
                except Exception as e:
                    logger.warning(f"Failed to get screenshot: {e}")
                    return new_img.attr('src')
                    
            time.sleep(2)
            
        raise Exception("Timeout waiting for generation.")

    def _safe_input_prompt(self, editor, prompt: str):
        """Safely input text into ProseMirror/textarea without triggering @-mention modals."""
        if editor.tag.lower() == 'textarea':
            editor.run_js("this.value = arguments[0]; this.dispatchEvent(new Event('input', {bubbles: true}));", prompt)
        else:
            js = """
            const dataTransfer = new DataTransfer();
            dataTransfer.setData('text/plain', arguments[0]);
            const event = new ClipboardEvent('paste', {
                clipboardData: dataTransfer,
                bubbles: true,
                cancelable: true
            });
            this.dispatchEvent(event);
            """
            editor.run_js(js, prompt)

    def generate_portrait(self, prompt: str, model_name: str = "Nano banana pro"):
        """Step 4, 5, 6: Generate Portrait."""
        logger.info(f"Generating portrait with model '{model_name}'...")
        
        # 1. Clear editor and enter prompt
        editor = self.tab.ele('css:.ProseMirror', timeout=3)
        if not editor:
            editor = self.tab.ele('css:textarea')
            
        if editor:
            editor.click()
            editor.clear()
            self._safe_input_prompt(editor, prompt)
            time.sleep(1)
            
        # 2. Select Model
        if model_name:
            logger.info(f"Selecting model: {model_name}")
            model_btn = self.tab.ele('css:button.model-select-button, button[aria-label*="模型"], button[aria-label*="model"]', timeout=2)
            if model_btn:
                model_btn.click()
                time.sleep(1)
                
                # Find the specific model option
                lower_model = model_name.lower()
                menu_items = self.tab.eles('css:.mat-mdc-menu-item, .mat-menu-item', timeout=2)
                found_model = False
                for item in menu_items:
                    if lower_model in (item.text or "").lower():
                        item.click()
                        time.sleep(1)
                        found_model = True
                        break
                        
                if not found_model:
                    model_item = self.tab.ele(f'xpath://*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "{lower_model}")]', timeout=1)
                    if model_item:
                        model_item.click()
                        time.sleep(1)
                    else:
                        logger.warning(f"Could not find model '{model_name}', closing menu...")
                        model_btn.click()
                        time.sleep(1)
            else:
                logger.warning("Could not find model selection button.")
            
        # 3. Click Generate
        gen_btn = self.tab.ele('xpath://button[contains(@aria-label, "开始生成") or contains(., "开始生成") or contains(., "Generate") or contains(@class, "generate-icon-button")]', timeout=2)
        if gen_btn:
            gen_btn.click()
            time.sleep(2)
        else:
            raise Exception("Could not find Generate button for portrait.")
            
        # 4. Wait for completion
        return self._wait_for_generation_complete()

    def rename_character(self, name: str):
        """Rename the character after generation."""
        logger.info(f"Renaming character to '{name}'...")
        title_input = self.tab.ele('css:input[aria-label*="名称"], input[aria-label*="Name"]', timeout=3)
        if not title_input:
            title_ele = self.tab.ele('xpath://*[contains(text(), "未命名的角色") or contains(text(), "Untitled")]', timeout=2)
            if title_ele:
                title_ele.click()
                time.sleep(0.5)
            title_input = self.tab.ele('css:input[aria-label*="名称"], input[aria-label*="Name"]', timeout=3)
            
        if title_input:
            title_input.run_js("this.value = ''; this.dispatchEvent(new Event('input', {bubbles: true}));")
            title_input.input(name + '\n')
            time.sleep(1)
        else:
            logger.warning("Could not find character name input field.")

    def configure_voice(self, voice_name: str, voice_style: str):
        """Step 7: Configure voice for the character."""
        if not voice_name:
            return True
            
        logger.info(f"Configuring voice: {voice_name}")
        voice_btn = self.tab.ele('xpath://button[contains(., "选择语音") or contains(., "voice") or contains(@aria-label, "语音") or contains(@aria-label, "voice")]', timeout=3)
        if not voice_btn:
            logger.error("Could not find Voice button.")
            return False
            
        voice_btn.click()
        time.sleep(1.5)
        
        search_input = self.tab.ele('css:input[placeholder*="搜索"], input[placeholder*="Search"]', timeout=2)
        if search_input:
            search_input.input(voice_name)
            time.sleep(1)
            
        # Click the voice item
        voice_item = self.tab.ele(f'xpath://*[contains(text(), "{voice_name}")]', timeout=2)
        if voice_item:
            # Emulate pointer events as per docs
            voice_item.run_js("this.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true})); this.dispatchEvent(new PointerEvent('mousedown', {bubbles: true}));")
            time.sleep(0.1)
            voice_item.run_js("this.dispatchEvent(new PointerEvent('pointerup', {bubbles: true})); this.dispatchEvent(new PointerEvent('mouseup', {bubbles: true}));")
            voice_item.click()
            time.sleep(1)
            
        if voice_style:
            style_input = self.tab.ele('css:textarea[placeholder*="口音"], textarea[placeholder*="accent"]', timeout=1)
            if style_input:
                style_input.input(voice_style)
                time.sleep(0.5)
                
                
        logger.info("Voice configured successfully.")
        return True

    def generate_fullbody(self, character_name: str, prompt: str, model_name: str = "Nano banana pro"):
        """Step 4b & 6: Generate Full Body Image."""
        logger.info("Starting Full Body generation...")
        fullbody_btn = self.tab.ele('xpath://button[contains(., "生成全身像") or contains(., "full body") or contains(., "全身像")]', timeout=3)
        
        if fullbody_btn:
            # Use JS click to avoid element interception issues
            fullbody_btn.click(by_js=True)
            time.sleep(2)
            
        editor = self.tab.ele('css:.ProseMirror', timeout=3)
        if not editor:
            editor = self.tab.ele('css:textarea')
            
        if editor:
            editor.click()
            editor.clear()
            time.sleep(0.5)
            
            # Type the prompt all at once using safe paste
            logger.info("Pasting prompt...")
            self._safe_input_prompt(editor, prompt)
            time.sleep(1)
            
        # Select Model for Fullbody
        if model_name:
            logger.info(f"Selecting model: {model_name} for fullbody")
            model_btn = self.tab.ele('css:button.model-select-button, button[aria-label*="模型"], button[aria-label*="model"]', timeout=2)
            if model_btn:
                model_btn.click()
                time.sleep(1)
                
                lower_model = model_name.lower()
                menu_items = self.tab.eles('css:.mat-mdc-menu-item, .mat-menu-item', timeout=2)
                found_model = False
                for item in menu_items:
                    if lower_model in (item.text or "").lower():
                        item.click()
                        time.sleep(1)
                        found_model = True
                        break
                        
                if not found_model:
                    model_item = self.tab.ele(f'xpath://*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "{lower_model}")]', timeout=1)
                    if model_item:
                        model_item.click()
                        time.sleep(1)
                    else:
                        logger.warning(f"Could not find model '{model_name}', closing menu...")
                        model_btn.click()
                        time.sleep(1)
            else:
                logger.warning("Could not find model selection button.")
            
        gen_btn = self.tab.ele('xpath://button[contains(@aria-label, "开始生成") or contains(., "开始生成") or contains(., "Generate") or contains(@class, "generate-icon-button")]', timeout=2)
        if gen_btn:
            gen_btn.click()
            time.sleep(2)
            
        return self._wait_for_generation_complete()

    def upload_portrait(self, portrait_path: str, timeout: int = 30) -> bool:
        """
        Upload character portrait image file.
        Uses DrissionPage CDP file chooser interception to avoid OS native file dialogs.
        Handles agreement dialog ('我同意，不再显示') and waits for upload completion
        (detected via '//button[@aria-label="下载图片"]').
        """
        path_obj = Path(portrait_path)
        if not path_obj.is_file():
            raise FileNotFoundError(f"Portrait image file not found: {portrait_path}")

        abs_path = str(path_obj.resolve())
        logger.info(f"Initiating portrait upload for file: {abs_path}")

        # Set file to be uploaded via CDP interception before clicking button
        self.tab.set.upload_files(abs_path)

        # Locate and click the upload button: //span[text()="上传"]
        upload_btn = self.tab.ele('xpath://span[text()="上传"]', timeout=5)
        if not upload_btn:
            upload_btn = self.tab.ele('xpath://button[contains(., "上传")] | //span[contains(text(), "上传")]', timeout=2)
        if not upload_btn:
            raise Exception("Could not find portrait Upload button (//span[text()='上传']).")

        try:
            upload_btn.click()
        except Exception as e:
            logger.warning(f"Direct click on portrait upload button failed: {e}, attempting JS click...")
            upload_btn.click(by_js=True)

        logger.info(f"Waiting up to {timeout}s for portrait upload to complete...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Check for agreement popup ('此视频的使用权' dialog: //span[text()="我同意，不再显示"])
            agree_btn = self.tab.ele('xpath://span[text()="我同意，不再显示"]', timeout=0)
            if not agree_btn:
                agree_btn = self.tab.ele('xpath://button[contains(., "我同意") or .//span[contains(text(), "我同意")]]', timeout=0)
            if agree_btn:
                logger.info("Detected agreement dialog, clicking '我同意，不再显示'...")
                try:
                    agree_btn.click()
                except Exception:
                    agree_btn.click(by_js=True)
                time.sleep(1)

            # Check if download button appears indicating upload completed
            dl_btn = self.tab.ele('xpath://button[@aria-label="下载图片"]', timeout=0.5)
            if dl_btn:
                logger.info("Portrait upload completed successfully! Download button detected.")
                time.sleep(1)
                return True

            time.sleep(1)

        raise TimeoutError(f"Timeout ({timeout}s) waiting for portrait upload completion (download button not found).")

    def upload_fullbody(self, fullbody_path: str, timeout: int = 30) -> bool:
        """
        Upload character fullbody image file.
        Clicks Fullbody tab/button, intercepts file chooser dialog,
        handles agreement dialog, and waits for upload completion.
        """
        path_obj = Path(fullbody_path)
        if not path_obj.is_file():
            raise FileNotFoundError(f"Fullbody image file not found: {fullbody_path}")

        abs_path = str(path_obj.resolve())
        logger.info(f"Initiating fullbody upload for file: {abs_path}")

        # Step 5: Click Fullbody button/tab
        logger.info("Clicking Fullbody button/tab...")
        fullbody_btn = self.tab.ele('xpath://button[contains(., "全身像") or contains(., "full body")] | //span[contains(text(), "全身像")]', timeout=5)
        if fullbody_btn:
            try:
                fullbody_btn.click(by_js=True)
            except Exception as e:
                logger.warning(f"JS click on fullbody button failed: {e}, attempting regular click...")
                fullbody_btn.click()
            time.sleep(1.5)
        else:
            logger.warning("Could not find Fullbody button/tab. Continuing to look for fullbody upload button...")

        # Count existing download buttons prior to fullbody upload
        existing_dl_btns = self.tab.eles('xpath://button[@aria-label="下载图片"]')
        initial_dl_count = len(existing_dl_btns) if existing_dl_btns else 0

        # Set upload file via CDP interception
        self.tab.set.upload_files(abs_path)

        # Step 6: Locate and click Upload button in fullbody area
        upload_btn = self.tab.ele('xpath://span[text()="上传"] | //span[contains(text(), "上传")]', timeout=5)
        if not upload_btn:
            upload_btn = self.tab.ele('xpath://button[contains(., "上传")]', timeout=2)
        if not upload_btn:
            raise Exception("Could not find fullbody Upload button (//span[contains(text(), '上传')]).")

        try:
            upload_btn.click()
        except Exception as e:
            logger.warning(f"Direct click on fullbody upload button failed: {e}, attempting JS click...")
            upload_btn.click(by_js=True)

        logger.info(f"Waiting up to {timeout}s for fullbody upload to complete...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Check for agreement popup
            agree_btn = self.tab.ele('xpath://span[text()="我同意，不再显示"]', timeout=0)
            if not agree_btn:
                agree_btn = self.tab.ele('xpath://button[contains(., "我同意") or .//span[contains(text(), "我同意")]]', timeout=0)
            if agree_btn:
                logger.info("Detected agreement dialog, clicking '我同意，不再显示'...")
                try:
                    agree_btn.click()
                except Exception:
                    agree_btn.click(by_js=True)
                time.sleep(1)

            # Check if a new download button appeared, or if at least one exists
            current_dl_btns = self.tab.eles('xpath://button[@aria-label="下载图片"]')
            current_dl_count = len(current_dl_btns) if current_dl_btns else 0
            if current_dl_count > initial_dl_count or (initial_dl_count == 0 and current_dl_count > 0):
                logger.info("Fullbody upload completed successfully! Download button detected.")
                time.sleep(1)
                return True

            time.sleep(1)

        raise TimeoutError(f"Timeout ({timeout}s) waiting for fullbody upload completion.")

    def download_character_image(self, target_stem: str, timeout: int = 60) -> str | None:
        """
        Click the download image button (//button[@aria-label="下载图片"]),
        wait for the downloaded file (starts with '图片'),
        and rename it to f"{target_stem}{ext}", overwriting if already exists.

        Args:
            target_stem: Target filename without extension (e.g. "Alice_Portrait" or "Alice_Fullbody").
            timeout: Maximum seconds to wait for download to finish.

        Returns:
            The absolute path of the renamed file as a string, or None if failed or timed out.
        """
        settings = get_settings()
        download_dir_str = settings.chrome_download_dir
        if download_dir_str:
            download_path = Path(download_dir_str)
        else:
            download_path = Path.home() / "Downloads"

        try:
            download_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Failed to ensure download directory {download_path}: {e}")

        try:
            existing_files = set(download_path.iterdir())
        except Exception as e:
            logger.warning(f"Failed to list files in download directory {download_path}: {e}")
            existing_files = set()

        start_time = time.time()
        logger.info(f"Initiating character image download for '{target_stem}' into {download_path}...")

        # 1. Locate and click download button: //button[@aria-label="下载图片"]
        download_btn = self.tab.ele('xpath://button[@aria-label="下载图片"]', timeout=5)
        if not download_btn:
            logger.warning("Download button (//button[@aria-label='下载图片']) not found!")
            return None

        try:
            download_btn.click()
            time.sleep(1)
        except Exception as e:
            logger.warning(f"Direct click on download button failed: {e}, attempting JS click...")
            try:
                download_btn.click(by_js=True)
                time.sleep(1)
            except Exception as e2:
                logger.error(f"JS click on download button failed: {e2}")
                return None

        # 2. Wait for downloaded file to appear
        logger.info(f"Waiting up to {timeout}s for downloaded image starting with '图片' in {download_path}...")
        poll_interval = 1
        downloaded_file = None

        while time.time() - start_time < timeout:
            time.sleep(poll_interval)
            try:
                current_files = list(download_path.iterdir())
            except Exception as e:
                logger.warning(f"Error scanning download directory: {e}")
                continue

            for file in current_files:
                if not file.is_file():
                    continue

                fname = file.name
                if fname.endswith('.crdownload') or fname.endswith('.tmp'):
                    continue

                if not fname.startswith("图片"):
                    continue

                if file not in existing_files:
                    try:
                        if file.stat().st_size > 0:
                            downloaded_file = file
                            break
                    except Exception:
                        pass
                else:
                    try:
                        stat = file.stat()
                        if stat.st_mtime >= start_time - 1 and stat.st_size > 0:
                            downloaded_file = file
                            break
                    except Exception:
                        pass

            if downloaded_file:
                break

        if not downloaded_file:
            logger.warning(f"Download timed out after {timeout}s waiting for file starting with '图片'")
            return None

        # 3. Rename to target_stem + ext (overwriting if target exists)
        ext = downloaded_file.suffix or ".png"
        target_file = download_path / f"{target_stem}{ext}"
        try:
            if target_file.exists():
                target_file.unlink()
            downloaded_file.rename(target_file)
            logger.info(f"Character image downloaded and renamed successfully: {target_file.resolve()}")
            return str(target_file.resolve())
        except Exception as e:
            logger.warning(f"Failed to rename downloaded file {downloaded_file} directly: {e}, falling back to shutil.move")
            try:
                if target_file.exists():
                    target_file.unlink()
                shutil.move(str(downloaded_file), str(target_file))
                logger.info(f"Character image moved successfully via shutil: {target_file.resolve()}")
                return str(target_file.resolve())
            except Exception as e2:
                logger.error(f"shutil.move also failed: {e2}")
                return str(downloaded_file.resolve())

    def save_character(self):
        """Step 8: Save character (Click Done)."""
        logger.info("Saving character...")
        done_btn = self.tab.ele('xpath://button[contains(., "完成") or contains(., "Done") or contains(., "保存")]', timeout=3)
        if done_btn:
            done_btn.click()
            time.sleep(2)
            logger.info("Character saved successfully.")
            return True
        logger.warning("Could not find Done/Save button.")
        return False

    def list_characters(self, project_url: str = "") -> list:
        """
        List all characters in the current or specified project.
        - If project_url is provided, navigates to the project if not already there.
        - Locates sidebar button: //mat-list-item//span[text()="角色"]
        - If button does not exist, returns empty list (indicating no characters).
        - If button exists, clicks it to enter characters view and extracts all //flow-character-tile.
        """
        logger.info(f"Listing characters (project_url='{project_url}')...")
        if project_url:
            current_url = self.tab.url or ""
            if project_url not in current_url:
                logger.info(f"Navigating to project url ({project_url})...")
                self.tab.get(project_url)
                time.sleep(3)

        # Check if we need to click the '角色' (Characters) tab/button
        current_url = self.tab.url or ""
        # If already on character page or character tile is present, we might already be on the page
        has_tiles = self.tab.ele('xpath://div[@class="character-tile-container"]', timeout=1) or \
                    self.tab.ele('xpath://div[contains(@class, "character-tile-container")]', timeout=0)
        
        if not has_tiles and not current_url.endswith("/character"):
            logger.info("Looking for '角色' button in sidebar/navigation...")
            # Try exact xpath first
            char_btn = self.tab.ele('xpath://mat-list-item//span[text()="角色"]', timeout=2)
            if not char_btn:
                # Fallback to broader match
                char_btn = self.tab.ele('xpath://mat-list-item[.//span[contains(text(), "角色") or contains(text(), "Character")]]', timeout=2)
            if not char_btn:
                # Direct span or button fallback
                char_btn = self.tab.ele('xpath://button[contains(., "角色") or contains(., "Character")]', timeout=1)

            if char_btn:
                logger.info("Clicking '角色' button...")
                char_btn.click()
                time.sleep(2)
            else:
                logger.warning("Character navigation button not found; attempting to check current page directly.")

        # Wait briefly for character tiles or empty list to appear
        self.tab.ele('xpath://div[contains(@class, "character-tile-container")]', timeout=3)
        
        tiles = self.tab.eles('xpath://div[@class="character-tile-container"]')
        if not tiles:
            tiles = self.tab.eles('xpath://div[contains(@class, "character-tile-container")]')

        characters = []
        for idx, tile in enumerate(tiles):
            # Name: xpath //div[@class="character-tile-container"]/span
            name_ele = tile.ele('xpath:.//span', timeout=0)
            name = name_ele.text.strip() if name_ele else ""
            if not name:
                name = tile.text.strip()

            # Thumbnail
            img_ele = tile.ele('css:img', timeout=0)
            thumbnail_url = img_ele.attr('src') if img_ele else ""

            char_info = {
                "index": idx + 1,
                "name": name,
                "thumbnail_url": thumbnail_url
            }
            characters.append(char_info)

        logger.info(f"Found {len(characters)} characters in project.")
        return characters
