# google_flow_mcp

[![Python Version](https://img.shields.io/badge/python-3.14%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-Standard-orange.svg)](https://modelcontextprotocol.io/)

基于 Model Context Protocol (MCP) 的 Google Agentspace / Flow 网页端操作本地服务。底层借助 DrissionPage 驱动 Chrome 浏览器，复用已登录的用户目录执行 Flow 创建、编辑和触发运行。

## 特性

- 🤖 **MCP 标准协议**：兼容 Claude Desktop、Cursor 等支持 MCP 的 AI 客户端。
- 🌐 **网页自动化**：通过真实浏览器环境操作 Google Flow 页面。
- 🔐 **零密码存储**：复用已有 Chrome 用户数据目录（`chrome_data`），无感免登。
- ⚙️ **浏览器参数集中管理**：`browser_config.yaml` 集中管理所有 Chrome 启动 flags，支持独立开关与跨平台适配。
- ♻️ **浏览器单例模式**：会话生命周期内单例运行，节约系统资源并在进程退出时优雅关闭。

## 目录结构

```
google_flow_mcp/
├── docs/                     # 设计与接口参考文档
├── src/google_flow_mcp/
│   ├── browser/              # 浏览器会话与参数构建
│   ├── models/               # 数据模型与 ToolResponse
│   ├── pages/                # Page Object 页面对象
│   ├── tools/                # MCP 工具实现 (create/edit/run)
│   ├── config.py             # 配置管理
│   └── server.py             # FastMCP 启动入口
├── tests/                    # 单元测试 (pytest + mock)
├── browser_config.yaml       # 浏览器参数配置
├── .env.example              # 环境变量示例
└── pyproject.toml            # 项目配置与依赖声明
```

## 快速上手

### 1. 环境准备

要求 Python ≥ 3.14 及 [uv](https://docs.astral.sh/uv/)：

```bash
# 安装项目依赖并生成虚拟环境
uv sync
```

### 2. 配置环境

复制 `.env.example` 到 `.env` 并调整本地配置：

```bash
cp .env.example .env
```

核心配置说明：
- `CHROME_USER_DATA_DIR`：本地 Chrome 用户数据目录路径（默认 `./chrome_data`）
- `CHROME_PROFILE_DIRECTORY`：用户 Profile，默认为 `Default`
- `CHROME_BINARY_PATH`：指定 Chrome 可执行文件路径（留空则自动探测）
- `BROWSER_CONFIG_PATH`：浏览器启动参数配置文件（默认 `browser_config.yaml`）

### 3. 运行测试

项目内置完整的 Mock 单元测试套件，无需启动真实图形界面即可运行：

```bash
uv run pytest
```

### 4. 启动 MCP 服务

以 stdio 模式启动服务：

```bash
uv run google-flow-mcp
```

### 5. 集成到 Claude Desktop

在 `claude_desktop_config.json` 中添加配置：

```json
{
  "mcpServers": {
    "google-flow": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/google_flow_mcp",
        "run",
        "google-flow-mcp"
      ],
      "env": {
        "CHROME_USER_DATA_DIR": "/path/to/google_flow_mcp/chrome_data",
        "CHROME_PROFILE_DIRECTORY": "Default"
      }
    }
  }
}
```

### 6. 集成到 Antigravity IDE

在工作区根目录（或想要生效的任何目录下）创建 `.agents/mcp_config.json` 文件，并添加如下配置：

```json
{
  "mcpServers": {
    "google-flow-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/google_flow_mcp",
        "run",
        "google-flow-mcp"
      ],
      "env": {
        "CHROME_USER_DATA_DIR": "/path/to/google_flow_mcp/chrome_data",
        "CHROME_PROFILE_DIRECTORY": "Default"
      }
    }
  }
}
```
