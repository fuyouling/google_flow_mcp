import time
from pathlib import Path
from loguru import logger
from google_flow_mcp.pages.base_page import BasePage


class FlowVideoPage(BasePage):
    """
    Page Object Model for Video management in Google Flow.
    """

    def list_videos(self, project_url: str = "") -> list:
        """
        List all videos in the current or specified project.
        - If project_url is provided, navigates to the project if not already there.
        - Locates sidebar button: //mat-list-item//span[text()="视频"]
        - If button does not exist, returns empty list (indicating no videos).
        - If button exists, clicks it to enter videos view and extracts all //flow-video-tile.
        - Video name extracted from: //flow-video-tile//flow-tile-hover-footer/div/span
        """
        logger.info(f"Listing videos (project_url='{project_url}')...")
        if project_url:
            current_url = self.tab.url or ""
            if project_url not in current_url:
                logger.info(f"Navigating to project url ({project_url})...")
                self.tab.get(project_url)
                time.sleep(3)

        # Check if already showing video tiles
        has_tiles = self.tab.ele('xpath://flow-video-tile', timeout=1) or \
                    self.tab.ele('xpath://*[contains(@class, "flow-video-tile")]', timeout=0)

        current_url = self.tab.url or ""
        if not has_tiles and not current_url.endswith("/videos"):
            logger.info("Looking for '视频' button in sidebar/navigation...")
            # User specified exact xpath: //mat-list-item//span[text()="视频"]
            video_btn = self.tab.ele('xpath://mat-list-item//span[text()="视频"]', timeout=2)
            if not video_btn:
                # English UI fallback
                video_btn = self.tab.ele('xpath://mat-list-item[.//span[contains(text(), "视频") or text()="Videos" or text()="Video"]]', timeout=1)

            if not video_btn:
                logger.info("No '视频' navigation button found on page. Project has no videos.")
                return []

            logger.info("Found '视频' button, clicking...")
            video_btn.click()
            time.sleep(2)

        # Wait briefly for tiles to load
        self.tab.ele('xpath://flow-video-tile', timeout=3)
        tiles = self.tab.eles('xpath://flow-video-tile')
        if not tiles:
            tiles = self.tab.eles('xpath://*[contains(@class, "flow-video-tile")]')

        videos = []
        for idx, tile in enumerate(tiles):
            # User specified: xpath //flow-video-tile//flow-tile-hover-footer/div/span
            name_ele = tile.ele('xpath:.//flow-tile-hover-footer/div/span', timeout=0)
            if not name_ele:
                # Fallback to span inside footer or direct span
                name_ele = tile.ele('xpath:.//flow-tile-hover-footer//span', timeout=0) or tile.ele('xpath:.//span', timeout=0)
            name = name_ele.text.strip() if name_ele else ""
            if not name:
                name = tile.text.strip()

            # Thumbnail / preview video or img url
            img_ele = tile.ele('css:img', timeout=0)
            thumbnail_url = img_ele.attr('src') if img_ele else ""
            if not thumbnail_url:
                vid_ele = tile.ele('css:video', timeout=0)
                thumbnail_url = vid_ele.attr('src') if vid_ele else ""

            # Extract any media link if present
            media_link = tile.ele('css:a', timeout=0)
            media_href = media_link.attr('href') if media_link else ""

            vid_info = {
                "index": idx + 1,
                "name": name,
                "thumbnail_url": thumbnail_url
            }
            if media_href:
                vid_info["href"] = media_href

            videos.append(vid_info)

        logger.info(f"Found {len(videos)} videos in project.")
        return videos

    def upload_video_on_project_page(self, project_url: str, video_path: str, timeout: int = 60) -> bool:
        """
        Upload a video file from the project home page:
        1. Navigate to project page: {project_url}
        2. Click button: //button[@mattooltip="添加媒体"]
        3. Set file upload via CDP interception: self.tab.set.upload_files(abs_path)
        4. Click button: //span[text()="上传"]
        5. Poll and auto-click agreement dialog if present: //span[text()="我同意，不再显示"]
        6. Wait until (//flow-grid-tile-container)[1]//span contains the video file name / stem.
        7. Click (//flow-grid-tile-container)[1] to enter the video details interface.
        """
        path_obj = Path(video_path)
        if not path_obj.is_file():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        abs_path = str(path_obj.resolve())
        file_stem = path_obj.stem
        file_name = path_obj.name

        # 1. Navigate to project
        current_url = self.tab.url or ""
        if project_url not in current_url:
            logger.info(f"Navigating to project url ({project_url})...")
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
        logger.info(f"Waiting up to {timeout}s for video upload completion (checking (//flow-grid-tile-container)[1]//span)...")
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
            raise TimeoutError(f"Timeout ({timeout}s) waiting for uploaded video tile to appear.")

        # 5. Click first tile to enter details/edit interface
        logger.info("Clicking uploaded video tile to enter details page...")
        time.sleep(0.5)
        try:
            uploaded_tile.click()
        except Exception as e:
            logger.warning(f"Direct click on tile failed: {e}, trying JS click...")
            uploaded_tile.click(by_js=True)
        time.sleep(0.5)
        return True

    def rename_and_save_in_detail(self, new_name: str, timeout: int = 15) -> bool:
        """
        Rename the video in the detail/edit interface and press Enter to auto-save.
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

        logger.info(f"Video successfully renamed to '{new_name}' in detail view.")
        return True
