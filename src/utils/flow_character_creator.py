#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Flow (flow.google.com) 角色基准母板双轮生成自动化工具
专为《秘密花园》项目定制开发，支持人像（*-portrait.png）+ 全身二联画（*-fullbody.png）双轮生成与音色配置。
"""

import os
import sys
import re
import time
import json
import argparse
import urllib.request
from pathlib import Path

import subprocess

try:
    import websocket
except ImportError:
    print("❌ [依赖缺失] 未安装 websocket-client 库，请先运行: pip install websocket-client")
    sys.exit(1)


# =====================================================================
# 1. 配置文件加载与 Chrome 直接命令启动
# =====================================================================

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "chrome_config.json"

DEFAULT_CHROME_CONFIG = {
    "chrome_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "port": 9222,
    "user_data_dir": r"C:\Users\zgh\AppData\Local\Google\Chrome_CDP",
    "profile_directory": "",
    "headless": True,
    "extra_args": [
        "--remote-allow-origins=*",
        "--disable-features=DevToolsRemoteDebuggingAllowNotice"
    ]
}


def load_chrome_config(config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
    """加载 Chrome 配置文件，若不存在则自动生成默认配置"""
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                return {**DEFAULT_CHROME_CONFIG, **config}
        except Exception as e:
            print(f"⚠️ [配置警告] 读取配置文件失败 ({e})，将使用内置默认配置。")
            return DEFAULT_CHROME_CONFIG.copy()
    else:
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CHROME_CONFIG, f, indent=2, ensure_ascii=False)
            print(f"ℹ️ [配置生成] 已创建默认 Chrome 配置文件: {config_path}")
        except Exception:
            pass
        return DEFAULT_CHROME_CONFIG.copy()


def launch_chrome_by_command(config: dict):
    """直接使用配置命令启动 Chrome 浏览器（不进行前置端口监听与等待）"""
    command = config.get("command")
    headless = config.get("headless", True)
    if not command:
        chrome_path = config.get("chrome_path", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        port = config.get("port", 9222)
        user_data_dir = config.get("user_data_dir", r"C:\Users\zgh\AppData\Local\Google\Chrome\User Data")
        profile_dir = config.get("profile_directory", "")
        extra_args = config.get("extra_args", [])

        headless_args = []
        if headless:
            # 采用 Chrome 新版无头模式，并锁定 1080P 视口以保障 Web UI 正常渲染
            headless_args = ["--headless=new", "--disable-gpu", "--window-size=1920,1080"]

        if sys.platform == "win32":
            # Windows 下使用 PowerShell Core (pwsh) Start-Process 启动，确保 Chrome 成为完全脱离的独立 GUI/后台进程
            arg_list = [
                f"'--remote-debugging-port={port}'",
                f"'--user-data-dir={user_data_dir}'"
            ]
            for h_arg in headless_args:
                arg_list.append(f"'{h_arg}'")
            if profile_dir and profile_dir.strip():
                arg_list.append(f"'--profile-directory={profile_dir.strip()}'")
            for arg in extra_args:
                if arg and arg.strip():
                    arg_list.append(f"'{arg.strip()}'")
            command = f"pwsh -NoProfile -Command \"Start-Process -FilePath '{chrome_path}' -ArgumentList {', '.join(arg_list)}\""
        else:
            cmd_parts = [
                f'"{chrome_path}"',
                f"--remote-debugging-port={port}",
                f'--user-data-dir="{user_data_dir}"'
            ]
            cmd_parts.extend(headless_args)
            if profile_dir and profile_dir.strip():
                cmd_parts.append(f'--profile-directory="{profile_dir.strip()}"')
            if extra_args:
                cmd_parts.append(" ".join(extra_args))
            command = " ".join(cmd_parts).strip()

    mode_text = "【无头静默模式 (Headless)】" if headless else "【有头窗口模式 (Headed)】"
    print("\n" + "=" * 65)
    print(f"🚀 [启动 Chrome] 正在执行命令启动浏览器 {mode_text}...")
    print(f"   命令: {command}")
    print("=" * 65 + "\n")

    try:
        if sys.platform == "win32":
            subprocess.Popen(command, shell=True, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            subprocess.Popen(command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception as e:
        print(f"⚠️ [启动提醒] 执行启动命令提示: {e}，将直接尝试接管...")

    # 留给浏览器进程基础唤醒时间
    time.sleep(2.0)


# =====================================================================
# 2. CDP 通信与浏览器直接接管
# =====================================================================

class ChromeCDPClient:
    """基于 WebSocket 与 CDP 协议直接接管 Chrome，严格绑定指定端口（无端口自适应）"""

    def __init__(self, host: str = "127.0.0.1", port: int = 9222):
        self.host = host
        self.port = port
        self.ws = None
        self.msg_id = 0
        self.browser_session = None

    def connect(self, max_retries: int = 20, retry_interval: float = 1.0):
        """严格直连配置端口建立 WebSocket 连接（无端口自适应，增加就绪重试）"""
        for attempt in range(max_retries):
            ws_url = None

            # 方式 1: 直接向指定 host:port 的 /json/version 请求获取 webSocketDebuggerUrl
            try:
                req = urllib.request.Request(f"http://{self.host}:{self.port}/json/version")
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    data = json.loads(resp.read().decode())
                    ws_url = data.get("webSocketDebuggerUrl")
            except Exception:
                pass

            # 方式 2: 直连指定端口的 devtools/browser 端点
            if not ws_url:
                ws_url = f"ws://{self.host}:{self.port}/devtools/browser"

            try:
                # suppress_origin=True 避免 Chrome 新版跨源 403 拦截
                self.ws = websocket.create_connection(ws_url, suppress_origin=True, timeout=5.0)
                print(f"✅ [CDP 连接成功] 已成功接管 Chrome ({self.host}:{self.port})")
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(retry_interval)
                else:
                    print(f"❌ [CDP 连接失败] 无法建立 WebSocket 连接 ({ws_url}): {e}")
                    sys.exit(1)

    def send_cmd(self, method: str, params: dict = None, session_id: str = None) -> dict:
        """发送 CDP 指令并同步接收响应"""
        self.msg_id += 1
        payload = {"id": self.msg_id, "method": method}
        if params:
            payload["params"] = params
        if session_id:
            payload["sessionId"] = session_id

        self.ws.send(json.dumps(payload))

        while True:
            raw = self.ws.recv()
            data = json.loads(raw)
            if data.get("id") == self.msg_id:
                if "error" in data:
                    raise RuntimeError(f"CDP Error in {method}: {data['error']}")
                return data.get("result", {})

    def evaluate_js(self, session_id: str, expression: str):
        """在指定页面会话中执行 JavaScript 并返回纯值"""
        res = self.send_cmd(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            session_id=session_id
        )
        result_val = res.get("result", {})
        return result_val.get("value")

    def attach_to_page(self, target_id: str) -> str:
        """附加到目标页签并获取 session ID"""
        res = self.send_cmd("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        return res.get("sessionId")

    def get_all_targets(self) -> list:
        res = self.send_cmd("Target.getTargets")
        return res.get("targetInfos", [])

    def close(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass


# =====================================================================
# 3. 提示词解析与提取
# =====================================================================

def _extract_code_block(content: str, section_pattern: str) -> str | None:
    """提取指定 section 标题下的第一个代码块"""
    pat = section_pattern + r"[\s\S]*?```(?:\w+)?\n([\s\S]*?)\n```"
    m = re.search(pat, content, re.IGNORECASE)
    return m.group(1).strip() if m else None


def extract_portrait_prompt(md_path: Path) -> str:
    """提取 ### Portrait Prompt (English) 代码块"""
    if not md_path.exists():
        raise FileNotFoundError(f"提示词文件不存在: {md_path}")
    content = md_path.read_text(encoding="utf-8")
    # 优先匹配新格式 Portrait Prompt 章节
    prompt = _extract_code_block(content, r"###\s*Portrait Prompt")
    if not prompt:
        # 兼容旧版单一代码块（三联画旧格式）：取第一个含 SUBJECT 的代码块
        m = re.search(r"```(?:\w+)?\n((?:A (?:close-up|continuous)|SUBJECT:)[\s\S]*?)\n```", content)
        prompt = m.group(1).strip() if m else None
    if not prompt:
        raise ValueError(f"未能在 {md_path.name} 中提取到 Portrait Prompt！")
    return prompt


