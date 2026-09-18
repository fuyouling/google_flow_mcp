"""
测试打开图像编辑页面
"""

import time
from loguru import logger
from google_flow_mcp.browser.session import get_browser, close_browser
from google_flow_mcp.pages.image_edit_page import ImageEditPage

def test_open_image_edit_page():
    logger.info("启动浏览器...")
    browser = get_browser()
    
    logger.info("实例化 ImageEditPage...")
    tab = browser.latest_tab
    edit_page = ImageEditPage(tab)
    
    project_id = "41ffbc19-48f6-44c0-8b2a-4745e26ddc74"
    media_id = "e45e4ec3-34b5-4b63-aa62-d6510415e8f8"
    
    logger.info(f"打开项目 {project_id} 下的资源 {media_id} ...")
    edit_page.open(project_id, media_id)
    
    # 打印一些页面信息以确认
    logger.info(f"当前 URL: {edit_page.current_url}")
    logger.info(f"页面标题: {edit_page.title}")
    
    # 获取媒体 URL
    media_url = edit_page.get_media_url()
    logger.info(f"获取到的媒体 URL: {media_url}")
    
    # 可以尝试获取 base64
    b64 = edit_page.get_base64()
    b64_len = len(b64) if b64 else 0
    logger.info(f"获取到的 Base64 长度: {b64_len}")
    
    logger.info("开始测试通过 xpath 获取输入框并修改内容...")
    try:
        from DrissionPage.common import Keys
        # 1. 通过 xpath 表达式获取元素 //input[@type="text"]
        input_ele = tab.ele('xpath://input[@type="text"]', timeout=5)
        if input_ele:
            # 2. 点击该元素进入编辑模式
            logger.info("找到输入框，点击进入编辑模式")
            input_ele.click()
            time.sleep(0.5)
            
            # 3. 发送全选快捷键 (Ctrl+A) 采用 CDP 模式触发底层按键
            logger.info("发送全选快捷键 (CDP)")
            tab.run_cdp('Input.dispatchKeyEvent', type='keyDown', windowsVirtualKeyCode=65, modifiers=2)
            tab.run_cdp('Input.dispatchKeyEvent', type='keyUp', windowsVirtualKeyCode=65, modifiers=2)
            time.sleep(0.2)
            
            # 4. 发送 backspace 键
            logger.info("发送 backspace 键 (CDP)")
            tab.run_cdp('Input.dispatchKeyEvent', type='keyDown', windowsVirtualKeyCode=8)
            tab.run_cdp('Input.dispatchKeyEvent', type='keyUp', windowsVirtualKeyCode=8)
            time.sleep(0.2)
            
            # 5. 粘贴/修改内容 "test_222"
            logger.info("输入修改内容 test_222")
            input_ele.input('test_222')
            time.sleep(0.2)
            
            # 6. 发送回车
            logger.info("发送回车键 (完善版 CDP)")
            tab.run_cdp('Input.dispatchKeyEvent', type='rawKeyDown', windowsVirtualKeyCode=13, key='Enter', code='Enter', text='\r', unmodifiedText='\r')
            tab.run_cdp('Input.dispatchKeyEvent', type='char', windowsVirtualKeyCode=13, key='Enter', code='Enter', text='\r', unmodifiedText='\r')
            tab.run_cdp('Input.dispatchKeyEvent', type='keyUp', windowsVirtualKeyCode=13, key='Enter', code='Enter')
            time.sleep(1)
            
            # 打印修改后的值以便确认
            logger.info(f"操作完成，当前输入框的值为: {input_ele.property('value')}")
        else:
            logger.warning("未能找到 //input[@type=\"text\"] 元素")
    except Exception as e:
        logger.error(f"测试操作输入框时发生异常: {e}")
    
    logger.info("测试完毕，页面将停留 5 秒后结束。")
    time.sleep(5)
    close_browser()

if __name__ == "__main__":
    test_open_image_edit_page()
