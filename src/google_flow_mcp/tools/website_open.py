from typing import Annotated
from pydantic import Field
from loguru import logger
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.browser.exceptions import BrowserException
from google_flow_mcp.browser.session import get_browser
from google_flow_mcp.config import get_settings
from google_flow_mcp.models.response import ToolResponse


def register_website_open_tool(mcp: FastMCP) -> None:
    """Register the open website tool with the MCP server."""

    @mcp.tool()
    def website_open(
        url: Annotated[str, Field(description="要打开的 URL，默认是 Google Flow 首页")] = "https://flow.google.com"
    ) -> str:
        """
        使用 DrissionPage 操控 Chromium 浏览器打开指定的网页。
        如果未提供 url，则默认打开 Google Flow 主页，并检查用户的登录状态。
        """
        settings = get_settings()
        url = url or settings.google_flow_base_url
        logger.info(f"Executing website_open for URL: {url}")

        from google_flow_mcp.tasks.manager import task_manager
        is_busy, busy_task = task_manager.is_browser_busy()
        if is_busy:
            job_id = busy_task.get("job_id", "unknown") if busy_task else "unknown"
            task_type = busy_task.get("task_type", "生成") if busy_task else "生成"
            error_msg = f"当前有后台{task_type}任务正在执行中 (job_id='{job_id}') 占用浏览器，暂无法跳转网页。请等待生成完成或使用 task_cancel(job_id='{job_id}') 取消后再操作。"
            logger.warning(f"website_open blocked: browser is busy with job {job_id}")
            return ToolResponse(success=False, error=error_msg).to_json()

        try:
            browser = get_browser()
            logger.info(f"Navigating to {url}")
            tab = browser.latest_tab
            
            # Using BasePage wrapper
            from google_flow_mcp.pages.base_page import BasePage
            page = BasePage(tab)
            page.navigate(url)

            logger.info("Retrieving page metadata and checking login status")
            
            # 方法1：检查 URL 是否被重定向到 /about (未登录状态)
            is_logged_in = True
            account_email = None
            
            if tab.url.endswith("/about") or "accounts.google.com" in tab.url:
                is_logged_in = False
                logger.warning("Redirected to /about or login page. User is not logged in.")
            else:
                # 方法2：尝试从页面 meta 标签中提取账号邮箱
                try:
                    account_meta = tab.ele('xpath://meta[@name="og-profile-acct"]', timeout=2)
                    if account_meta:
                        account_email = account_meta.attr("content")
                        logger.info(f"Found login account: {account_email}")
                    else:
                        logger.warning("Could not find account email meta tag, but URL indicates logged in state.")
                except Exception as e:
                    logger.warning(f"Error checking account meta tag: {e}")

            data = {
                "title": tab.title,
                "url": tab.url,
                "is_logged_in": is_logged_in,
                "account_email": account_email,
                "message": "Website opened successfully" if is_logged_in else "Opened, but login required"
            }
            
            return ToolResponse(success=True, data=data).to_json()

        except BrowserException as e:
            logger.error(f"Browser error during website opening: {e}")
            return ToolResponse(success=False, error=str(e)).to_json()
        except Exception as e:
            logger.exception("Unexpected error during website opening")
            return ToolResponse(success=False, error=str(e)).to_json()
