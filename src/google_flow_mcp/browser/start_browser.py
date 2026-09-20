"""Google Flow MCP 独立浏览器常驻启动器.

用于独立启动并常驻一个 Chromium 浏览器实例，复用项目现有配置 (.env 与 browser_config.yaml)。
启动后监听 9222 远程调试端口 (CDP)，后续智能体对话或 MCP 工具调用时将直接连接此窗口，
避免反复拉起或关闭浏览器窗口。

使用方式:
    python -m google_flow_mcp.browser.start_browser              # 启动并常驻前台（推荐：显示状态，按 q 退出，按 r 刷新）
    python -m google_flow_mcp.browser.start_browser --detach     # 启动/接管后直接退出终端交互（后台模式）
    python -m google_flow_mcp.browser.start_browser --status     # 查看当前 9222 端口浏览器的运行状态
    python -m google_flow_mcp.browser.start_browser --stop       # 关闭运行在 9222 端口的浏览器
    python -m google_flow_mcp.browser.start_browser --force      # 强制重启（先杀死占用 9222 端口的残留进程）
    python -m google_flow_mcp.browser.start_browser --url <URL>  # 启动后打开指定的 URL
"""

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

# 确保项目根目录与 src 目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psutil
from DrissionPage import Chromium
from loguru import logger

