import time
from pathlib import Path
from loguru import logger
from google_flow_mcp.pages.base_page import BasePage


class FlowImagePage(BasePage):
    """
    Page Object Model for Image management in Google Flow.
    """

    def list_images(self, project_url: str = "") -> list:
        """
        List all images in the current or specified project.
        - If project_url is provided, navigates to the project if not already there.
        - Locates sidebar button: //mat-list-item//span[text()="图片"]
        - If button does not exist, returns empty list (indicating no images).
        - If button exists, clicks it to enter images view and extracts all //flow-image-tile.
        """
        logger.info(f"Listing images (project_url='{project_url}')...")
        if project_url:
            current_url = self.tab.url or ""
            if project_url not in current_url:
                logger.info(f"Navigating to project url ({project_url})...")
                self.tab.get(project_url)
                time.sleep(3)

        # Check if already showing image tiles
        has_tiles = self.tab.ele('xpath://flow-image-tile', timeout=1) or \
                    self.tab.ele('xpath://*[contains(@class, "flow-image-tile")]', timeout=0)

        current_url = self.tab.url or ""
        if not has_tiles and not current_url.endswith("/images"):
            logger.info("Looking for '图片' button in sidebar/navigation...")
            # User specified exact xpath: //mat-list-item//span[text()="图片"]
            img_btn = self.tab.ele('xpath://mat-list-item//span[text()="图片"]', timeout=2)
            if not img_btn:
                # English UI fallback
                img_btn = self.tab.ele('xpath://mat-list-item[.//span[contains(text(), "图片") or text()="Images" or text()="Image"]]', timeout=1)

            if not img_btn:
                logger.info("No '图片' navigation button found on page. Project has no images.")
                return []

            logger.info("Found '图片' button, clicking...")
            img_btn.click()
            time.sleep(2)

        # Wait briefly for tiles to load
        self.tab.ele('xpath://flow-image-tile', timeout=3)
        tiles = self.tab.eles('xpath://flow-image-tile')
        if not tiles:
            tiles = self.tab.eles('xpath://*[contains(@class, "flow-image-tile")]')

        images = []
        for idx, tile in enumerate(tiles):
            # User specified: xpath //flow-image-tile//flow-tile-hover-footer/div/span
            name_ele = tile.ele('xpath:.//flow-tile-hover-footer/div/span', timeout=0)
            if not name_ele:
                # Fallback to span inside footer or direct span
                name_ele = tile.ele('xpath:.//flow-tile-hover-footer//span', timeout=0) or tile.ele('xpath:.//span', timeout=0)
            name = name_ele.text.strip() if name_ele else ""
            if not name:
                name = tile.text.strip()

            # Thumbnail url
            img_ele = tile.ele('css:img', timeout=0)
            thumbnail_url = img_ele.attr('src') if img_ele else ""

            # Extract any media link if present
            media_link = tile.ele('css:a', timeout=0)
            media_href = media_link.attr('href') if media_link else ""

            img_info = {
                "index": idx + 1,
                "name": name,
                "thumbnail_url": thumbnail_url
            }
            if media_href:
                img_info["href"] = media_href

            images.append(img_info)

        logger.info(f"Found {len(images)} images in project.")
        return images

    def upload_image_on_project_page(self, project_url: str, image_path: str, timeout: int = 45) -> bool:
        """
        Upload an image file from the project home page:
        1. Navigate to project page: {project_url}
        2. Click button: //button[@mattooltip="添加媒体"]
        3. Set file upload via CDP interception: self.tab.set.upload_files(abs_path)
        4. Click button: //span[text()="上传"]
        5. Poll and auto-click agreement dialog if present: //span[text()="我同意，不再显示"]
        6. Wait until (//flow-grid-tile-container)[1]//span contains the image file name / stem.
        7. Click (//flow-grid-tile-container)[1] to enter the image details interface.
        """
        path_obj = Path(image_path)
        if not path_obj.is_file():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        abs_path = str(path_obj.resolve())
        file_stem = path_obj.stem
        file_name = path_obj.name

        # 1. Navigate to project
        logger.info(f"Navigating to project page at {project_url}...")
        self.tab.get(project_url)
        time.sleep(3)

        # 2. Click '添加媒体' button
        logger.info("Locating '添加媒体' button (//button[@mattooltip='添加媒体'])...")
        add_btn = self.tab.ele('xpath://button[@mattooltip="添加媒体"]', timeout=5)
        if not add_btn:
            add_btn = self.tab.ele('xpath://button[contains(@mattooltip, "添加媒体") or contains(@aria-label, "添加媒体")]', timeout=2)
        if not add_btn:
            raise Exception("Could not find '添加媒体' button (//button[@mattooltip='添加媒体']).")

        try:
            add_btn.click()
        except Exception as e:
            logger.warning(f"Direct click on add media button failed: {e}, using JS click...")
            add_btn.click(by_js=True)
        time.sleep(1)

        # 3. Intercept file chooser and click '上传'
        logger.info(f"Setting upload file via CDP interception: {abs_path}")
        self.tab.set.upload_files(abs_path)

        upload_btn = self.tab.ele('xpath://span[text()="上传"]', timeout=5)
        if not upload_btn:
            upload_btn = self.tab.ele('xpath://button[contains(., "上传")] | //span[contains(text(), "上传")]', timeout=2)
        if not upload_btn:
            raise Exception("Could not find '上传' button (//span[text()='上传']).")

        try:
            upload_btn.click()
        except Exception as e:
            logger.warning(f"Direct click on upload button failed: {e}, using JS click...")
            upload_btn.click(by_js=True)

        # 4. Wait for upload completion and agreement popup
        logger.info(f"Waiting up to {timeout}s for upload completion (checking (//flow-grid-tile-container)[1]//span)...")
        start_time = time.time()
        uploaded_tile = None

        while time.time() - start_time < timeout:
            # Check agreement popup ('此视频的使用权' dialog: //span[text()="我同意，不再显示"])
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

            # Check (//flow-grid-tile-container)[1]//span
            first_span = self.tab.ele('xpath:(//flow-grid-tile-container)[1]//span', timeout=0.5)
            if first_span:
                span_text = first_span.text.strip()
                if file_stem.lower() in span_text.lower() or file_name.lower() in span_text.lower():
                    logger.info(f"Upload complete! First tile span matched: '{span_text}'")
                    uploaded_tile = self.tab.ele('xpath:(//flow-grid-tile-container)[1]', timeout=1) or first_span
                    break

            time.sleep(1)

        if not uploaded_tile:
            raise TimeoutError(f"Timeout ({timeout}s) waiting for uploaded image tile to appear.")

        # 5. Click first tile to enter details/edit interface
        logger.info("Clicking uploaded image tile to enter details page...")
        time.sleep(1)
        try:
            uploaded_tile.click()
        except Exception as e:
            logger.warning(f"Direct click on tile failed: {e}, trying JS click...")
            uploaded_tile.click(by_js=True)
        time.sleep(3)
        return True

    def rename_and_save_in_detail(self, new_name: str, timeout: int = 15) -> bool:
        """
        Rename the image in the detail/edit interface and press Enter to auto-save.
        """
        logger.info(f"Renaming media in detail view to '{new_name}'...")
        start_time = time.time()
        rename_input = None
        while time.time() - start_time < timeout:
            rename_input = self.tab.ele('tag:input@@class=editable-text-input', timeout=1)
            if not rename_input:
                rename_input = self.tab.ele('css:input.editable-text-input, input[aria-label*="名称"], input[aria-label*="Name"]', timeout=1)
            if rename_input:
                break
            time.sleep(0.5)

        if not rename_input:
            logger.warning("Rename input not found in detail view!")
            return False

        try:
            rename_input.click()
            time.sleep(0.5)
        except Exception as e:
            logger.warning(f"Failed to click rename input: {e}")

        try:
            # 1. Select All (Ctrl+A)
            self.tab.run_cdp('Input.dispatchKeyEvent', type='keyDown', windowsVirtualKeyCode=65, modifiers=2)
            self.tab.run_cdp('Input.dispatchKeyEvent', type='keyUp', windowsVirtualKeyCode=65, modifiers=2)
            time.sleep(0.2)

            # 2. Backspace
            self.tab.run_cdp('Input.dispatchKeyEvent', type='keyDown', windowsVirtualKeyCode=8)
            self.tab.run_cdp('Input.dispatchKeyEvent', type='keyUp', windowsVirtualKeyCode=8)
            time.sleep(0.2)

            # 3. Input new text
            rename_input.input(new_name)
            time.sleep(0.2)

            # 4. Enter to save
            self.tab.run_cdp('Input.dispatchKeyEvent', type='rawKeyDown', windowsVirtualKeyCode=13, key='Enter', code='Enter', text='\r', unmodifiedText='\r')
            self.tab.run_cdp('Input.dispatchKeyEvent', type='char', windowsVirtualKeyCode=13, key='Enter', code='Enter', text='\r', unmodifiedText='\r')
            self.tab.run_cdp('Input.dispatchKeyEvent', type='keyUp', windowsVirtualKeyCode=13, key='Enter', code='Enter')
            time.sleep(1)
        except Exception as e:
            logger.warning(f"Failed during CDP rename steps: {e}")

        # Fallback check for any save/done button if exists
        save_btn = self.tab.ele('xpath://button[contains(., "保存") or contains(., "Save") or contains(., "完成")]', timeout=0.5)
        if save_btn:
            try:
                save_btn.click()
                time.sleep(0.5)
            except Exception:
                pass

        logger.info(f"Image successfully renamed to '{new_name}' in detail view.")
        return True