def extract_fullbody_prompt(md_path: Path) -> str:
    """提取 ### Full Body Prompt (English) 代码块"""
    if not md_path.exists():
        raise FileNotFoundError(f"提示词文件不存在: {md_path}")
    content = md_path.read_text(encoding="utf-8")
    prompt = _extract_code_block(content, r"###\s*Full Body Prompt")
    if not prompt:
        raise ValueError(f"未能在 {md_path.name} 中提取到 Full Body Prompt！")
    return prompt


def extract_voice_metadata(md_path: Path) -> dict:
    """提取元数据头部的 Recommended Voice 与 Voice Style Prompt 字段
    返回: {"voice_name": "Kore", "voice_style": "British Yorkshire accent..."}
    """
    if not md_path.exists():
        raise FileNotFoundError(f"提示词文件不存在: {md_path}")
    content = md_path.read_text(encoding="utf-8")
    voice_name = ""
    voice_style = ""
    m = re.search(r"\*\*Recommended Voice\*\*\s*:\s*(.+)", content)
    if m:
        voice_name = m.group(1).strip().split("（")[0].split("(")[0].strip()
    m2 = re.search(r"\*\*Voice Style Prompt\*\*\s*:\s*(.+)", content)
    if m2:
        voice_style = m2.group(1).strip()
    return {"voice_name": voice_name, "voice_style": voice_style}


# 兼容旧接口
def extract_full_prompt_from_markdown(md_path: Path) -> str:
    """[兼容旧接口] 提取 Portrait Prompt（新格式）或旧版 Full Prompt"""
    try:
        return extract_portrait_prompt(md_path)
    except ValueError:
        pass
    # 旧格式兜底
    if not md_path.exists():
        raise FileNotFoundError(f"提示词文件不存在: {md_path}")
    c = md_path.read_text(encoding="utf-8")
    m = re.search(r"##\s*Full Prompt\s*\(English\)\s*\n+```(?:\w+)?\n([\s\S]*?)\n```", c, re.IGNORECASE)
    if not m:
        m = re.search(r"```(?:\w+)?\n([\s\S]*?STYLE[\s\S]*?)\n```", c)
    if not m:
        raise ValueError(f"未能在 {md_path.name} 中提取到有效提示词代码块！")
    return m.group(1).strip()


# =====================================================================
# 4. Google Flow 自动化创建角色核心业务流程
# =====================================================================

