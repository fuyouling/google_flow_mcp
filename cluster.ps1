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

    # 5. 后台运行守护进程 (start / stop / restart)
    .\cluster.ps1 start master
    .\cluster.ps1 stop
    .\cluster.ps1 restart master
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

$PidFile = ".cluster.pid"

if ($ScriptArgs.Length -gt 0) {
    $command = $ScriptArgs[0].ToLower()
    
    if ($command -eq "start") {
        $argsToPass = if ($ScriptArgs.Length -gt 1) { $ScriptArgs[1..($ScriptArgs.Length - 1)] } else { @() }
        $argList = @("-m", "google_flow_mcp.cluster.launcher") + $argsToPass
        Write-Host "[*] 正在后台启动集群进程..."
        $process = Start-Process -FilePath $PythonExec -ArgumentList $argList -PassThru -WindowStyle Hidden -RedirectStandardOutput "cluster.log" -RedirectStandardError "cluster_error.log"
        $process.Id | Out-File -FilePath $PidFile -Encoding ascii
        Write-Host "[+] 启动成功！PID: $($process.Id), 日志保存在 cluster.log"
        exit
    }
    elseif ($command -eq "stop") {
        $killedAny = $false
        if (Test-Path $PidFile) {
            $pidStr = (Get-Content $PidFile).Trim()
            if ($pidStr -match '^\d+$') {
                Write-Host "[*] 正在停止后台集群进程 (PID: $pidStr)..."
                Stop-Process -Id $pidStr -Force -ErrorAction SilentlyContinue
                $killedAny = $true
            }
            Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        }
        
        # 兜底：查找并清理所有相关的 python 进程
        $strayProcs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" | Where-Object { $_.CommandLine -match "google_flow_mcp\.cluster\.launcher" }
        foreach ($proc in $strayProcs) {
            Write-Host "[*] 发现残留的集群进程 (PID: $($proc.ProcessId))，正在终止..."
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
            $killedAny = $true
        }

        if ($killedAny) {
            Write-Host "[+] 集群进程已停止。"
        } else {
            Write-Host "未找到运行中的集群进程 (.cluster.pid 不存在，且无对应进程)。"
        }
        exit
    }
    elseif ($command -eq "restart") {
        $argsToPass = if ($ScriptArgs.Length -gt 1) { $ScriptArgs[1..($ScriptArgs.Length - 1)] } else { @() }
        & $PSCommandPath stop
        Start-Sleep -Seconds 2
        & $PSCommandPath start @argsToPass
        exit
    }
}

& $PythonExec -m google_flow_mcp.cluster.launcher @ScriptArgs
