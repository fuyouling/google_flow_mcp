from loguru import logger
from google_flow_mcp.pages.base_page import BasePage
import time

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

    def save_and_close(self):
        """Click the Done/Save button to close the edit view."""
        logger.info("Attempting to click Done/Save button")
        done_btn = self.tab.ele('xpath://button[@aria-label="完成修改"]', timeout=5)
        if done_btn:
            done_btn.click()
            time.sleep(1)
        else:
            logger.warning("Done/Save button not found.")