class GoogleFlowCharacterCreator:
    def __init__(self, cdp: ChromeCDPClient, project_name: str, char_name: str, prompt_file: Path, output_dir: Path, headless: bool = True):
        self.cdp = cdp
        self.project_name = project_name
        self.char_name = char_name
        self.prompt_file = prompt_file
        self.prompt_filename = prompt_file.stem
        self.output_dir = output_dir
        self.headless = headless
        self.session_id = None
        self.target_id = None
        self.downloaded_img_srcs = set()

    def find_or_open_flow_tab(self):
        """查找已有 Flow 标签页，若无则新建打开"""
        targets = self.cdp.get_all_targets()
        flow_target = None
        for t in targets:
            url = t.get("url", "")
            if "flow.google.com" in url:
                flow_target = t
                break

        if flow_target:
            self.target_id = flow_target["targetId"]
            print(f"🔍 [发现已有标签页] {flow_target.get('title')} ({flow_target.get('url')})")
            self.session_id = self.cdp.attach_to_page(self.target_id)
            current_url = flow_target.get("url", "")
            if "/project/" in current_url:
                print("🔄 [重置起始路径] 将标签页导航至 flow.google.com 首页以执行严格的项目选择流程...")
                self.cdp.evaluate_js(self.session_id, "location.href = 'https://flow.google.com/';")
                time.sleep(3.5)
        else:
            print("🌐 [打开新标签页] 正在打开 https://flow.google.com/ ...")
            res = self.cdp.send_cmd("Target.createTarget", {"url": "https://flow.google.com/"})
            self.target_id = res["targetId"]
            time.sleep(3.0)
            self.session_id = self.cdp.attach_to_page(self.target_id)

    def check_login_status_strictly(self):
        """只读严格检测 Google 账号登录态（绝对禁止脚本自动化登录）"""
        print("🔐 [登录检测] 正在进行 Google 账号只读登录态安全检测...")

        for _ in range(5):
            status = self.cdp.evaluate_js(
                self.session_id,
                """
                (() => {
                    const url = location.href;
                    if (url.includes('accounts.google.com') || url.includes('ServiceLogin')) {
                        return { loggedIn: false, reason: '处于 Google 登录跳转页' };
                    }
                    // 检测右上角用户头像或账号信息
                    const profile = document.querySelector('[aria-label*="Google 账号"], [aria-label*="Google Account"], [aria-label="账号详情"], .header-user-button');
                    const signInBtn = Array.from(document.querySelectorAll('button, a')).find(el => {
                        const txt = (el.innerText || '').trim();
                        return txt === 'Sign in' || txt === '登录' || (el.getAttribute('aria-label') || '').includes('登录');
                    });
                    if (signInBtn && !profile) {
                        return { loggedIn: false, reason: '检测到登录按钮' };
                    }
                    if (profile) {
                        return { loggedIn: true, account: profile.getAttribute('aria-label') || profile.innerText };
                    }
                    return { loggedIn: true, note: '正常进入主控制台' };
                })()
                """
            )
            if status and not status.get("loggedIn"):
                print("\n" + "!" * 70)
                print(f"❌ [安全熔断] 检测到 Google Flow 当前未登录账号 ({status.get('reason')})！")
                print("👉 为保障账号安全与遵循合规要求，脚本严禁自动化输入账号密码。")
                if self.headless:
                    print("💡 当前为【无头模式 (Headless)】，无法在桌面直接人工点击登录。")
                    print("👉 请添加 --headed 参数启动有头模式完成一次性手动登录：")
                    print(f"   python scripts/flow_character_creator.py --character {self.char_name} --headed")
                else:
                    print("👉 请在已打开的 Chrome 浏览器窗口中手动完成 Google 账号登录后重新运行本脚本。")
                print("!" * 70 + "\n")
                sys.exit(1)
            elif status and status.get("loggedIn"):
                account_info = status.get("account", "").replace("\n", " ")
                print(f"✅ [登录状态确认] Google 账号已登录: {account_info or '有效会话'}")
                return

            time.sleep(1.0)

    def step1_find_and_enter_project(self):
        """步骤 1：找到项目名称，点击"""
        print(f"📁 [步骤 1: 找到项目名称, 点击] 正在匹配目标项目: '{self.project_name}' ...")

        # 先检查当前页面是否已在目标项目中
        cur_status = self.cdp.evaluate_js(
            self.session_id,
            """
            (() => {
                return {
                    url: location.href,
                    title: document.title
                };
            })()
            """
        )
        if "/project/" in cur_status.get("url", "") and (self.project_name in cur_status.get("title", "") or "flow" in cur_status.get("title", "").lower()):
            print(f"✅ [步骤 1 就绪] 当前页面已处于项目中: {cur_status.get('title')}")
            return

        # 轮询等待项目列表渲染并检索项目卡片 (最多等待 15 秒)
        found_project = None
        for attempt in range(10):
            found_project = self.cdp.evaluate_js(
                self.session_id,
                f"""
                (() => {{
                    const targetName = '{self.project_name}'.toLowerCase();
                    const targetClean = targetName.replace(/-/g, ' ');

                    // 1. 优先查找具有"打开项目"属性的链接与容器
                    const links = Array.from(document.querySelectorAll('a[aria-label*="打开项目"], a[href*="/project/"]'));
                    for (const a of links) {{
                        const container = a.closest('div, li, mat-card') || a.parentElement;
                        const fullText = ((container ? container.innerText : '') + ' ' + (a.innerText || '')).toLowerCase();
                        if (fullText.includes(targetName) || fullText.includes(targetClean) || fullText.includes('garden')) {{
                            a.click();
                            return {{ found: true, text: container ? container.innerText.trim() : a.href }};
                        }}
                    }}

                    // 2. 查找包含项目名称的卡片或按钮
                    const allCards = Array.from(document.querySelectorAll('div, li, mat-card, a')).filter(el => {{
                        const t = (el.innerText || '').toLowerCase();
                        return (t.includes(targetName) || t.includes(targetClean)) && t.length < 100;
                    }});
                    if (allCards.length > 0) {{
                        const targetCard = allCards[0];
                        const clickEl = targetCard.querySelector('a, button') || targetCard;
                        clickEl.click();
                        return {{ found: true, text: targetCard.innerText.trim() }};
                    }}

                    return {{ found: false }};
                }})()
                """
            )
            if found_project and found_project.get("found"):
                break
            time.sleep(1.5)

        if not found_project or not found_project.get("found"):
            print("\n" + "=" * 70)
            print(f"❌ [项目不存在] 在 Google Flow 中未找到名为 '{self.project_name}' 的项目！")
            print("👉 脚本不会自动创建新项目。请先在 flow.google.com 网页端手动创建该项目后重试。")
            print("=" * 70 + "\n")
            sys.exit(1)

        print(f"✅ [步骤 1 完成] 已成功点击进入项目: {self.project_name}")
        time.sleep(4.0)

    def step2_find_and_click_right_character_button(self):
        """步骤 2：找到右侧角色按钮，点击"""
        print("🎭 [步骤 2: 找到右侧角色按钮, 点击] 正在定位'角色'板块按钮...")

        # 检查是否已经在角色页面或编辑器已就绪
        url_check = self.cdp.evaluate_js(self.session_id, "location.href") or ""
        if url_check.endswith("/character"):
            print("✅ [步骤 2 跳过] 当前已在角色管理页面 (/character)")
            return

        for attempt in range(5):
            click_res = self.cdp.evaluate_js(
                self.session_id,
                """
                (() => {
                    const winWidth = window.innerWidth;
                    // 查找所有包含"角色"或"Character"的按钮、Tab或列表项
                    const candidates = Array.from(document.querySelectorAll('mat-list-item, button, a, [role="tab"], [role="button"], div.tab, span, .navigation-item'));
                    const matches = candidates.filter(el => {
                        const txt = (el.innerText || '').trim();
                        const aria = (el.getAttribute('aria-label') || '').trim();
                        return txt === '角色' || txt.includes('角色') || aria.includes('角色') ||
                               txt.toLowerCase() === 'characters' || txt.toLowerCase() === 'character' ||
                               aria.toLowerCase().includes('character');
                    });

                    if (matches.length > 0) {
                        const topMatches = matches.map(m => m.closest('mat-list-item, button, a, [role="tab"]') || m);
                        const uniqueTargets = Array.from(new Set(topMatches));
                        const target = uniqueTargets[0];
                        target.click();
                        const r = target.getBoundingClientRect();
                        return {
                            success: true,
                            text: target.innerText || target.getAttribute('aria-label'),
                            isRight: r.left > (winWidth * 0.4)
                        };
                    }
                    return { success: false };
                })()
                """
            )
            if click_res and click_res.get("success"):
                pos_desc = "右侧/导航" if click_res.get("isRight") else "侧边栏"
                raw_text = (click_res.get('text') or '').replace('\n', ' ')
                print(f"✅ [步骤 2 完成] 已成功点击{pos_desc}'角色'按钮 ({raw_text})")
                time.sleep(3.0)
                return
            time.sleep(1.5)

        # 兜底：直接在当前项目中尝试导航至 /character
        if "/project/" in url_check:
            base_url = url_check.split("?")[0].rstrip("/")
            print(f"ℹ️ [步骤 2 路由补正] 直接导航至项目角色模块: {base_url}/character ...")
            self.cdp.evaluate_js(self.session_id, f"location.href = '{base_url}/character';")
            time.sleep(3.5)

    def step3_find_and_click_new_character(self):
        """步骤 3：找到'新角色'按钮，点击"""
        print("➕ [步骤 3: 找找 新角色 点击] 正在检索'新角色'创建入口...")

        for attempt in range(5):
            click_res = self.cdp.evaluate_js(
                self.session_id,
                """
                (() => {
                    // 查找包含"新角色"、"新建角色"、"创建角色"、"New Character"的按钮
                    const btns = Array.from(document.querySelectorAll('button, a, [role="button"], mat-list-item, div[role="button"]'));
                    const newBtn = btns.find(el => {
                        const txt = (el.innerText || '').trim();
                        const aria = (el.getAttribute('aria-label') || '').trim();
                        return txt.includes('新角色') || txt.includes('新建角色') || txt.includes('创建角色') ||
                               aria.includes('新角色') || aria.includes('新建角色') || aria.includes('创建角色') ||
                               txt.toLowerCase().includes('new character') || aria.toLowerCase().includes('new character');
                    });
                    if (newBtn) {
                        newBtn.click();
                        return { clicked: true, text: newBtn.innerText || newBtn.getAttribute('aria-label') };
                    }
                    return { clicked: false };
                })()
                """
            )
            if click_res and click_res.get("clicked"):
                print(f"✅ [步骤 3 完成] 已成功点击'新角色'按钮 ({click_res.get('text')})")
                time.sleep(2.5)
                return
            time.sleep(1.0)

        # 兜底检查：是否已存在 ProseMirror / 提示词输入框
        has_editor = self.cdp.evaluate_js(self.session_id, "!!document.querySelector('.ProseMirror, textarea')")
        if has_editor:
            print("✅ [步骤 3 就绪] 角色创建编辑器已就绪")
            return

        print("ℹ️ [步骤 3 检查] 编辑器或已展示，直接进入下一步...")

    def step4_input_prompt_and_name_character(self, full_prompt: str, prompt_filename: str):
        """步骤 4：输入框输入提示词，同时命名角色名，点击开始生成"""
        # 核心铁律：网页端角色名称统一使用提示词文件名（如 officer-barney-A-reference-sheet），
        # 做到提示词文件、输出图片与网页端角色名称三者 100% 严格一致
        char_display_name = prompt_filename
        print(f"📝 [步骤 4: 输入框输入提示词, 同时命名角色名] 注入提示词并为角色命名: '{char_display_name}' (严格与提示词文件名一致) ...")

        # 1. 尝试提前为角色命名
        self.rename_character(char_display_name)

        # 2. 聚焦并清空输入框 (ProseMirror / textarea)
        self.cdp.evaluate_js(
            self.session_id,
            """
            (() => {
                const pm = document.querySelector('.ProseMirror, textarea');
                if (!pm) return false;
                pm.focus();
                if (pm.tagName === 'TEXTAREA') {
                    pm.value = '';
                } else {
                    const range = document.createRange();
                    range.selectNodeContents(pm);
                    const sel = window.getSelection();
                    sel.removeAllRanges();
                    sel.addRange(range);
                }
                return true;
            })()
            """
        )
        time.sleep(0.3)

        # 清空默认内容
        self.cdp.send_cmd(
            "Input.dispatchKeyEvent",
            {"type": "keyDown", "key": "Backspace", "code": "Backspace", "windowsVirtualKeyCode": 8},
            session_id=self.session_id
        )
        self.cdp.send_cmd(
            "Input.dispatchKeyEvent",
            {"type": "keyUp", "key": "Backspace", "code": "Backspace", "windowsVirtualKeyCode": 8},
            session_id=self.session_id
        )
        time.sleep(0.3)

        # 注入纯英文提示词
        self.cdp.send_cmd(
            "Input.insertText",
            {"text": full_prompt},
            session_id=self.session_id
        )
        time.sleep(1.0)

        # 再次确认命名（防止某些界面在提示词输入后才渲染标题输入框）
        self.rename_character(char_display_name)

        # 触发 input 事件通知 Angular / React 状态机
        self.cdp.evaluate_js(
            self.session_id,
            "document.querySelector('.ProseMirror, textarea')?.dispatchEvent(new Event('input', { bubbles: true }));"
        )
        time.sleep(0.8)

        # 点击开始生成按钮
        print("🚀 [步骤 4 触发] 点击'开始生成'按钮...")
        clicked_gen = self.cdp.evaluate_js(
            self.session_id,
            """
            (() => {
                const btn = document.querySelector('button[aria-label*="开始生成"], button.generate-icon-button, button[aria-label*="Generate"]');
                if (btn) {
                    btn.click();
                    return true;
                }
                // 兜底找包含"生成"或"Generate"文字的按钮
                const allBtns = Array.from(document.querySelectorAll('button'));
                const gBtn = allBtns.find(b => {
                    const txt = (b.innerText || '').trim();
                    return txt === '生成' || txt === '开始生成' || txt.toLowerCase() === 'generate';
                });
                if (gBtn) {
                    gBtn.click();
                    return true;
                }
                return false;
            })()
            """
        )
        print(f"✅ [步骤 4 完成] 提示词与角色名已提交生成 (按钮点击: {clicked_gen})")
        time.sleep(2.0)


    def step4b_click_fullbody_and_inject_prompt(self, fullbody_prompt: str) -> bool:
        """步骤 4b：点击「生成全身像」按钮，等待参考图注入，追加 Full Body Prompt，点击生成
        
        注意：Flow 自动在输入框中插入人像参考图 token，本函数在 token 之后追加文本。
        绝对不能清空输入框，否则会删除参考图！
        """
        print("\n🔷 [步骤 4b] 正在点击「生成全身像」按钮...")

        # 1. 查找并点击「生成全身像」按钮
        clicked = self.cdp.evaluate_js(
            self.session_id,
            """
            (() => {
                const btns = Array.from(document.querySelectorAll('button, [role="button"]'));
                const btn = btns.find(el => {
                    const txt = (el.innerText || el.textContent || '').trim();
                    const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                    return txt.includes('生成全身像') || aria.includes('full body') || 
                           txt.toLowerCase().includes('full body') || txt.includes('全身像');
                });
                if (btn) { btn.click(); return true; }
                return false;
            })()
            """
        )
        if not clicked:
            print("⚠️ [步骤 4b] 未找到「生成全身像」按钮，请检查是否已完成第一轮人像生成！")
            return False
        print("   ✓ 已点击「生成全身像」按钮")

        # 2. 等待输入框中出现参考图 token（最多等 10s）
        print("   ⏳ 等待 Flow 自动注入人像参考图 token...")
        ref_injected = False
        for _ in range(20):
            time.sleep(0.5)
            has_ref = self.cdp.evaluate_js(
                self.session_id,
                """
                (() => {
                    // 检查输入框内是否有图片 token / 附件 / chip
                    const chips = document.querySelectorAll(
                        '[class*="chip"], [class*="attachment"], [class*="reference"], [class*="token"], img[class*="thumb"]'
                    );
                    const prosemirror = document.querySelector('.ProseMirror, [contenteditable="true"]');
                    const hasImg = prosemirror && prosemirror.querySelector('img');
                    return chips.length > 0 || !!hasImg;
                })()
                """
            )
            if has_ref:
                ref_injected = True
                break
        if ref_injected:
            print("   ✓ 人像参考图已注入输入框")
        else:
            print("   ⚠️ 未检测到参考图注入，仍继续追加提示词...")

        # 3. 将光标移至输入框末尾，并使用 CDP 原生 Input.insertText 追加提示词
        self.cdp.evaluate_js(
            self.session_id,
            """
            (() => {
                const editor = document.querySelector('.ProseMirror, [contenteditable="true"]');
                if (!editor) return false;
                editor.focus();
                const range = document.createRange();
                range.selectNodeContents(editor);
                range.collapse(false);
                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
                return true;
            })()
            """
        )
        time.sleep(0.3)
        self.cdp.send_cmd(
            "Input.insertText",
            {"text": "\n\n" + fullbody_prompt},
            session_id=self.session_id
        )
        time.sleep(0.5)
        self.cdp.evaluate_js(
            self.session_id,
            "document.querySelector('.ProseMirror, [contenteditable=\"true\"]')?.dispatchEvent(new Event('input', { bubbles: true }));"
        )
        print("   ✓ Full Body Prompt 已追加到输入框")
        time.sleep(1.0)

        # 4. 点击「开始生成」（精确选择器，并严格排除“全身像”、“人像”等前置按钮）
        gen_clicked = self.cdp.evaluate_js(
            self.session_id,
            """
            (() => {
                // 优先使用专用类名或属性
                const preciseBtn = document.querySelector('button[aria-label*="开始生成"], button.generate-icon-button, button[aria-label*="Generate"]');
                if (preciseBtn && !preciseBtn.disabled) {
                    preciseBtn.click();
                    return true;
                }
                // 备选：查找包含生成文本但排除“全身”、“人像”的按钮
                const btns = Array.from(document.querySelectorAll('button, [role="button"]'));
                const btn = btns.find(el => {
                    const txt = (el.innerText || el.textContent || '').trim();
                    const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                    if (txt.includes('全身') || aria.includes('full body') || txt.includes('人像') || aria.includes('portrait')) {
                        return false;
                    }
                    const matchTxt = txt === '生成' || txt === '开始生成' || txt.toLowerCase() === 'generate';
                    const matchAria = aria === '生成' || aria === '开始生成' || aria === 'generate' || aria.includes('开始生成');
                    return (matchTxt || matchAria) && !el.disabled;
                });
                if (btn) { btn.click(); return true; }
                return false;
            })()
            """
        )
        if gen_clicked:
            print("   ✓ 已点击「开始生成」，等待第2轮全身像生成...")
        else:
            print("   ⚠️ 未能找到「开始生成」按钮，请手动点击！")
        return gen_clicked

    def step7_select_voice(self, voice_name: str, voice_style: str) -> bool:
        """步骤 7：点击「选择语音」弹窗 → 选定音色 → 填入风格提示词 → 添加到角色"""
        if not voice_name:
            print("ℹ️ [步骤 7] 未指定音色，跳过语音配置。")
            return False

        print(f"\n🎙️ [步骤 7] 正在配置音色: {voice_name}")

        # 1. 查找并点击「选择语音」按钮
        clicked = self.cdp.evaluate_js(
            self.session_id,
            """
            (() => {
                const btns = Array.from(document.querySelectorAll('button, [role="button"], a'));
                const btn = btns.find(el => {
                    const txt = (el.innerText || el.textContent || '').trim();
                    const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                    return txt.includes('选择语音') || (txt.includes('语音') && !txt.includes('演绎')) ||
                           aria.includes('voice') || txt.toLowerCase().includes('select voice');
                });
                if (btn) { btn.click(); return true; }
                return false;
            })()
            """
        )
        if not clicked:
            print("⚠️ [步骤 7] 未找到「选择语音」按钮！")
            return False
        print("   ✓ 已打开语音选择弹窗")
        time.sleep(2.0)  # 等待弹窗渲染

        # 2. 在弹窗搜索框中精准搜索目标音色
        search_res = self.cdp.evaluate_js(
            self.session_id,
            f"""
            (() => {{
                const searchInputs = Array.from(document.querySelectorAll('input[type="text"], input[type="search"], input'));
                const sInp = searchInputs.find(inp => {{
                    const ph = (inp.getAttribute('placeholder') || '').toLowerCase();
                    const aria = (inp.getAttribute('aria-label') || '').toLowerCase();
                    return ph.includes('搜索') || ph.includes('search') || aria.includes('搜索') || aria.includes('search');
                }});
                if (sInp) {{
                    sInp.focus();
                    sInp.value = '{voice_name}';
                    sInp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    sInp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    return true;
                }}
                return false;
            }})()
            """
        )
        time.sleep(1.0)

        # 3. 选定匹配的音色条目（分发完整鼠标与指针事件）
        voice_clicked = self.cdp.evaluate_js(
            self.session_id,
            f"""
            (() => {{
                const voiceName = '{voice_name}'.toLowerCase();
                const items = Array.from(document.querySelectorAll(
                    'button.asset-item, [role="option"], [class*="asset-item"], [class*="voice"]'
                ));
                const item = items.find(el => {{
                    const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                    return txt.includes(voiceName);
                }}) || items[0];

                if (item) {{
                    item.scrollIntoView({{ block: 'nearest' }});
                    const clickTarget = item.querySelector('*') || item;
                    ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(evtType => {{
                        const evt = new MouseEvent(evtType, {{ bubbles: true, cancelable: true, view: window }});
                        clickTarget.dispatchEvent(evt);
                    }});
                    item.click();
                    return true;
                }}
                return false;
            }})()
            """
        )
        if voice_clicked:
            print(f"   ✓ 已选择音色: {voice_name}")
        else:
            print(f"   ⚠️ 未能在列表中找到音色 '{voice_name}'")

        time.sleep(1.0)

        # 4. 填入音色风格提示词
        if voice_style:
            style_json = json.dumps(voice_style)
            style_filled = self.cdp.evaluate_js(
                self.session_id,
                f"""
                (() => {{
                    const textarea = document.querySelector('textarea');
                    if (textarea) {{
                        textarea.focus();
                        textarea.value = {style_json};
                        textarea.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        textarea.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        return true;
                    }}
                    return false;
                }})()
                """
            )
            if style_filled:
                print(f"   ✓ 已填入风格提示词")
            else:
                print(f"   ⚠️ 未找到风格提示词输入框: {voice_style}")

        time.sleep(1.0)

        # 5. 精准点击「添加到角色」按钮
        added = self.cdp.evaluate_js(
            self.session_id,
            """
            (() => {
                const btn = document.querySelector('button.detail-add-to-prompt-btn') ||
                            Array.from(document.querySelectorAll('button, [role="button"]')).find(el => {
                                const txt = (el.innerText || el.textContent || '').trim();
                                const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                                return txt === '添加到角色' || txt.includes('添加到角色') ||
                                       txt.toLowerCase() === 'add to character' ||
                                       aria.includes('add to character') || aria.includes('添加到角色');
                            });
                if (btn) {
                    btn.scrollIntoView({ block: 'center' });
                    btn.click();
                    return true;
                }
                return false;
            })()
            """
        )
        if added:
            print(f"   ✓ 已点击「添加到角色」，音色配置完成")
        else:
            print(f"   ℹ️ 「添加到角色」已生效或弹窗已完成更新")
        time.sleep(1.5)
        return True

    def rename_character(self, target_name: str = None):
        """在 Google Flow 角色页面中，点击铅笔编辑按钮并修改角色名称"""
        name_to_set = target_name or getattr(self, "prompt_filename", None) or self.char_name
        print(f"🏷️ [角色命名] 正在修改角色名称为: '{name_to_set}' ...")
        res = self.cdp.evaluate_js(
            self.session_id,
            f"""
            (async () => {{
                // 1. 查找铅笔编辑按钮或未命名的标题元素
                const pencilBtn = Array.from(document.querySelectorAll('button, [role="button"]')).find(el => {{
                    const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                    const txt = (el.innerText || '').trim();
                    return aria.includes('edit') || aria.includes('编辑') || aria.includes('name') || aria.includes('名称') ||
                           txt === 'edit' || txt.includes('edit');
                }}) || document.querySelector('button.pencil-button, button[aria-label*="Edit name"], button[aria-label*="编辑名称"]');

                const titleNode = Array.from(document.querySelectorAll('h1, h2, h3, .title, span, div, p')).find(el => {{
                    const t = (el.innerText || '').trim();
                    return (t === '未命名的角色' || t === '未命名角色' || t.toLowerCase() === 'untitled character' || t.toLowerCase() === 'untitled') && el.children.length === 0;
                }});

                if (pencilBtn) {{
                    pencilBtn.click();
                }} else if (titleNode) {{
                    titleNode.click();
                }}

                // 2. 异步等待输入框渲染
                let input = null;
                for (let i = 0; i < 20; i++) {{
                    await new Promise(r => setTimeout(r, 150));
                    input = document.querySelector('input.editable-text-input, input.name-input, input[aria-label*="名称"], input[placeholder*="名称"], input[aria-label*="Name"], input[aria-label*="可编辑文本"], input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"])');
                    if (input) break;
                }}

                if (!input) {{
                    const currentTitle = Array.from(document.querySelectorAll('h1, h2, h3, .title, span')).some(el => (el.innerText || '').includes('{name_to_set}'));
                    if (currentTitle) {{
                        return {{ success: true, name: '{name_to_set}' }};
                    }}
                    return {{ success: false, reason: '未能在界面中定位到角色名称输入框' }};
                }}

                // 3. 填入角色名称并触发响应式 input / change 事件
                input.focus();
                input.value = '{name_to_set}';
                input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                input.dispatchEvent(new Event('change', {{ bubbles: true }}));

                // 4. 触发回车与失焦以保存
                input.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }}));
                input.dispatchEvent(new KeyboardEvent('keyup', {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }}));
                await new Promise(r => setTimeout(r, 300));
                input.blur();
                await new Promise(r => setTimeout(r, 300));

                return {{
                    success: true,
                    name: input.value
                }};
            }})()
            """
        )
        if res and res.get("success"):
            print(f"✅ [角色命名成功] 角色名称已设置为: '{res.get('name')}'")
            time.sleep(1.0)
            return True
        else:
            print(f"ℹ️ [角色命名状态] {res.get('reason') if res else '保持当前名称'}")
            return False

    def finalize_character_save(self):
        """点击右上角'完成'按钮，将角色永久保存至 Google Flow 项目库中"""
        clicked = self.cdp.evaluate_js(
            self.session_id,
            """
            (() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const doneBtn = btns.find(b => {
                    const txt = (b.innerText || '').trim();
                    return txt === '完成' || txt.toLowerCase() === 'done';
                });
                if (doneBtn && !doneBtn.disabled) {
                    doneBtn.click();
                    return true;
                }
                return false;
            })()
            """
        )
        if clicked:
            print("💾 [角色保存完成] 已点击右上角'完成'按钮，角色已正式保存至项目库！")
            time.sleep(2.0)
            return True
        return False

    def step5_and_6_wait_and_handle_result(self, prompt_filename: str, max_wait_seconds: int = 240, output_suffix: str = ""):
        """步骤 5：等待生成完成；步骤 6：如果失败点击重新生成，如果成功下载到对应目录（output_suffix 控制后缀，如 -portrait / -fullbody）"""
        print(f"⏳ [步骤 5: 等待生成完成] 正在监控单图生成状态 (最大等待: {max_wait_seconds}s)...")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        dest_path = self.output_dir / f"{prompt_filename}{output_suffix}.png"

        start_time = time.time()
        last_log = 0
        retry_count = 0
        max_retries = 3

        portrait_file = self.output_dir / f"{prompt_filename}_portrait.png"
        if not portrait_file.exists():
            portrait_file = self.output_dir / f"{prompt_filename}-portrait.png"
        portrait_md5 = None
        if output_suffix in ("_fullbody", "-fullbody") and portrait_file.exists():
            import hashlib
            portrait_md5 = hashlib.md5(portrait_file.read_bytes()).hexdigest()

        while time.time() - start_time < max_wait_seconds:
            elapsed = int(time.time() - start_time)
            if elapsed - last_log >= 10:
                print(f"   ... 已等待 {elapsed} 秒，生成进行中 ...")
                last_log = elapsed

            # 刚启动生成的前 8 秒，绝不提前判定完成（防止误抓上一轮遗留的下载按钮与状态）
            if elapsed < 8:
                time.sleep(1.0)
                continue

            # 如果是第 2 轮全身像，尝试点击界面上最新生成的版本卡片/缩略图，确保大图展示区切换至最新图片
            if output_suffix in ("_fullbody", "-fullbody"):
                self.cdp.evaluate_js(
                    self.session_id,
                    """
                    (() => {
                        const thumbs = Array.from(document.querySelectorAll('[class*="version"], [class*="thumbnail"], [class*="history"] img, button img'));
                        if (thumbs.length > 1) {
                            const lastThumb = thumbs[thumbs.length - 1];
                            lastThumb.click();
                        }
                    })()
                    """
                )

            # -------------------------------------------------------------
            # 步骤 6 成功分支（优先检测）：如果已生成完毕，直接下载并保存
            # -------------------------------------------------------------
            # 将排除库中的 URL 标准化为纯路径（忽略动态 query 参数）
            exclude_paths = [u.split("?")[0] for u in self.downloaded_img_srcs if u]
            exclude_json = json.dumps(exclude_paths)
            success_check = self.cdp.evaluate_js(
                self.session_id,
                f"""
                (() => {{
                    // 1. 查找下载按钮
                    const downloadBtn = Array.from(document.querySelectorAll('button, a')).find(el => {{
                        const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                        const text = (el.innerText || '').toLowerCase();
                        return aria.includes('下载') || aria.includes('download') || text.includes('下载') || text.includes('download');
                    }});

                    // 1b. 查找强完成信标：是否有「生成全身像」或「选择语音」按钮
                    const hasFullbodyBtn = Array.from(document.querySelectorAll('button, [role="button"]')).some(b => {{
                        const t = (b.innerText || b.textContent || '').trim();
                        const a = (b.getAttribute('aria-label') || '').trim();
                        return t.includes('生成全身像') || t.toLowerCase().includes('generate full body') ||
                               a.includes('生成全身像') || a.toLowerCase().includes('generate full body');
                    }});
                    const hasVoiceBtn = Array.from(document.querySelectorAll('button, [role="button"]')).some(b => {{
                        const t = (b.innerText || b.textContent || '').trim();
                        return t.includes('选择语音') || t.toLowerCase().includes('select voice');
                    }});
                    
                    // 2. 精确查找 Flow 生成的高清图片 (严格排除头像、小图标与已下载历史图片)
                    const excludeList = {exclude_json};
                    const flowImgs = Array.from(document.querySelectorAll('img')).filter(img => {{
                        const src = img.src || '';
                        const cleanPath = src.split('?')[0];
                        const isProfile = src.includes('profile') || src.includes('avatar') || src.includes('gstatic');
                        const isFlowImg = src.includes('flow-content.google') || img.classList.contains('preview-image') || src.startsWith('blob:') || src.includes('googleusercontent');
                        const hasSize = (img.naturalWidth > 200 || img.width > 200);
                        return isFlowImg && !isProfile && hasSize && !excludeList.includes(cleanPath);
                    }});

                    // 3. 检查是否有真实的进行中进度条 (如 1%~99%)
                    const text = document.body.innerText || '';
                    let isGenerating = false;
                    const match = text.match(/([0-9]{{1,2}})%/);
                    if (match) {{
                        const val = parseInt(match[1], 10);
                        if (val > 0 && val < 100) {{
                            isGenerating = true;
                        }}
                    }}

                    // 强完成信标判定：如果出现了生成全身像按钮、选择语音按钮，或者下载按钮且有图，则必定已完成
                    const stronglyCompleted = hasFullbodyBtn || (hasVoiceBtn && flowImgs.length > 0) || (!!downloadBtn && flowImgs.length > 0);

                    let chosenImg = flowImgs.length > 0 ? flowImgs[flowImgs.length - 1].src : null;
                    if (!chosenImg && stronglyCompleted) {{
                        const fallbackImgs = Array.from(document.querySelectorAll('img')).filter(img => {{
                            const src = img.src || '';
                            return src.includes('flow-content.google') && (img.naturalWidth > 200 || img.width > 200);
                        }});
                        if (fallbackImgs.length > 0) {{
                            chosenImg = fallbackImgs[fallbackImgs.length - 1].src;
                        }}
                    }}

                    return {{
                        hasDownloadBtn: !!downloadBtn,
                        hasFullbodyBtn: hasFullbodyBtn,
                        hasVoiceBtn: hasVoiceBtn,
                        stronglyCompleted: stronglyCompleted,
                        isGenerating: isGenerating && !stronglyCompleted,
                        imgCount: flowImgs.length,
                        firstImgSrc: chosenImg
                    }};
                }})()
                """
            )

            if success_check and (success_check.get("stronglyCompleted") or (not success_check.get("isGenerating") and success_check.get("firstImgSrc"))):
                img_src = success_check.get("firstImgSrc")
                print(f"\n🎉 [步骤 6: 成功捕获] 检测到图片已生成完毕！")
                print(f"🔍 [图片检测详情] img_src: {img_src[:120] if img_src else None} | 已排除库: {len(self.downloaded_img_srcs)} 个")

                # 优先直接使用带签名的 CDN 直链下载完整高清原图
                if img_src and (img_src.startswith("http://") or img_src.startswith("https://")):
                    try:
                        print(f"💾 [步骤 6 下载保存] 正在下载图片至: {dest_path}")
                        req = urllib.request.Request(img_src, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                        with urllib.request.urlopen(req, timeout=10) as resp:
                            data = resp.read()
                        if len(data) > 10000:
                            if portrait_md5:
                                import hashlib
                                cur_md5 = hashlib.md5(data).hexdigest()
                                if cur_md5 == portrait_md5:
                                    print("   ⚠️ 捕获到与人像相同的旧图，等待全身像完全加载...")
                                    time.sleep(2.0)
                                    continue
                            dest_path.write_bytes(data)
                            file_size = dest_path.stat().st_size
                            self.downloaded_img_srcs.add(img_src.split("?")[0])
                            print(f"✅ [步骤 6 完成 · 落盘成功] 图片已保存至: {dest_path} (大小: {file_size} 字节)")
                            time.sleep(0.5)
                            return True
                    except Exception as e:
                        print(f"⚠️ 直链直接下载失败 ({e})，将尝试通过浏览器上下文读取...")

                # 次选：在浏览器上下文内直接 fetch 并转换 Base64
                if img_src:
                    try:
                        print(f"💾 [步骤 6 下载保存] 正在通过浏览器上下文读取图片...")
                        b64_data = self.cdp.evaluate_js(
                            self.session_id,
                            f"""
                            (async () => {{
                                try {{
                                    const res = await fetch('{img_src}');
                                    const blob = await res.blob();
                                    return await new Promise((resolve, reject) => {{
                                        const reader = new FileReader();
                                        reader.onloadend = () => {{
                                            const base64 = reader.result.split(',')[1];
                                            resolve(base64);
                                        }};
                                        reader.onerror = reject;
                                        reader.readAsDataURL(blob);
                                    }});
                                }} catch (e) {{
                                    return null;
                                }}
                            }})()
                            """
                        )
                        if b64_data:
                            import base64
                            raw = base64.b64decode(b64_data)
                            if len(raw) > 10000:
                                dest_path.write_bytes(raw)
                                file_size = dest_path.stat().st_size
                                self.downloaded_img_srcs.add(img_src)
                                print(f"✅ [步骤 6 完成 · 落盘成功] 图片已保存至: {dest_path} (大小: {file_size} 字节)")
                                time.sleep(0.5)
                                return True
                    except Exception as e:
                        print(f"⚠️ 浏览器上下文读取图片失败 ({e})，尝试直接下载...")

                # 触发界面下载按钮
                clicked_dl = self.cdp.evaluate_js(
                    self.session_id,
                    """
                    (() => {
                        const downloadBtn = Array.from(document.querySelectorAll('button, a')).find(el => {
                            const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                            const text = (el.innerText || '').toLowerCase();
                            return aria.includes('下载') || aria.includes('download') || text.includes('下载') || text.includes('download');
                        });
                        if (downloadBtn) {
                            downloadBtn.click();
                            return true;
                        }
                        return false;
                    })()
                    """
                )
                if clicked_dl:
                    print(f"📥 [步骤 6 下载触发] 已点击界面的下载按钮，请检查浏览器默认下载目录或将文件移动至: {dest_path}")
                    return True

            # -------------------------------------------------------------
            # 步骤 6 异常分支（仅在真正报错时触发）：
            # 必须存在明确的错误警报文本，才允许尝试点击重新生成
            # 严禁在无报错状态下误触界面的常规"重新生成"操作按钮
            # -------------------------------------------------------------
            fail_check = self.cdp.evaluate_js(
                self.session_id,
                """
                (() => {
                    // 1. 严格查找明确的错误警报或提示文本
                    const errorMsg = Array.from(document.querySelectorAll('.error-message, .alert, [role="alert"], mat-error, div[class*="error"], span[class*="error"], p[class*="error"]')).find(el => {
                        const txt = (el.innerText || '').trim();
                        return txt.includes('失败') || txt.includes('出错了') || txt.toLowerCase().includes('failed') || txt.toLowerCase().includes('error');
                    });

                    if (!errorMsg) {
                        return { failed: false };
                    }

                    // 2. 只有在明确检测到错误提示的前提下，才查找重试/重新生成按钮
                    const btns = Array.from(document.querySelectorAll('button, a, [role="button"]'));
                    const retryBtn = btns.find(el => {
                        const txt = (el.innerText || '').trim();
                        const aria = (el.getAttribute('aria-label') || '').trim();
                        return txt.includes('重试') || txt.includes('重新生成') ||
                               aria.includes('重试') || aria.includes('重新生成') ||
                               txt.toLowerCase().includes('retry') || txt.toLowerCase().includes('regenerate') ||
                               aria.toLowerCase().includes('retry') || aria.toLowerCase().includes('regenerate');
                    });

                    if (retryBtn) {
                        retryBtn.click();
                        return { failed: true, clickedRetry: true, msg: errorMsg.innerText.trim() };
                    }
                    return { failed: true, clickedRetry: false, msg: errorMsg.innerText.trim() };
                })()
                """
            )

            if fail_check and fail_check.get("failed"):
                if fail_check.get("clickedRetry"):
                    retry_count += 1
                    print(f"\n⚠️ [步骤 6: 失败重试] 检测到错误提示 ({fail_check.get('msg')})，已触发重试 (第 {retry_count} 次重试)...")
                    if retry_count >= max_retries:
                        print(f"❌ [重试达上限] 已重试 {retry_count} 次仍未成功，终止自动重试。")
                        break
                    time.sleep(3.0)
                    start_time = time.time()  # 重置等待计时器
                    last_log = 0
                    continue
                else:
                    print(f"⚠️ [步骤 6: 错误提示] 检测到生成错误但未找到重试按钮: {fail_check.get('msg')}")

            time.sleep(3.0)

        print(f"⚠️ [步骤 5/6 等待超时] 超出最大等待时间 ({max_wait_seconds}s)，请在 Chrome 界面手动查看并下载图片。")
        return False

    # 兼容旧接口的别名方法
    def enter_project(self):
        return self.step1_find_and_enter_project()

    def navigate_to_characters_and_new(self):
        self.step2_find_and_click_right_character_button()
        self.step3_find_and_click_new_character()

    def input_prompt_and_generate(self, full_prompt: str, prompt_filename: str):
        self.step4_input_prompt_and_name_character(full_prompt, prompt_filename)
        self.step5_and_6_wait_and_handle_result(prompt_filename)


# =====================================================================
# 5. 主入口与命令行交互
# =====================================================================

def main():
    parser = argparse.ArgumentParser(description="Google Flow 角色自动化创建工具 (秘密花园项目)")
    parser.add_argument("character_pos", nargs="?", default=None, help="[可选位置参数] 提示词文件名或角色名，如 officer_barney_A_reference_sheet")
    parser.add_argument("--character", type=str, help="提示词文件名或角色英文名，如 officer_barney_A_reference_sheet 或 officer_barney")
    parser.add_argument("--prompt-file", type=str, help="提示词 markdown 文件路径")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG_PATH), help="Chrome 启动配置文件路径")
    parser.add_argument("--port", type=int, default=None, help="Chrome 远程调试端口，覆盖配置文件设置")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Chrome 调试主机，默认 127.0.0.1")
    parser.add_argument("--project", type=str, default=None, help="Google Flow 项目名称，默认取工作区根目录名")
    parser.add_argument("--headless", action="store_true", default=None, help="强制启用无头模式后台静默运行（覆盖配置文件）")
    parser.add_argument("--headed", "--head", action="store_true", default=False, help="强制启用有头窗口模式（显示浏览器窗口，用于人工登录或调试，覆盖配置文件）")
    parser.add_argument("--dry-run", action="store_true", help="仅执行前置环境与提示词检查，不提交生成")

    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    project_name = args.project or repo_root.name

    # 1. 加载 Chrome 配置文件
    config_path = Path(args.config)
    chrome_config = load_chrome_config(config_path)
    if args.port:
        chrome_config["port"] = args.port

    # 命令行参数覆盖 headless 配置
    if args.headed:
        chrome_config["headless"] = False
    elif args.headless is not None:
        chrome_config["headless"] = args.headless

    target_port = int(chrome_config.get("port", 9222))

    # 2. 智能解析并定位提示词文件路径
    # 核心一致性原则：支持提示词文件名、带.md后缀文件名、文件路径或角色目录名
    char_input = args.prompt_file or args.character or args.character_pos
    prompt_file = None

    if char_input:
        input_path = Path(char_input)
        if input_path.is_file():
            prompt_file = input_path.resolve()
        elif (repo_root / char_input).is_file():
            prompt_file = (repo_root / char_input).resolve()
        else:
            clean_name = char_input.strip()
            if clean_name.endswith(".md"):
                clean_name = clean_name[:-3]
            if clean_name.endswith("-zh") or clean_name.endswith("_zh"):
                clean_name = clean_name[:-3]

            prompt_base = repo_root / "01-script" / "prompts" / "image-prompts"

            # 方式 A: 按提示词文件名直接检索 (如 officer_barney_A_reference_sheet.md 或旧格式)
            candidates = [f for f in prompt_base.glob(f"**/{clean_name}.md") if not (f.name.endswith("-zh.md") or f.name.endswith("_zh.md"))]

            # 方式 B: 按角色目录检索时序 A 基准母板 (如 officer_barney)
            if not candidates:
                candidates = [f for f in prompt_base.glob(f"**/{clean_name}/*_A_reference_sheet.md") if not f.name.endswith("_zh.md")]
            if not candidates:
                candidates = [f for f in prompt_base.glob(f"**/{clean_name}/*-A-reference-sheet.md") if not f.name.endswith("-zh.md")]

            # 方式 C: 若传入名称含母板标识则提取角色名前缀匹配
            for rk in ["_A_reference_sheet", "-A-reference-sheet"]:
                if not candidates and rk in clean_name:
                    char_prefix = clean_name.replace(rk, "")
                    candidates = [f for f in prompt_base.glob(f"**/{char_prefix}/*_A_reference_sheet.md") if not f.name.endswith("_zh.md")]
                    if not candidates:
                        candidates = [f for f in prompt_base.glob(f"**/{char_prefix}/*-A-reference-sheet.md") if not f.name.endswith("-zh.md")]

            # 方式 D: 模糊包含匹配
            if not candidates:
                candidates = [f for f in prompt_base.glob(f"**/*{clean_name}*A_reference_sheet.md") if not f.name.endswith("_zh.md")]
            if not candidates:
                candidates = [f for f in prompt_base.glob(f"**/*{clean_name}*A-reference-sheet.md") if not f.name.endswith("-zh.md")]

            if candidates:
                prompt_file = candidates[0]

    if not prompt_file or not prompt_file.exists():
        print(f"❌ [错误] 未能找到对应的基准母板提示词文件！输入: '{char_input}'。请传入有效的提示词文件名或 --prompt-file。")
        sys.exit(1)

    prompt_filename = prompt_file.stem
    char_folder_name = prompt_file.parent.name
    output_dir = repo_root / "02-assets" / "characters" / char_folder_name

    mode_desc = "无头静默 (Headless)" if chrome_config.get("headless", True) else "有头窗口 (Headed)"
    print("\n" + "=" * 65)
    print("🎬 Google Flow 角色母版自动化创建流程启动")
    print(f"   • 项目名称: {project_name}")
    print(f"   • 目标角色: {char_folder_name}")
    print(f"   • 运行模式: {mode_desc}")
    print(f"   • 提示词源: {prompt_file.relative_to(repo_root)}")
    print(f"   • 落盘目录: {output_dir.relative_to(repo_root)} (方案 B)")
    print(f"   • 目标端口: {args.host}:{target_port}")
    print(f"   • 配置文件: {config_path}")
    print("=" * 65 + "\n")

    # 3. 提取提示词（Portrait + Full Body + 音色元数据）
    portrait_prompt = extract_portrait_prompt(prompt_file)
    print(f"📄 [Portrait Prompt 就绪] ({len(portrait_prompt)} 字符)")
    fullbody_prompt = None
    try:
        fullbody_prompt = extract_fullbody_prompt(prompt_file)
        print(f"📄 [Full Body Prompt 就绪] ({len(fullbody_prompt)} 字符)")
    except ValueError:
        print("ℹ️ [提示] 未找到 Full Body Prompt，将跳过第2轮全身像生成（旧格式文件）。")
    voice_meta = extract_voice_metadata(prompt_file)
    if voice_meta.get("voice_name"):
        print(f"🎙️ [音色元数据] {voice_meta['voice_name']} — {voice_meta.get('voice_style', '')[:60]}...")
    else:
        print("ℹ️ [音色元数据] 未配置推荐音色字段，将跳过音色配置步骤。")

    if args.dry_run:
        print("🔍 [Dry-Run 模式] 前置检查与提示词提取均已通过，退出执行。")
        return

    # 4. 直接使用配置命令启动 Chrome 浏览器（不进行端口监听）
    launch_chrome_by_command(chrome_config)
    time.sleep(2.5)

    # 5. 直接直连配置的调试端口建立 CDP 连接（彻底移除端口自适应）
    cdp = ChromeCDPClient(host=args.host, port=target_port)
    try:
        cdp.connect()
        creator = GoogleFlowCharacterCreator(
            cdp=cdp,
            project_name=project_name,
            char_name=char_folder_name,
            prompt_file=prompt_file,
            output_dir=output_dir,
            headless=bool(chrome_config.get("headless", True))
        )
        creator.find_or_open_flow_tab()
        creator.check_login_status_strictly()
        creator.step1_find_and_enter_project()
        creator.step2_find_and_click_right_character_button()
        creator.step3_find_and_click_new_character()

        # ── 第1轮：人像生成 ───────────────────────────────────────
        creator.step4_input_prompt_and_name_character(portrait_prompt, prompt_filename)
        portrait_ok = creator.step5_and_6_wait_and_handle_result(prompt_filename, output_suffix="_portrait")

        if portrait_ok:
            # ── 人像完成后立即固化角色信息 ───────────────────────
            creator.rename_character(prompt_filename)
            creator.step7_select_voice(
                voice_meta.get("voice_name", ""),
                voice_meta.get("voice_style", "")
            )

            # ── 第2轮：全身像生成 ─────────────────────────────────
            if fullbody_prompt:
                creator.step4b_click_fullbody_and_inject_prompt(fullbody_prompt)
                creator.step5_and_6_wait_and_handle_result(prompt_filename, output_suffix="_fullbody")
            else:
                print("⏭️ [跳过] 无 Full Body Prompt，不执行第2轮生成。")
        else:
            print("⚠️ [警告] 第1轮人像生成未成功，跳过改名/音色/全身像步骤。")

        # ── 完成 ──────────────────────────────────────────────────
        creator.finalize_character_save()
        print("\n✨ Google Flow 角色自动化创建流程全部执行完毕！\n")
    finally:
        cdp.close()


if __name__ == "__main__":
    main()
