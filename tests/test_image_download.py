"""
测试打开图像编辑页面并下载图片
"""

import base64
import time
from loguru import logger
from google_flow_mcp.browser.session import get_browser, close_browser
from google_flow_mcp.pages.image_edit_page import ImageEditPage

def test_image_download():
    logger.info("启动浏览器...")
    browser = get_browser()
    
    logger.info("实例化 ImageEditPage...")
    tab = browser.latest_tab
    edit_page = ImageEditPage(tab)
    
    project_name = "41ffbc19-48f6-44c0-8b2a-4745e26ddc74"
    media_id = "e45e4ec3-34b5-4b63-aa62-d6510415e8f8"
    
    logger.info(f"打开项目 {project_name} 下的资源 {media_id} ...")
    edit_page.open(project_name, media_id)
    
    # 打印一些页面信息以确认
    logger.info(f"当前 URL: {edit_page.current_url}")
    logger.info(f"页面标题: {edit_page.title}")
    
    # 获取媒体 URL
    logger.info("尝试通过 xpath 查找图片元素...")
    img_ele = tab.ele('xpath://img[@class="ghost-image"]', timeout=5)
    if img_ele:
        img_src = img_ele.attr('src')
        logger.info(f"成功获取图片链接: {img_src}")
    else:
        logger.warning("未能找到对应的图片元素")
        
    logger.info("尝试点击 [完成修改] 按钮...")
    btn_ele = tab.ele('xpath://button[@aria-label="完成修改"]', timeout=5)
    if btn_ele:
        btn_ele.click()
        logger.info("已点击 [完成修改] 按钮")
    else:
        logger.warning("未能找到 [完成修改] 按钮")
        
    time.sleep(3)
    close_browser()

if __name__ == "__main__":
    test_image_download()
