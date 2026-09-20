@echo off
rem ==============================================================================
rem Google Flow MCP 集群管理控制台 (Windows 批处理)
rem
rem 使用方式:
rem   【双击运行】
rem       直接双击 cluster.bat 打开交互菜单 (可一键启动 Worker 或查看状态)
rem
rem   【命令行运行】
rem       cluster.bat worker 192.168.1.100    - 启动从机并连接 Master
rem       cluster.bat 192.168.1.100           - 快捷启动从机
rem       cluster.bat status                  - 查看当前集群状态看板
rem       cluster.bat status -w               - 持续实时刷新监控集群
rem       cluster.bat master                  - 独立启动主节点
rem ==============================================================================

title Google Flow MCP - Cluster Manager
cd /d "%~dp0"

set PYTHON_EXEC=python
if exist ".venv\Scripts\python.exe" (
    set PYTHON_EXEC=.venv\Scripts\python.exe
)

%PYTHON_EXEC% -m google_flow_mcp.cluster.launcher %*

if "%~1"=="" pause
if "%~1"=="worker" pause
