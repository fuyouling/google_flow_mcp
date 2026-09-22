"""Google Flow MCP 集群快速启动与管理分发入口.

提供统一的跨平台命令行入口，供 Windows (.bat / .ps1) 和 Linux (.sh) 快速调用:
1. master: 启动集群主节点 (Master HTTP/WS Hub + Local Worker + FastMCP Server)
2. worker: 启动集群从机节点 (自动检查并拉起 Chrome + 连接 Master 执行分布式任务)
3. status: 查看集群实时监控看板 (在线机器数、执行中任务、资产缓存)
"""

import argparse
import socket
import sys
import time
from pathlib import Path
from typing import List

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from google_flow_mcp.config import get_settings


def get_lan_ips() -> List[str]:
    """探测本机局域网 IPv4 地址列表，排除环回与链路本地地址。"""
    ips = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            primary_ip = s.getsockname()[0]
            if not primary_ip.startswith("127.") and not primary_ip.startswith("169.254."):
                ips.append(primary_ip)
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127.") and not ip.startswith("169.254.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass

    return ips or ["127.0.0.1"]


def normalize_master_url(raw_url: str, default_port: int = 8765) -> str:
    """标准化 Master URL。"""
    url = raw_url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"http://{url}"
    clean = url.split("://", 1)[1]
    if ":" not in clean and "/" not in clean:
        url = f"{url}:{default_port}"
    return url.rstrip("/")


def ensure_browser_running(port: int | None = None, force: bool = False) -> bool:
    """Ensure the local browser is running.
    
    If port is None, it reads the configured port from browser_config.yaml (defaults to 9222).
    """
    if port is None:
        from google_flow_mcp.browser.launcher import get_browser_port
        port = get_browser_port()
    from google_flow_mcp.browser.start_browser import get_cdp_version, is_port_in_use, launch_browser

    if not force and is_port_in_use(port):
        cdp = get_cdp_version(port)
        if cdp:
            print(f" [✔] Chrome 浏览器正在端口 {port} 运行 (CDP 就绪: {cdp.get('Browser', 'Chrome')})")
            return True

    print(f" [*] 本地端口 {port} 未检测到可用 Chrome，正在自动启动后台常驻浏览器...")
    try:
        launch_browser(force=force, detach=True, port=port)
    except Exception as e:
        print(f" [!] 启动浏览器异常: {e}")

    # 等待 CDP 就绪
    for _ in range(10):
        time.sleep(0.5)
        if get_cdp_version(port):
            print(f" [✔] Chrome 浏览器启动完成并监听端口 {port}")
            return True

    print(f" [!] 警告: 无法确认 Chrome CDP 端口 {port} 是否正常响应，请检查 Chrome 是否安装。")
    return False


# ── 命令实现 ───────────────────────────────────────────────


def cmd_master(args: argparse.Namespace) -> None:
    """启动主节点。"""
    settings = get_settings()
    lan_ips = get_lan_ips()
    primary_ip = lan_ips[0]

    print("=" * 76)
    print("           Google Flow MCP 集群主节点 (Master Node) 启动中")
    print("=" * 76)
    print(f" [✔] 本机局域网 IP : {', '.join(lan_ips)}")
    print(f" [✔] 集群调度端口 : {settings.cluster_master_port}")
    print(f" [✔] 从机接入地址 : http://{primary_ip}:{settings.cluster_master_port}")
    print(f" [✔] 集群监控端点 : http://{primary_ip}:{settings.cluster_master_port}/api/cluster/status")
    print("-" * 76)
    print(" 从机启动命令示例 (在同局域网其他机器上运行):")
    print(f"   Windows (PowerShell): .\\start_worker.ps1 -MasterUrl http://{primary_ip}:{settings.cluster_master_port}")
    print(f"   Windows (CMD/双击)  : start_worker.bat {primary_ip}")
    print(f"   Linux (Bash)        : ./start_worker.sh --master http://{primary_ip}:{settings.cluster_master_port}")
    print("=" * 76)

    if not args.no_browser:
        ensure_browser_running(port=None, force=args.force_browser)

    if args.hub_only:
        # 仅启动集群 Hub 服务，不作为 stdio MCP 运行
        from google_flow_mcp.cluster.asset_hub import AssetHub
        from google_flow_mcp.cluster.master_server import MasterServer
        from google_flow_mcp.cluster.scheduler import ClusterScheduler
        from google_flow_mcp.cluster.worker_client import WorkerClient

        print("\n[*] 启动独立集群调度中枢 (Hub Only 模式)...")
        asset_hub = AssetHub(Path(settings.cluster_asset_dir))
        cluster_scheduler = ClusterScheduler()
        master_server = MasterServer(
            scheduler=cluster_scheduler,
            asset_hub=asset_hub,
            host=settings.cluster_master_host,
            http_port=settings.cluster_master_port,
            grpc_port=settings.cluster_grpc_port,
        )
        master_server.start()

        if not args.no_local_worker:
            print("[*] 启动本机 Worker 0 参与任务计算...")
            local_worker = WorkerClient(
                master_url=f"http://127.0.0.1:{settings.cluster_master_port}",
                worker_id=settings.worker_id,
                account=settings.worker_account,
            )
            import threading
            threading.Thread(target=local_worker.run_forever, daemon=True, name="MasterLocalWorker").start()

        print("[✔] Master 服务已就绪，按 Ctrl+C 停止服务。")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[*] 正在关闭 Master 服务...")
            master_server.stop()
            print("[+] Master 服务已关闭。")
    else:
        # 默认模式：运行完整 MCP 服务 (内置 MasterServer + 本机 Worker)
        from google_flow_mcp.server import main as server_main
        print("\n[*] 正在启动 FastMCP 服务 (集成集群调度中枢与本机 Worker)...")
        server_main()


