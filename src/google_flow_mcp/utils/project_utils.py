from google_flow_mcp.models.project_cache import ProjectCache
from google_flow_mcp.pages.flow_home_page import FlowHomePage
from loguru import logger

def ensure_project_exists(project_name: str, browser) -> str:
    """
    Ensures a project with the given name exists in the cloud.
    1. Checks local cache. If found, returns URL.
    2. If not in cache, navigates to FlowHomePage, extracts all projects from the cloud.
    3. If found in cloud projects, updates cache and returns URL.
    4. If not found in cloud, auto-creates it, renames it, updates cache, and returns URL.
    """
    if not project_name:
        raise ValueError("project_name cannot be empty")
        
    cache = ProjectCache.load()
    projects = cache.get("projects", {})
    if project_name in projects and projects[project_name].get("url"):
        return projects[project_name]["url"]
        
    logger.info(f"Project '{project_name}' not in local cache. Fetching from cloud...")
    page = FlowHomePage(browser.latest_tab)
    page.open()
    
    cloud_projects = page.get_projects()
    # Sync all cloud projects to cache
    for title, data in cloud_projects.items():
        ProjectCache.update_project(title, data["url"])
        
    if project_name in cloud_projects:
        logger.info(f"Project '{project_name}' found in cloud. Updated cache.")
        return cloud_projects[project_name]["url"]
        
    # Not found in cloud. Auto-create it.
    logger.info(f"Project '{project_name}' not found in cloud. Auto-creating...")
    new_id = page.create_project()
    url = f"https://flow.google.com/project/{new_id}"
    
    logger.info(f"Navigating back to home to rename new project to '{project_name}'")
    page.open()
    success = page.rename_project("Untitled project", project_name)
    if not success:
        logger.warning(f"Failed to rename newly created project to {project_name}")
        
    ProjectCache.update_project(project_name, url)
    return url