from google_flow_mcp.browser.session import _build_options
from google_flow_mcp.config import get_settings


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """检查指定端口是否处于监听状态。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def get_process_by_port(port: int) -> Optional[psutil.Process]:
    """通过端口号查找占用该端口的进程。"""
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                if conn.pid:
                    try:
                        return psutil.Process(conn.pid)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        return None
    except Exception as e:
        logger.debug(f"psutil 查找端口出错: {e}")
    return None


def get_cdp_version(port: int = 9222, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
    """向 CDP HTTP 调试端口发送探测请求获取浏览器版本信息。"""
    url = f"http://127.0.0.1:{port}/json/version"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GoogleFlowMCP-Launcher"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return None


def get_cdp_tabs(port: int = 9222, timeout: float = 2.0) -> List[Dict[str, Any]]:
    """获取 CDP 调试端口上所有打开的标签页列表。"""
    url = f"http://127.0.0.1:{port}/json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GoogleFlowMCP-Launcher"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    return []


def stop_browser(port: int = 9222) -> bool:
    """关闭监听指定端口的浏览器进程树。"""
    proc = get_process_by_port(port)
    if not proc:
        print(f"[-] 端口 {port} 未被占用，没有正在运行的浏览器。")
        return True

    try:
        print(f"[*] 发现占用端口 {port} 的进程: PID={proc.pid}, Name={proc.name()}")
        children = proc.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        proc.terminate()
        gone, alive = psutil.wait_procs(children + [proc], timeout=3)
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        print(f"[+] 成功停止端口 {port} 上的浏览器进程。")
        return True
    except Exception as e:
        print(f"[!] 停止进程失败: {e}")
        return False


def check_status(port: int = 9222) -> None:
    """检查并打印浏览器当前运行状态。"""
    in_use = is_port_in_use(port)
    print("=" * 64)
    print(f" 浏览器运行状态检测 (CDP 端口: {port})")
    print("=" * 64)

    if not in_use:
        print(f"状态: [未运行] 端口 {port} 未被监听。")
        print("提示: 可执行 `start_browser.bat` 或 `.\\start_browser.ps1` 启动常驻浏览器。")
        print("=" * 64)
        return

    proc = get_process_by_port(port)
    proc_info = f"PID={proc.pid}, Name={proc.name()}" if proc else "未知进程"
    print(f"端口占用: 是 ({proc_info})")

    cdp_ver = get_cdp_version(port)
    if cdp_ver:
        print(f"CDP 协议: [正常可用]")
        print(f"浏览器版本: {cdp_ver.get('Browser', 'Unknown')}")
        print(f"调试地址: {cdp_ver.get('webSocketDebuggerUrl', 'Unknown')}")
        tabs = get_cdp_tabs(port)
        page_tabs = [t for t in tabs if t.get("type") in ("page", "webview")]
        print(f"活动标签页数: {len(page_tabs)}")
        for idx, tab in enumerate(page_tabs[:5], 1):
            title = tab.get("title", "No Title")
            url = tab.get("url", "about:blank")
            print(f"  {idx}. {title[:32]} -> {url[:60]}")
        if len(page_tabs) > 5:
            print(f"  ... 等共 {len(page_tabs)} 个标签页")
        print("\n结论: ✅ 浏览器正在运行且 CDP 响应正常，智能体可直接连接。")
    else:
        print(f"CDP 协议: [异常] 端口 {port} 已被占用，但未能响应 CDP 调试协议。")
        print("提示: 该端口可能被其他应用占用，可运行 `.\\start_browser.ps1 -Force` 重启。")

    print("=" * 64)


def check_login_status(tab) -> Dict[str, Any]:
    """通过页面特征检测 Google Flow 登录状态。"""
    url = getattr(tab, "url", "")
    is_logged_in = True
    account_email = None

    if url.endswith("/about") or "accounts.google.com" in url:
        is_logged_in = False
    else:
        try:
            account_meta = tab.ele('xpath://meta[@name="og-profile-acct"]', timeout=2)
            if account_meta:
                account_email = account_meta.attr("content")
        except Exception:
            pass

    return {
        "url": url,
        "title": getattr(tab, "title", ""),
        "is_logged_in": is_logged_in,
        "account_email": account_email,
    }


def launch_browser(
    target_url: Optional[str] = None,
    force: bool = False,
    detach: bool = False,
    port: int = 9222,
) -> None:
    """复用项目配置启动或接管浏览器并保持常驻。"""
    settings = get_settings()
    url = target_url or settings.google_flow_base_url

    print("=" * 64)
    print(" Google Flow MCP 独立浏览器常驻启动器")
    print("=" * 64)
    print(f"配置来源: {PROJECT_ROOT / '.env'}")
    print(f"用户数据目录: {settings.chrome_user_data_dir}")
    print(f"启动参数配置: {settings.browser_config_path}")
    print(f"Chrome 路径: {settings.chrome_binary_path or '自动探测'}")
    print(f"目标调试端口: {port}")
    print(f"目标网页地址: {url}")
    print("=" * 64)

    # 1. 如果指定了 --force，先清理现有端口占用
    if force:
        print(f"[*] 执行强制重启: 清理端口 {port} 现有进程...")
        stop_browser(port)
        time.sleep(1)

    # 2. 检查当前是否已有可用的 CDP 实例
    existing_cdp = get_cdp_version(port)
    if existing_cdp:
        print(f"[+] 检测到端口 {port} 上已有正在运行的 Chrome 实例！")
        print(f"    内核版本: {existing_cdp.get('Browser')}")
        print("[*] 正在接管现有浏览器会话...")
    elif is_port_in_use(port):
        print(f"[!] 警告: 端口 {port} 已被占用但未响应 CDP。请加参数 --force 强制释放并重启。")
        sys.exit(1)
    else:
        print(f"[*] 端口 {port} 空闲，正在根据项目配置启动全新的 Chromium 实例...")

    # 3. 构建配置并启动 / 接管浏览器
    options = _build_options(settings)

    try:
        browser = Chromium(addr_or_opts=options)
        tab = browser.latest_tab

        current_url = getattr(tab, "url", "")
        if not current_url or current_url.startswith("chrome://") or current_url == "about:blank":
            print(f"[*] 导航到首页: {url}")
            tab.get(url)
        elif target_url and target_url != current_url:
            print(f"[*] 打开指定页面: {target_url}")
            tab.get(target_url)

        time.sleep(1.5)

        # 4. 打印当前页面与登录态
        login_info = check_login_status(tab)
        print("-" * 64)
        print(f"当前页面标题: {login_info['title']}")
        print(f"当前页面地址: {login_info['url']}")
        if login_info["is_logged_in"]:
            email_desc = f" ({login_info['account_email']})" if login_info["account_email"] else ""
            print(f"Google 登录态: ✅ 已登录{email_desc}")
        else:
            print("Google 登录态: ⚠️ 未登录 (如需在 MCP 中生成内容，请在此浏览器窗口完成登录)")
        print("-" * 64)

        print("\n🎉 浏览器已就绪并处于活跃监听中！")
        print("💡 智能体在后续对话中调用 MCP 工具将直接复用本浏览器窗口，无需反复启动。")

        if detach:
            print("\n[*] [--detach 模式] 已脱离交互终端，Python 启动器退出。")
            return

        # 5. 常驻交互模式（默认）
        print("\n" + "=" * 64)
        print(" [常驻服务模式运行中]")
        print(" 保持本控制台窗口打开，即可确保浏览器持续常驻供智能体随时连接。")
        print(" 快捷控制命令:")
        print("   输入  r  并回车: 刷新并打印当前标签页状态与登录态")
        print("   输入  q  并回车: 安全关闭浏览器并退出")
        print("   按 Ctrl+C: 退出本控制台（浏览器仍保留后台）")
        print("=" * 64 + "\n")

        while True:
            try:
                cmd = input("Command [r: 刷新 / q: 退出浏览器] > ").strip().lower()
                if cmd == "q":
                    print("[*] 正在关闭浏览器...")
                    try:
                        browser.quit()
                    except Exception:
                        pass
                    print("[+] 浏览器已关闭，程序退出。")
                    break
                elif cmd == "r":
                    print("\n--- 正在刷新状态 ---")
                    check_status(port)
                    # 重新探测登录态
                    try:
                        t = browser.latest_tab
                        info = check_login_status(t)
                        status_str = f"已登录 ({info['account_email']})" if info["is_logged_in"] else "未登录"
                        print(f"最新标签页: {info['title'][:30]} | 登录: {status_str}")
                    except Exception as e:
                        print(f"探测标签页异常: {e}")
                    print("--------------------\n")
                elif cmd == "":
                    continue
                else:
                    print(f"未知命令: '{cmd}'，请输入 'r' 刷新或 'q' 退出。")
            except (KeyboardInterrupt, EOFError):
                print("\n[*] 终端控制已退出，浏览器进程已保持在后台常驻。")
                break

    except Exception as e:
        logger.exception("启动/连接浏览器发生异常")
        print(f"\n[❌ 错误] 启动或连接浏览器失败: {e}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Google Flow MCP 独立浏览器常驻启动脚本，复用项目现有配置保持浏览器常驻后台。"
    )
    parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="指定启动或打开的网页 URL (默认使用配置中的 Google Flow 首页)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="仅检查当前 9222 端口浏览器的运行状态",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="关闭运行在 9222 端口的浏览器进程",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="强制重启：先结束占用 9222 端口的进程，再重新启动浏览器",
    )
    parser.add_argument(
        "-d",
        "--detach",
        action="store_true",
        help="以脱离/非交互模式启动，完成检测后立即退出终端进程",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9222,
        help="CDP 远程调试端口 (默认 9222)",
    )

    args = parser.parse_args()

    if args.status:
        check_status(port=args.port)
    elif args.stop:
        stop_browser(port=args.port)
    else:
        launch_browser(
            target_url=args.url,
            force=args.force,
            detach=args.detach,
            port=args.port,
        )


if __name__ == "__main__":
    main()
