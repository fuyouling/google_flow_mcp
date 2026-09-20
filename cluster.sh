#!/usr/bin/env bash
# ==============================================================================
# Google Flow MCP 集群管理控制台 (Linux / macOS / WSL)
#
# 使用方式:
#   ./cluster.sh                           # 打开交互控制台菜单 (默认启动从机)
#   ./cluster.sh worker 192.168.1.100      # 启动从机节点并连接 Master
#   ./cluster.sh 192.168.1.100             # 快捷启动从机
#   ./cluster.sh status                    # 查看集群看板
#   ./cluster.sh status -w                 # 持续刷新监控集群
#   ./cluster.sh master                    # 独立启动主节点
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

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

exec "$PYTHON_EXEC" -m google_flow_mcp.cluster.launcher "$@"
