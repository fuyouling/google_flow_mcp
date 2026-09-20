@echo off
rem ==============================================================================
rem Google Flow MCP 独立浏览器常驻启动与管理脚本 (Windows 批处理)
rem
rem 功能:
rem   复用项目现有配置 (.env 与 browser_config.yaml)，在 9222 端口常驻启动 Chromium 浏览器。
rem   启动后智能体对话和 MCP 工具调用将直接复用本窗口，无需反复启闭浏览器。
rem
rem 使用方式:
rem   【双击运行】
rem       直接双击 start_browser.bat 启动常驻服务（前台交互监控窗口）
rem
rem   【命令行运行】
rem       start_browser.bat               - 默认启动常驻服务（输入 r 刷新，输入 q 退出）
rem       start_browser.bat --status      - 查看当前 9222 端口浏览器及 CDP 运行状态
rem       start_browser.bat --force       - 强制重启（若端口冲突，先杀掉残留进程再启动）
rem       start_browser.bat --stop        - 关闭 9222 端口运行的浏览器
rem       start_browser.bat --detach      - 启动并完成检测后退出当前控制台，浏览器保留后台
rem       start_browser.bat --url <URL>   - 启动并打开指定的网页地址
rem
rem 控制台快捷键:
rem   r + 回车 : 刷新并显示当前标签页与登录态
rem   q + 回车 : 关闭浏览器并退出
rem   Ctrl+C   : 退出控制台窗口（浏览器仍保留在后台运行）
rem ==============================================================================

title Google Flow MCP Browser Service (CDP: 9222)
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m google_flow_mcp.browser.start_browser %*
) else (
    python -m google_flow_mcp.browser.start_browser %*
)

pause
