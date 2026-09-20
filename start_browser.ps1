<#
.SYNOPSIS
    Google Flow MCP 独立浏览器常驻启动与管理脚本 (PowerShell)

.DESCRIPTION
    复用项目现有配置 (.env 与 browser_config.yaml)，在 9222 端口启动并常驻 Chromium 浏览器。
    启动后后续智能体对话或 MCP 工具调用时将直接连接此窗口，无需反复启动浏览器。

.USAGE
    # 1. 默认启动常驻服务（推荐：前台保持监控，输入 r 刷新，输入 q 退出）
    .\start_browser.ps1

    # 2. 检查当前 9222 端口浏览器运行状态与活动标签页
    .\start_browser.ps1 --status

    # 3. 强制重启（若 9222 端口有残留僵死进程，先清理再启动）
    .\start_browser.ps1 --force

    # 4. 安全关闭 9222 端口的浏览器
    .\start_browser.ps1 --stop

    # 5. 后台模式启动（检测并启动后立即退出当前终端，浏览器保持后台常驻）
    .\start_browser.ps1 --detach

    # 6. 启动并打开指定页面
    .\start_browser.ps1 --url "https://flow.google.com"

.NOTES
    退出控制台交互时：
    - 按 Ctrl+C 退出控制台，浏览器仍会继续在后台运行；
    - 在控制台输入 'q' 并回车，会同时关闭浏览器并退出。
#>

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

Set-Location -Path $PSScriptRoot

if (Test-Path ".venv\Scripts\python.exe") {
    & .venv\Scripts\python.exe src\utils\start_browser.py @ScriptArgs
} else {
    python src\utils\start_browser.py @ScriptArgs
}
