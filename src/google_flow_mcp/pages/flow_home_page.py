from loguru import logger
from DrissionPage import ChromiumPage
from DrissionPage.common import Keys
from google_flow_mcp.pages.base_page import BasePage
from google_flow_mcp.models.project_cache import ProjectCache
import re

class FlowHomePage(BasePage):
    """
    Page Object Model for the Google Flow home page (https://flow.google.com).
    Handles i18n-friendly element locating.
    """
    URL = "https://flow.google.com"

    def dismiss_modals(self):
        """Attempt to dismiss any blocking modals/dialogs."""
        logger.info("Checking for blocking modals...")
        try:
            # Try looking for the '开始使用' / 'Get started' button
            btn = self.tab.ele('xpath://button[contains(., "开始使用") or contains(., "Get started") or contains(., "Got it") or contains(., "Close") or contains(., "关闭")]', timeout=2)
            if btn and btn.is_displayed:
                logger.info("Found a promotional modal button, clicking it...")
                btn.click()
                import time
                time.sleep(1) # wait for animation
        except Exception as e:
            logger.warning(f"Error while dismissing modals: {e}")

    def open(self):
        """Open the home page and wait for it to load."""
        logger.info("Navigating to Flow Home Page...")
        self.tab.get(self.URL)
        # Wait for either projects or the promotion banner/new project button
        self.tab.ele('css:flow-project-card, button.new-project-button', timeout=15)
        
        self.dismiss_modals()
        logger.info("Flow Home Page loaded.")

    def get_projects(self) -> dict:
        """
        Extract all project cards and save them to ProjectCache.
        Returns the parsed dictionary.
        """
        logger.info("Extracting project list...")
        cards = self.tab.eles('css:flow-project-card')
        result = {}
        for card in cards:
            link_ele = card.ele('css:a.project-thumbnail-container')
            title_div = card.ele('css:div.project-title-label')
            if not link_ele or not title_div:
                continue
                
            href = link_ele.attr('href')
            project_id = href.split('/')[-1] if href else ""
            
            # The title text might include the icon text if we just call .text
            # We want just the raw text node of the div, or we can replace the button text
            full_text = title_div.text
            btn_ele = title_div.ele('css:button', timeout=0)
            btn_text = btn_ele.text if btn_ele else ""
            
            title = full_text.replace(btn_text, '').strip() if btn_text else full_text.strip()
            if not title:
                title = full_text.strip()
                
            if project_id and title:
                ProjectCache.update_project(project_id, title, href)
                result[project_id] = {"name": title, "url": href}
                
        logger.info(f"Extracted {len(result)} projects.")
        return result

    def rename_project(self, project_id: str, old_title: str, new_title: str) -> bool:
        """
        Rename a project by its old title (or id if we have a robust way).
        Using old_title to find the specific card.
        """
        logger.info(f"Attempting to rename project from '{old_title}' to '{new_title}'...")
        cards = self.tab.eles('css:flow-project-card')
        target_card = None
        for card in cards:
            title_div = card.ele('css:div.project-title-label')
            if title_div and old_title in title_div.text:
                target_card = card
                break
                
        if not target_card:
            logger.error(f"Card for project '{old_title}' not found.")
            return False
            
        # Click the edit button nested in the title div
        title_div = target_card.ele('css:div.project-title-label')
        edit_btn = title_div.ele('css:button')
        if edit_btn:
            # use normal click to ensure Angular click listener captures it properly
            edit_btn.click()
        else:
            logger.error("Edit button not found in project card.")
            return False
            
        # The card might have been re-rendered by Angular, so we search globally on the tab.
        # Wait for the inline rename input to appear
        input_ele = self.tab.ele('css:input.title-input', timeout=5)
        if not input_ele:
            logger.error("Rename input box not found in card.")
            return False
            
        # Clear value via JS and dispatch event so Angular registers the change
        input_ele.run_js("this.value = ''; this.dispatchEvent(new Event('input', {bubbles: true}));")
        
        # Then type the new title and submit
        input_ele.input(new_title + '\n')
        
        # Wait for inline input to disappear (reverts to normal label)
        is_deleted = self.tab.wait.ele_deleted(input_ele, timeout=5)
        if is_deleted:
            logger.info("Project renamed successfully via Enter key.")
            
            # Update cache if we have ID
            if project_id:
                proj = ProjectCache.get_project_by_id(project_id)
                if proj:
                    ProjectCache.update_project(project_id, new_title, proj["url"])
            return True
            
        logger.error("Failed to save project title (timeout waiting for input box to disappear).")
        return False
        
    def create_project(self) -> str:
        """
        Click the new project button, wait for navigation, and return the new UUID.
        """
        logger.info("Clicking new project button...")
        new_btn = self.tab.ele('css:button.new-project-button')
        if not new_btn:
            raise Exception("Could not find the 'New Project' button on the home page.")
            
        new_btn.click()
        
        # Wait for navigation to /project/
        self.tab.wait.url_change(self.URL, timeout=10)
        
        # The URL should now be something like https://flow.google.com/project/UUID
        current_url = self.tab.url
        match = re.search(r'/project/([a-zA-Z0-9\-]+)', current_url)
        if match:
            new_id = match.group(1)
            logger.info(f"New project created with UUID: {new_id}")
            # Save to cache with a default name (Untitled)
            ProjectCache.update_project(new_id, "Untitled project", current_url)
            return new_id
        else:
            raise Exception(f"Failed to extract project ID from URL: {current_url}")
