from loguru import logger
from DrissionPage import ChromiumPage
from DrissionPage.common import Keys
from google_flow_mcp.pages.base_page import BasePage
import time
import base64

class FlowCharacterPage(BasePage):
    """
    Page Object Model for Character Creation in Google Flow.
    """
    def __init__(self, tab):
        super().__init__(tab)

    def navigate_to_characters(self, project_id: str):
        """Step 1 & 2: Navigate to characters page for a project."""
        logger.info(f"Navigating to project {project_id} characters page...")
        project_url = f"https://flow.google.com/project/{project_id}"
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
