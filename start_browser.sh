#!/usr/bin/env bash
# ==============================================================================
# Google Flow MCP 独立浏览器常驻启动与管理脚本 (Linux / macOS / WSL / Git Bash)
#
# 功能:
#   复用项目现有配置 (.env 与 browser_config.yaml)，在配置指定的端口（默认 9222）常驻启动 Chromium 浏览器。
#   启动后后续智能体对话或 MCP 工具调用时将直接连接此窗口，无需反复启动浏览器。
#
# 用法：
#   ./start_browser.sh               # 默认启动常驻服务（前台保持，按 q 退出，按 r 刷新）
#   ./start_browser.sh --status      # 检查当前配置端口浏览器及 CDP 运行状态与活动标签页
#   ./start_browser.sh --force       # 强制重启（先清理占用该端口的残留进程再启动）
#   ./start_browser.sh --stop        # 安全关闭运行在配置端口的浏览器
#   ./start_browser.sh --detach      # 后台模式启动（检测并启动后立即退出当前终端，浏览器保持后台常驻）
#   ./start_browser.sh --url <URL>   # 启动并打开指定的网页地址
#
# 控制台快捷操作:
#   输入 r 并回车 : 刷新并显示当前标签页与登录态
#   输入 q 并回车 : 关闭浏览器并安全退出
#   按 Ctrl+C     : 退出当前监控终端（浏览器仍会保留在后台运行）
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 优先使用项目内的虚拟环境 Python
if [ -f ".venv/bin/python" ]; then
    PYTHON_EXEC=".venv/bin/python"
elif [ -f ".venv/Scripts/python.exe" ]; then
    PYTHON_EXEC=".venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_EXEC="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_EXEC="python"
else
    echo "[!] 错误: 未找到可用的 Python 解释器。" >&2
    exit 1
fi

exec "$PYTHON_EXEC" -m google_flow_mcp.browser.start_browser "$@"
