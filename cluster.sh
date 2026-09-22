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
#   ./cluster.sh start master              # 在后台启动主节点
#   ./cluster.sh stop                      # 停止后台运行的集群进程
#   ./cluster.sh restart master            # 重启后台集群进程
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

PID_FILE=".cluster.pid"
LOG_FILE="cluster.log"
ERR_FILE="cluster_error.log"

if [ $# -gt 0 ]; then
    CMD="$(echo "$1" | tr '[:upper:]' '[:lower:]')"
    case "$CMD" in
        start)
            shift
            echo "[*] 正在后台启动集群进程..."
            nohup "$PYTHON_EXEC" -m google_flow_mcp.cluster.launcher "$@" > "$LOG_FILE" 2> "$ERR_FILE" &
            echo $! > "$PID_FILE"
            echo "[+] 启动成功！PID: $! , 日志保存在 $LOG_FILE"
            exit 0
            ;;
        stop)
            killed_any=0
            if [ -f "$PID_FILE" ]; then
                PID=$(cat "$PID_FILE" | tr -d ' \n\r')
                if [ -n "$PID" ]; then
                    echo "[*] 正在停止后台集群进程 (PID: $PID)..."
                    kill "$PID" 2>/dev/null || true
                    killed_any=1
                fi
                rm -f "$PID_FILE"
            fi
            
            # 兜底杀掉残留进程
            for p in $(pgrep -f "google_flow_mcp.cluster.launcher" 2>/dev/null); do
                if [ "$p" != "$$" ]; then
                    echo "[*] 发现残留的集群进程 (PID: $p)，正在终止..."
                    kill -9 "$p" 2>/dev/null || true
                    killed_any=1
                fi
            done

            if [ "$killed_any" -eq 1 ]; then
                echo "[+] 已停止。"
            else
                echo "未找到运行中的集群进程 (.cluster.pid 不存在，且无对应进程)。"
            fi
            exit 0
            ;;
        restart)
            shift
            "$0" stop
            sleep 2
            "$0" start "$@"
            exit 0
            ;;
    esac
fi

exec "$PYTHON_EXEC" -m google_flow_mcp.cluster.launcher "$@"
