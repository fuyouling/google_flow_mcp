"""Google Flow MCP Browser Utilities.

共享的浏览器端口与进程管理工具。
"""

import socket
from typing import Optional
import psutil
from loguru import logger


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


def stop_browser(port: int | None = None) -> bool:
    """关闭监听指定端口的浏览器进程树。"""
    if port is None:
        from google_flow_mcp.browser.launcher import get_browser_port
        port = get_browser_port()
    proc = get_process_by_port(port)
    if not proc:
        logger.info(f"端口 {port} 未被占用，没有正在运行的浏览器。")
        return True

    try:
        logger.info(f"发现占用端口 {port} 的进程: PID={proc.pid}, Name={proc.name()}")
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
        logger.info(f"成功停止端口 {port} 上的浏览器进程。")
        return True
    except Exception as e:
        logger.warning(f"停止进程失败: {e}")
        return False


def kill_chrome_by_user_dir(user_data_dir: str) -> bool:
    """关闭使用了指定 user_data_dir 的所有 chrome 进程。"""
    import os
    try:
        norm_dir = os.path.normcase(os.path.abspath(user_data_dir))
        killed_any = False
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            name = proc.info.get('name', '')
            if name and 'chrome' in name.lower():
                cmdline = proc.info.get('cmdline') or []
                for arg in cmdline:
                    if '--user-data-dir=' in arg:
                        arg_dir = arg.split('=', 1)[1].strip('"\'')
                        arg_norm_dir = os.path.normcase(os.path.abspath(arg_dir))
                        if arg_norm_dir == norm_dir:
                            logger.info(f"发现占用目标数据目录的 chrome 进程 (PID={proc.info['pid']})，准备强制结束")
                            try:
                                proc.kill()
                                killed_any = True
                            except psutil.NoSuchProcess:
                                pass
                            break
        return killed_any
    except Exception as e:
        logger.warning(f"清理占用 user_data_dir 的进程时发生错误: {e}")
        return False