def cmd_worker(args: argparse.Namespace) -> None:
    """启动从机工作节点。"""
    settings = get_settings()
    master_url = args.master

    # 如果未指定 master_url，尝试从 .env 获取；若仍无则交互式询问
    if not master_url:
        env_url = settings.cluster_master_url
        if env_url and not env_url.startswith("http://127.0.0.1") and not env_url.startswith("http://localhost"):
            master_url = env_url
        elif sys.stdin.isatty():
            print("=" * 76)
            print("           Google Flow MCP 集群从机节点 (Worker Node) 配置")
            print("=" * 76)
            prompt_default = env_url or "http://127.0.0.1:8765"
            try:
                user_input = input(f"请输入 Master 主机 IP 或地址 [默认: {prompt_default}]: ").strip()
                master_url = user_input if user_input else prompt_default
            except (KeyboardInterrupt, EOFError):
                print("\n操作已取消。")
                sys.exit(0)
        else:
            master_url = env_url or "http://127.0.0.1:8765"

    master_url = normalize_master_url(master_url, settings.cluster_master_port)

    # Derive grpc_target from master_url if not explicitly provided
    grpc_target = args.grpc_target
    if not grpc_target:
        from urllib.parse import urlparse
        try:
            parsed = urlparse(master_url)
            host = parsed.hostname or "127.0.0.1"
            grpc_target = f"{host}:{settings.cluster_grpc_port}"
        except Exception:
            grpc_target = settings.cluster_grpc_target

    # 确定 Worker ID
    worker_id = args.id
    if not worker_id:
        worker_id = (
            settings.worker_id
            if settings.worker_id and settings.worker_id != "master_local_worker"
            else f"worker_{socket.gethostname()}"
        )

    # 确定 Google Account
    account = args.account or settings.worker_account or ""

    print("=" * 76)
    print("           Google Flow MCP 集群从机节点 (Worker Node)")
    print("=" * 76)
    print(f" [✔] 目标 Master HTTP(资产): {master_url}")
    print(f" [✔] 目标 Master gRPC(调度): {grpc_target}")
    print(f" [✔] 从机节点 ID     : {worker_id}")
    print(f" [✔] 登录 Google 账号 : {account or '(未指定/自动使用本地浏览器会话)'}")
    print("=" * 76)

    # 检查并启动本地浏览器
    if not args.no_browser:
        ensure_browser_running(port=None, force=args.force_browser)

    from google_flow_mcp.cluster.worker_client import WorkerClient

    print("\n[*] 正在连接 Master 节点...")
    client = WorkerClient(
        master_url=master_url,
        grpc_target=grpc_target,
        worker_id=worker_id,
        account=account,
    )
    try:
        client.run_forever()
    except KeyboardInterrupt:
        print("\n[*] 正在停止 Worker 节点...")
        client.stop()
        print("[+] Worker 节点已安全退出。")


def cmd_status(args: argparse.Namespace) -> None:
    """查看集群状态。"""
    from google_flow_mcp.cluster.status_cli import run_status_cli

    code = run_status_cli(
        master_url=args.master,
        watch=args.watch,
        interval=args.interval,
        output_json=args.json,
    )
    sys.exit(code)


