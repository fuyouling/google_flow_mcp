from typing import Annotated, Optional
from pydantic import Field
from loguru import logger
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.browser.exceptions import BrowserException
from google_flow_mcp.browser.session import get_browser
from google_flow_mcp.config import get_settings
from google_flow_mcp.models.response import ToolResponse


def _fetch_and_cache_credits(
    tab,
    account_email: Optional[str],
    is_homepage: bool,
) -> Optional[int]:
    """
    尝试获取 Google Flow 点数并更新 AccountCache。

    - 仅当 is_homepage=True 时实际抓取网页点数
    - 抓取失败或 is_homepage=False 时，降级返回缓存中最新点数（优先匹配当前账号）
    - 成功获取后写入 AccountCache，并尝试通过 WorkerClient 单例上报 master

    Returns:
        点数整数，或 None（无法获取时）
    """
    from google_flow_mcp.models.account_cache import AccountCache
    from google_flow_mcp.pages.flow_home_page import FlowHomePage

    fresh_credits: Optional[int] = None  # 本次从网页实际抓取的点数

    if is_homepage:
        try:
            page = FlowHomePage(tab)
            fresh_credits = page.get_credits()
        except Exception as e:
            logger.warning(f"website_open: get_credits() 抛出异常: {e}")

    # 确定最终返回值：优先新抓取，降级读缓存（优先当前账号邮箱匹配的缓存）
    if fresh_credits is not None:
        credits = fresh_credits
    else:
        credits = None
        if account_email:
            acc = AccountCache.get(account_email)
            if acc and acc.get("credits") is not None:
                credits = acc.get("credits")
        if credits is None:
            credits = AccountCache.get_latest_credits()

        if credits is not None:
            reason = "非首页，" if not is_homepage else "点数抓取失败，"
            logger.info(f"website_open: {reason}使用缓存点数 = {credits}")
        else:
            logger.info("website_open: 无法获取点数且无可用缓存")

    # 仅当从页面成功抓取到新数据时才更新缓存并上报
    if is_homepage and fresh_credits is not None:
        # 如果 account_email 为空，尝试使用 settings 中的 worker_account 或默认占位符，避免点数丢弃
        save_email = account_email or get_settings().worker_account or "default_user"
        AccountCache.update(email=save_email, credits=fresh_credits)

        # 尝试通过 WorkerClient 单例上报 master（仅 Worker 进程中有效）
        # 如果当前进程没有 WorkerClient 实例（例如独立运行的 start_browser.py），则尝试使用临时 gRPC 连接上报。
        try:
            from google_flow_mcp.cluster.worker_client import get_worker_client
            worker = get_worker_client()
            if worker is not None:
                worker.report_account_info(email=save_email, credits=fresh_credits)
        except Exception as e:
            logger.debug(f"website_open: WorkerClient 上报跳过或异常: {e}")

        # 尝试通过临时 HTTP 请求上报（非阻塞/弱依赖）
        try:
            _report_credits_via_http_temp(email=save_email, credits=fresh_credits)
        except Exception as e:
            logger.debug(f"website_open: 临时 HTTP 上报失败: {e}")

    return credits


def _report_credits_via_http_temp(email: str, credits: int) -> None:
    """
    如果在非 WorkerClient 进程（如独立的 start_browser 脚本）中抓到了积分，
    尝试通过 HTTP POST 通知 Master，以便 Master 更新大盘。
    """
    try:
        from google_flow_mcp.config import get_settings
        import socket
        import requests
        from loguru import logger
        
        settings = get_settings()
        if not settings.is_cluster_enabled or not settings.cluster_master_url:
            return

        master_url = settings.cluster_master_url.rstrip("/")
        api_url = f"{master_url}/api/account/update"
        
        worker_id = (
            settings.worker_id
            if settings.worker_id and settings.worker_id != "master_local_worker"
            else f"worker_{socket.gethostname()}"
        )
        
        logger.info(f"[_report_credits_via_http_temp] Reporting credits to {api_url} as {worker_id}...")
        
        data = {
            "email": email,
            "credits": credits,
            "worker_id": worker_id
        }
        
        response = requests.post(api_url, data=data, timeout=3.0)
        if response.status_code == 200:
            logger.info("[_report_credits_via_http_temp] Successfully reported credits to Master.")
        else:
            logger.warning(f"[_report_credits_via_http_temp] Failed to report. Status: {response.status_code}, Body: {response.text}")
            
    except Exception as e:
        from loguru import logger
        logger.error(f"[_report_credits_via_http_temp] Exception while reporting credits via HTTP: {e}")



def website_open(
    url: Annotated[str, Field(description="要打开的 URL，默认是 Google Flow 首页")] = "https://flow.google.com"
) -> str:
    """
    使用 DrissionPage 操控 Chromium 浏览器打开指定的网页。
    如果未提供 url，则默认打开 Google Flow 主页，并检查用户的登录状态及剩余点数。
    """
    settings = get_settings()
    default_url = settings.google_flow_base_url or "https://flow.google.com"
    url = url or default_url
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

        # 获取点数（仅在已登录时）
        credits = None
        if is_logged_in:
            # 规范化判断是否为首页（去除 query/hash，且确认未进入具体项目页面）
            current_clean_url = tab.url.split("?")[0].split("#")[0].rstrip("/")
            default_clean_url = default_url.split("?")[0].split("#")[0].rstrip("/")
            is_homepage = (current_clean_url == default_clean_url) and ("/project/" not in tab.url)
            credits = _fetch_and_cache_credits(
                tab=tab,
                account_email=account_email,
                is_homepage=is_homepage,
            )

            if is_homepage:
                try:
                    from google_flow_mcp.pages.flow_home_page import FlowHomePage
                    from google_flow_mcp.models.project_cache import ProjectCache
                    
                    logger.info("Initializing project list to database...")
                    page = FlowHomePage(tab)
                    projects = page.get_projects()
                    
                    for title, proj_data in projects.items():
                        ProjectCache.update_project(title, proj_data["url"])
                        
                    logger.info(f"Successfully initialized {len(projects)} projects to database.")
                except Exception as e:
                    logger.warning(f"website_open: Failed to initialize project list: {e}")

        data = {
            "title": tab.title,
            "url": tab.url,
            "is_logged_in": is_logged_in,
            "account_email": account_email,
            "credits": credits,
            "message": "Website opened successfully" if is_logged_in else "Opened, but login required",
        }

        return ToolResponse(success=True, data=data).to_json()

    except BrowserException as e:
        logger.error(f"Browser error during website opening: {e}")
        return ToolResponse(success=False, error=str(e)).to_json()
    except Exception as e:
        logger.exception("Unexpected error during website opening")
        return ToolResponse(success=False, error=str(e)).to_json()


def register_website_open_tool(mcp: FastMCP) -> None:
    """Register the open website tool with the MCP server."""
    mcp.tool()(website_open)

