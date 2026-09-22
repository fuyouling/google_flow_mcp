"""
通过 MCP Python 客户端测试 project_list 工具
用途：验证 force_refresh=True 时能从网页抓取最新项目列表

运行方式:
    cd C:\dev\ai\mcp\google_flow_mcp
    uv run python tests/test_mcp_project_list.py
"""

import asyncio
import json
import sys
import io

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ── 编码修复（Windows GBK 终端） ──────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() in ("gbk", "gb2312", "cp936"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from pathlib import Path

# ── MCP 服务器参数 ────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

SERVER_PARAMS = StdioServerParameters(
    command="uv",
    args=["--directory", str(PROJECT_ROOT), "run", "google-flow-mcp"],
)


async def main() -> bool:
    print("=" * 60)
    print("  MCP project_list 集成测试")
    print("  force_refresh=True  →  从网页抓取最新数据")
    print("=" * 60)

    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. 确认 project_list 工具已注册
            tools_resp = await session.list_tools()
            tool_names = [t.name for t in tools_resp.tools]
            print(f"\n✅ 已注册工具: {tool_names}")
            assert "project_list" in tool_names, "❌ 工具 project_list 未注册！"

            # 2. 调用 project_list(force_refresh=True)
            print("\n🚀 调用 project_list(force_refresh=True)...")
            result = await session.call_tool(
                "project_list",
                arguments={"force_refresh": True},
            )

            raw = result.content[0].text
            print(f"\n📦 原始返回:\n{raw}")

            # 3. 解析并验证结果
            # project_list 返回格式：
            #   dict  → {project_name: {"name": ..., "url": ...}, ...}
            #   list  → [{"id": ..., "name": ..., "url": ...}, ...]  (未来可能)
            data = json.loads(raw)

            if isinstance(data, dict) and "error" in data:
                print(f"\n❌ 测试失败！服务端返回错误: {data['error']}")
                return False

            if isinstance(data, dict):
                # 标准格式：{project_name: {name, url}}
                projects = [{"id": pid, **info} for pid, info in data.items()]
            elif isinstance(data, list):
                projects = data
            else:
                print(f"\n❌ 测试失败！未知返回类型: {type(data).__name__}")
                return False

            if not projects:
                print("\n⚠️  项目列表为空，请确认账户下有项目。")
                return False

            print(f"\n✅ 共获取到 {len(projects)} 个项目:")
            for i, proj in enumerate(projects, 1):
                name = proj.get("name") or proj.get("title") or str(proj)
                pid  = proj.get("id") or proj.get("project_name") or ""
                url  = proj.get("url") or ""
                print(f"   {i:2d}. {name}  (id: {pid})")
                if url:
                    print(f"       url: {url}")

            print("\n✅ 测试通过！")
            print("=" * 60)
            return True


if __name__ == "__main__":
    ok = asyncio.run(main())
    exit(0 if ok else 1)