def cmd_menu() -> None:
    """交互式控制台菜单。"""
    print("=" * 72)
    print("         Google Flow MCP 集群管理控制台 (Cluster Manager)")
    print("=" * 72)
    print(" [1] 启动从机节点 (Worker) - 参与分布式视频/图片生成 (默认)")
    print(" [2] 查看集群看板 (Status) - 查看在线机器、任务与已缓存素材")
    print(" [3] 启动主控中枢 (Master) - 独立启动 (智能体正常添加时已自动启动)")
    print(" [q] 退出")
    print("=" * 72)

    try:
        choice = input("请选择操作 [1/2/3/q, 默认 1]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n已退出。")
        sys.exit(0)

    if choice in ("", "1"):
        # 伪造 worker 参数
        worker_parser = argparse.ArgumentParser()
        worker_parser.add_argument("--master", default=None)
        worker_parser.add_argument("--grpc-target", default=None)
        worker_parser.add_argument("--id", default=None)
        worker_parser.add_argument("--account", default=None)
        worker_parser.add_argument("--no-browser", action="store_true")
        worker_parser.add_argument("--force-browser", action="store_true")
        cmd_worker(worker_parser.parse_args([]))
    elif choice == "2":
        status_parser = argparse.ArgumentParser()
        status_parser.add_argument("master", nargs="?", default=None)
        status_parser.add_argument("-w", "--watch", action="store_true")
        status_parser.add_argument("-i", "--interval", type=float, default=2.0)
        status_parser.add_argument("--json", action="store_true")
        cmd_status(status_parser.parse_args([]))
    elif choice == "3":
        master_parser = argparse.ArgumentParser()
        master_parser.add_argument("--hub-only", action="store_true")
        master_parser.add_argument("--no-local-worker", action="store_true")
        master_parser.add_argument("--no-browser", action="store_true")
        master_parser.add_argument("--force-browser", action="store_true")
        cmd_master(master_parser.parse_args([]))
    else:
        print("已退出。")
        sys.exit(0)


# ── 主入口解析 ─────────────────────────────────────────────


def main() -> None:
    raw_args = sys.argv[1:]

    # 如果没有任何参数
    if not raw_args:
        if sys.stdin.isatty():
            cmd_menu()
            return
        # 非交互环境打印帮助
        raw_args = ["--help"]

    # 智能前置转换:
    # 1. 如果第一个参数是 -w / --watch / --json，智能识别为 status 命令
    if raw_args[0] in ("-w", "--watch", "--json"):
        raw_args = ["status"] + raw_args
    # 2. 如果第一个参数是 IP 地址或 http/https 地址，智能识别为 worker --master <ip>
    elif (
        raw_args[0] not in ("master", "worker", "status", "-h", "--help")
        and not raw_args[0].startswith("-")
    ):
        raw_args = ["worker", "--master"] + raw_args

    parser = argparse.ArgumentParser(
        description="Google Flow MCP 集群快速启动与管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # master
    p_master = subparsers.add_parser("master", help="启动 Master 集群主节点")
    p_master.add_argument("--hub-only", action="store_true", help="仅启动 HTTP/WS 集群中枢，不运行 stdio MCP")
    p_master.add_argument("--no-local-worker", action="store_true", help="主节点不启动本机 Worker 0")
    p_master.add_argument("--no-browser", action="store_true", help="不自动检测或启动本机 Chrome")
    p_master.add_argument("--force-browser", action="store_true", help="强制重启本地 Chrome")

    # worker
    p_worker = subparsers.add_parser("worker", help="启动 Worker 集群从机节点")
    p_worker.add_argument("--master", "-m", default=None, help="Master 节点地址 (例如 http://192.168.1.100:8765 或 192.168.1.100)")
    p_worker.add_argument("--grpc-target", default=None, help="Master gRPC 目标地址 (默认根据 master 自动推导)")
    p_worker.add_argument("--id", default=None, help="从机节点唯一标识 (默认 worker_<主机名>)")
    p_worker.add_argument("--account", "-a", default=None, help="该从机登录的 Google Flow 账号标识")
    p_worker.add_argument("--no-browser", action="store_true", help="不自动检测或启动本机 Chrome")
    p_worker.add_argument("--force-browser", action="store_true", help="强制重启本地 Chrome")

    # status
    p_status = subparsers.add_parser("status", help="查看集群实时监控状态")
    p_status.add_argument("master", nargs="?", default=None, help="Master 节点地址")
    p_status.add_argument("-w", "--watch", action="store_true", help="持续监控并自动刷新")
    p_status.add_argument("-i", "--interval", type=float, default=2.0, help="刷新间隔秒数 (默认 2.0)")
    p_status.add_argument("--json", action="store_true", help="以 JSON 格式输出")

    args = parser.parse_args(raw_args)

    if args.command == "master":
        cmd_master(args)
    elif args.command == "worker":
        cmd_worker(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

