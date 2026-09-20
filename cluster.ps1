<#
.SYNOPSIS
    Google Flow MCP 集群管理控制台 (PowerShell)

.DESCRIPTION
    统一管理 Google Flow MCP 集群各节点角色:
    - 启动从机节点 (Worker): 连接主控机参与视频/图片生成
    - 查看集群看板 (Status): 实时监控在线机器、任务排队与素材缓存
    - 启动主控中枢 (Master): 独立启动主控调度中枢 (智能体正常添加时已默认启动)

.USAGE
    # 1. 交互式控制台菜单 (双击或直接运行，默认启动从机)
    .\cluster.ps1

    # 2. 启动从机 (Worker)
    .\cluster.ps1 worker 192.168.1.100
    .\cluster.ps1 worker --master http://192.168.1.100:8765 --id worker_pc2 --account acc2@gmail.com
    # 快捷直接传 IP:
    .\cluster.ps1 192.168.1.100

    # 3. 监控集群状态 (Status)
    .\cluster.ps1 status
    .\cluster.ps1 status -w   # 持续自动刷新
    .\cluster.ps1 -w          # 快捷持续刷新

    # 4. 独立启动主节点 (Master，仅在不通过智能体启动且希望独立常驻时使用)
    .\cluster.ps1 master
#>

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

Set-Location -Path $PSScriptRoot

$PythonExec = "python"
if (Test-Path ".venv\Scripts\python.exe") {
    $PythonExec = ".venv\Scripts\python.exe"
}

& $PythonExec -m google_flow_mcp.cluster.launcher @ScriptArgs
