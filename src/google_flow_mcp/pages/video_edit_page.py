import time
from pathlib import Path
from loguru import logger
from google_flow_mcp.pages.base_page import BasePage
from google_flow_mcp.config import get_settings

class VideoEditPage(BasePage):
    """
    Page Object Model for the video edit interface in Google Flow.
    URL pattern: https://flow.google.com/project/{project_id}/edit/{media_id}
    """
    
    def open(self, project_id: str, media_id: str):
        """Open the specific media edit page."""
        url = f"https://flow.google.com/project/{project_id}/edit/{media_id}"
        logger.info(f"Navigating to Video Edit Page: {url}")
        self.tab.get(url)
        # Wait 5s for page initial render before polling
        logger.info("Waiting 5s for page initial render...")
        time.sleep(5)
        logger.info("Video Edit Page loaded.")




    def rename(self, new_name: str) -> bool:
        """Rename the media."""
        logger.info(f"Attempting to rename media to '{new_name}' via CDP")
        rename_input = self.tab.ele('tag:input@@class=editable-text-input', timeout=5)
        
        if not rename_input:
            logger.warning("Rename input not found!")
            return False
            
        # Click to focus
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
            
            # 4. Enter
            self.tab.run_cdp('Input.dispatchKeyEvent', type='rawKeyDown', windowsVirtualKeyCode=13, key='Enter', code='Enter', text='\r', unmodifiedText='\r')
            self.tab.run_cdp('Input.dispatchKeyEvent', type='char', windowsVirtualKeyCode=13, key='Enter', code='Enter', text='\r', unmodifiedText='\r')
            self.tab.run_cdp('Input.dispatchKeyEvent', type='keyUp', windowsVirtualKeyCode=13, key='Enter', code='Enter')
            time.sleep(1)
            
        except Exception as e:
            logger.warning(f"Failed during CDP rename steps: {e}")
            
        final_val = rename_input.property('value')
        return final_val == new_name

    def download_video(self, resolution: str = "720p", expected_prefix: str = "", timeout: int = 120) -> str | None:
        """
        Download the video in specified resolution ('270p', '720p', or '1080p') and wait for completion.

        Args:
            resolution: Target resolution, strictly '270p', '720p', or '1080p'.
            expected_prefix: The prefix of the file name (usually the renamed video title).
            timeout: Max seconds to wait for download to complete.

        Returns:
            The absolute path of the downloaded file as a string, or None if failed or timed out.
        """
        resolution = resolution.strip().lower()
        if resolution not in ("270p", "720p", "1080p"):
            logger.warning(f"Unsupported download resolution: {resolution}. Only '270p', '720p', and '1080p' are allowed.")
            return None

        settings = get_settings()
        download_dir_str = settings.chrome_download_dir
        if not download_dir_str:
            logger.warning("CHROME_DOWNLOAD_DIR is not configured in settings!")
            return None

        download_path = Path(download_dir_str)
        download_path.mkdir(parents=True, exist_ok=True)

        existing_files = set(download_path.iterdir())
        start_time = time.time()

        logger.info(f"Initiating {resolution} video download, expected prefix: {expected_prefix!r}")

        # 1. Click download button: //button[@aria-label="下载媒体内容"]
        download_btn = self.tab.ele('xpath://button[@aria-label="下载媒体内容"]', timeout=5)
        if not download_btn:
            logger.warning("Download button (//button[@aria-label='下载媒体内容']) not found on edit page!")
            return None

        try:
            download_btn.click()
            time.sleep(1)
        except Exception as e:
            logger.warning(f"Failed to click download button: {e}")
            try:
                download_btn.click(by_js=True)
                time.sleep(1)
            except Exception as e2:
                logger.error(f"Failed to click download button via JS: {e2}")
                return None

        # 2. Click resolution button: //span[text()="{resolution}"]
        res_btn = self.tab.ele(f'xpath://span[text()="{resolution}"]', timeout=5)
        if not res_btn:
            res_btn = self.tab.ele(f'xpath://button[contains(., "{resolution}")]', timeout=2)

        if not res_btn:
            logger.warning(f"Resolution button for '{resolution}' not found!")
            return None

        try:
            res_btn.click()
            logger.info(f"Clicked resolution option: {resolution}")
        except Exception as e:
            logger.warning(f"Failed to click resolution button: {e}")
            try:
                res_btn.click(by_js=True)
                logger.info(f"Clicked resolution option via JS: {resolution}")
            except Exception as e2:
                logger.error(f"Failed to click resolution button via JS: {e2}")
                return None

        # 3. Wait for file download to complete
        logger.info(f"Waiting up to {timeout}s for video file starting with '{expected_prefix}' in {download_path}...")
        poll_interval = 2
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
                matches_prefix = fname.startswith(expected_prefix) if expected_prefix else True
                if not matches_prefix:
                    continue

                # Ignore unfinished temporary download files
                if fname.endswith('.crdownload') or fname.endswith('.tmp'):
                    continue

                # Ensure it's a new or updated file with content
                if file not in existing_files:
                    try:
                        if file.stat().st_size > 0:
                            logger.info(f"Video download complete: {file.resolve()}")
                            return str(file.resolve())
                    except Exception:
                        pass
                else:
                    try:
                        stat = file.stat()
                        if stat.st_mtime >= start_time - 1 and stat.st_size > 0:
                            logger.info(f"Video download complete (updated file): {file.resolve()}")
                            return str(file.resolve())
                    except Exception:
                        pass

        logger.warning(f"Video download timed out after {timeout}s waiting for file with prefix '{expected_prefix}'")
        return None

    def save_and_close(self):
        """Click the Done/Save button to close the edit view."""
        logger.info("Attempting to click Done/Save button")
        done_btn = self.tab.ele('xpath://button[@aria-label="完成场景编辑"]', timeout=5)
        if done_btn:
            done_btn.click()
            time.sleep(1)
        else:
            logger.warning("Done/Save button not found.")
