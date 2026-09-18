"""
测试打开指定的项目页面
"""

import time
from loguru import logger
from google_flow_mcp.browser.session import get_browser, close_browser

def test_open_project_page():
    logger.info("启动浏览器...")
    browser = get_browser()
    
    tab = browser.latest_tab
    
    target_url = "https://flow.google.com/project/41ffbc19-48f6-44c0-8b2a-4745e26ddc74"
    logger.info(f"打开项目地址: {target_url}")
    tab.get(target_url)
    
    # 等待页面加载
    tab.wait.load_start()
    
    # 打印一些页面信息以确认
    logger.info(f"当前 URL: {tab.url}")
    logger.info(f"页面标题: {tab.title}")
    
    logger.info("测试完毕，页面将停留 5 秒后结束。")
    time.sleep(5)
    close_browser()

if __name__ == "__main__":
    test_open_project_page()
