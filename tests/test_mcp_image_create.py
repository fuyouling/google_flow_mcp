"""
通过 MCP Python 客户端测试 image_create 工具
用途：验证提示词输入及图像生成流程

运行方式:
    cd /home/ubuntu/google_flow_mcp
    uv run python tests/test_mcp_image_create.py
"""

import asyncio
import io
import json
import sys
import time
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ── 编码修复（Windows GBK 终端） ──────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() in ("gbk", "gb2312", "cp936"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── 测试参数 ─────────────────────────────────────────────
PROJECT_ID   = "41ffbc19-48f6-44c0-8b2a-4745e26ddc74"  # qqqq
PROMPT       = "Mary Lennox 和 Officer Barney 正在吃饭"
IMAGE_NAME   = "SE_06"
ASSETS       = "Mary Lennox,Officer Barney"
ASPECT_RATIO = "16:9"
MODEL_NAME   = "Nano Banana Pro"
QUANTITY     = 1
# ─────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SERVER_PARAMS = StdioServerParameters(
    command="uv",
    args=["--directory", str(PROJECT_ROOT), "run", "google-flow-mcp"],
)


async def poll_status(session: ClientSession, job_id: str, max_wait: int = 120) -> dict:
    """轮询 image_status 直到任务完成或超时"""
    print(f"\n⏳ 轮询任务状态 (job_id={job_id[:8]}...)，最多等待 {max_wait}s")
    for elapsed in range(0, max_wait, 5):
        await asyncio.sleep(5)
        result = await session.call_tool("image_status", arguments={"job_id": job_id})
        raw = result.content[0].text
        state = json.loads(raw)
        status = state.get("status", "unknown")
        print(f"  [{elapsed+5:3d}s] status={status}  msg={state.get('message', state.get('error', ''))}")

        if status in ("completed", "error"):
            return state

    return {"status": "timeout", "error": f"超过 {max_wait}s 未完成"}


async def main():
    print("=" * 60)
    print("  MCP image_create 集成测试")
    print("=" * 60)
    print(f"  project_id : {PROJECT_ID}")
    print(f"  prompt     : {PROMPT}")
    print(f"  image_name : {IMAGE_NAME}")
    print(f"  assets     : {ASSETS}")
    print(f"  aspect_ratio: {ASPECT_RATIO}")
    print(f"  model_name : {MODEL_NAME}")
    print(f"  quantity   : {QUANTITY}")
    print("=" * 60)

    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. 列出工具，确认 image_create / image_status 已注册
            tools_resp = await session.list_tools()
            tool_names = [t.name for t in tools_resp.tools]
            print(f"\n✅ 已注册工具: {tool_names}")

            for required in ("image_create", "image_status"):
                assert required in tool_names, f"❌ 工具 {required} 未注册！"

            # 2. 调用 image_create
            print(f"\n🚀 调用 image_create...")
            t0 = time.time()
            create_result = await session.call_tool(
                "image_create",
                arguments={
                    "project_id":   PROJECT_ID,
                    "prompt":       PROMPT,
                    "assets":       ASSETS,
                    "image_name":   IMAGE_NAME,
                    "aspect_ratio": ASPECT_RATIO,
                    "model_name":   MODEL_NAME,
                    "quantity":     QUANTITY,
                },
            )
            raw_create = create_result.content[0].text
            print(f"   返回: {raw_create}")
            resp = json.loads(raw_create)

            assert resp.get("success"), f"❌ image_create 返回失败: {resp}"
            job_id = resp["job_id"]
            print(f"   ✅ job_id = {job_id}")

            # 3. 轮询 image_status
            final = await poll_status(session, job_id, max_wait=120)
            elapsed = time.time() - t0
            print(f"\n{'='*60}")
            # Format printable details (truncate base64 to avoid flooding terminal)
            printable_final = dict(final)
            if printable_final.get("image_base64"):
                printable_final["image_base64"] = f"<base64 data: {len(printable_final['image_base64'])} chars>"
            if printable_final.get("base64"):
                printable_final["base64"] = f"<base64 data: {len(printable_final['base64'])} chars>"

            is_ok = (
                final.get("status") == "completed" 
                and final.get("rename_success", True)
                and bool(final.get("image_url"))
                and bool(final.get("image_base64"))
            )
            if is_ok:
                print(f"✅ 测试通过！耗时 {elapsed:.1f}s")
                print(f"   详情: {json.dumps(printable_final, indent=2, ensure_ascii=False)}")
            else:
                print(f"❌ 测试失败！耗时 {elapsed:.1f}s")
                print(f"   详情: {json.dumps(printable_final, indent=2, ensure_ascii=False)}")
            print("=" * 60)

            return is_ok


if __name__ == "__main__":
    ok = asyncio.run(main())
    exit(0 if ok else 1)
