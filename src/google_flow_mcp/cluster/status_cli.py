"""Google Flow MCP 集群状态监控命令行工具.

用于查询并展示当前 Master 节点的集群健康状态、在线 Worker 节点、正在执行的任务与资产缓存。
支持一次性输出、持续监听 (--watch)、JSON 格式输出。

使用方式:
    python -m google_flow_mcp.cluster.status_cli
    python -m google_flow_mcp.cluster.status_cli http://192.168.1.100:8765
    python -m google_flow_mcp.cluster.status_cli --watch
    python -m google_flow_mcp.cluster.status_cli --json
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from google_flow_mcp.config import get_settings


def normalize_url(url: str, default_port: int = 8765) -> str:
    """标准化学员传入的主机地址格式。"""
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"http://{url}"
    # 如果没有指定端口且是纯 IP/主机名
    clean = url.split("://", 1)[1]
    if ":" not in clean and "/" not in clean:
        url = f"{url}:{default_port}"
    return url.rstrip("/")


def fetch_cluster_status(master_url: str, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
    """向 Master 节点请求集群状态。"""
    url = f"{master_url}/api/cluster/status"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "GoogleFlowMCP-StatusCLI/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = resp.read().decode("utf-8")
                return json.loads(data)
    except urllib.error.URLError as e:
        return None
    except Exception:
        return None
    return None


def format_status_table(master_url: str, data: Dict[str, Any]) -> str:
    """格式化终端状态面板。"""
    worker_count = data.get("worker_count", 0)
    pending_tasks = data.get("pending_tasks", 0)
    active_tasks = data.get("active_tasks", 0)
    workers = data.get("workers", [])

    lines = []
    lines.append("=" * 76)
    lines.append("                 Google Flow MCP 集群实时监控面板")
    lines.append("=" * 76)
    lines.append(f" Master 节点地址 : {master_url}")
    lines.append(f" 在线从机数量   : {worker_count} 台")
    lines.append(f" 任务排队中     : {pending_tasks} 个")
    lines.append(f" 任务执行中     : {active_tasks} 个")
    lines.append("-" * 76)

    if not workers:
        lines.append(" [!] 当前没有已连接的 Worker 从机节点。")
    else:
        # 表头
        lines.append(
            f"{'节点 ID':<22} {'账号/身份':<20} {'状态':<10} {'当前执行任务':<14} {'已缓存素材'}"
        )
        lines.append("-" * 76)
        for w in workers:
            w_id = str(w.get("worker_id", "unknown"))
            if len(w_id) > 20:
                w_id = w_id[:18] + ".."
            account = str(w.get("account") or "-")
            if len(account) > 18:
                account = account[:16] + ".."
            state = str(w.get("state", "idle")).upper()
            curr_job = str(w.get("current_job_id") or "-")
            if len(curr_job) > 12:
                curr_job = curr_job[:10] + ".."
            cached = w.get("cached_assets", [])
            cached_count = len(cached) if isinstance(cached, list) else 0
            cached_info = f"{cached_count} 个"
            if cached_count > 0 and isinstance(cached, list):
                preview = ", ".join(cached[:2])
                if cached_count > 2:
                    preview += f" 等"
                cached_info = f"{cached_count} ({preview})"

            lines.append(
                f"{w_id:<22} {account:<20} {state:<10} {curr_job:<14} {cached_info}"
            )

    lines.append("=" * 76)
    return "\n".join(lines)


def run_status_cli(
    master_url: Optional[str] = None,
    watch: bool = False,
    interval: float = 2.0,
    output_json: bool = False,
) -> int:
    """运行集群状态 CLI 主逻辑。"""
    settings = get_settings()
    target_master = master_url or settings.cluster_master_url or "http://127.0.0.1:8765"
    target_master = normalize_url(target_master, settings.cluster_master_port)

    while True:
        data = fetch_cluster_status(target_master)

        if output_json:
            if data is None:
                print(json.dumps({"error": f"Failed to connect to Master at {target_master}"}))
                if not watch:
                    return 1
            else:
                print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            if watch:
                # 清屏
                os.system("cls" if os.name == "nt" else "clear")

            if data is None:
                print("=" * 76)
                print(f" [!] 无法连接到 Master 节点: {target_master}")
                print("=" * 76)
                print(" 可能原因:")
                print("   1. 主节点 (Master) 尚未启动；")
                print(f"   2. 目标主机 IP 错误或防火墙阻止了 {settings.cluster_master_port} 端口的访问；")
                print("   3. 主节点与从机不在同一局域网或网络不通。")
                print("=" * 76)
                if not watch:
                    return 1
            else:
                print(format_status_table(target_master, data))
                if watch:
                    print(f" [i] 正在持续监听 (每 {interval} 秒刷新一次, 按 Ctrl+C 退出)...")

        if not watch:
            break

        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            break

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Google Flow MCP 集群状态监控")
    parser.add_argument("master", nargs="?", default=None, help="Master 节点地址 (默认从 .env 读取)")
    parser.add_argument("-w", "--watch", action="store_true", help="持续监控并自动刷新")
    parser.add_argument("-i", "--interval", type=float, default=2.0, help="刷新间隔秒数 (默认 2.0s)")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出状态")
    args = parser.parse_args()

    code = run_status_cli(
        master_url=args.master,
        watch=args.watch,
        interval=args.interval,
        output_json=args.json,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
