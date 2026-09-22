r"""
通过 MCP Python 客户端测试 image_create 工具及图片下载
用途：验证提示词输入、参考素材、模型选择、图像生成及本地下载（1K/2K）重命名保存流程

运行方式:
    cd C:\dev\ai\mcp\google_flow_mcp
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
PROJECT_NAME   = "qqqq"  # 目标项目 ID (留空 "" 则自动选用最近访问的项目)
PROMPT       = "A Cyanopica cyanus flies in the sky"
IMAGE_NAME   = "Cyanopica cyanus"
ASSETS       = ""
ASPECT_RATIO = "16:9"
MODEL_NAME   = "Nano Banana Pro"
QUANTITY     = 1
DOWNLOAD     = "2K"              # 可选: "1K", "2K"，留空 "" 则不自动下载
MAX_WAIT     = 180               # 最多等待 180s (3分钟)
# ─────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SERVER_PARAMS = StdioServerParameters(
    command="uv",
    args=["--directory", str(PROJECT_ROOT), "run", "google-flow-mcp"],
)


async def poll_status(session: ClientSession, job_id: str, max_wait: int = MAX_WAIT) -> dict:
    """轮询 image_status 直到任务完成或超时"""
    print(f"\n⏳ 轮询任务状态 (job_id={job_id[:8]}...)，最多等待 {max_wait}s", flush=True)
    for elapsed in range(0, max_wait, 5):
        await asyncio.sleep(5)
        result = await session.call_tool("image_status", arguments={"job_id": job_id})
        raw = result.content[0].text
        state = json.loads(raw)
        status = state.get("status", "unknown")
        progress = state.get("progress", state.get("progress_percent", ""))
        prog_str = f"({progress}%)" if progress else ""
        print(f"  [{elapsed+5:3d}s] status={status} {prog_str}  msg={state.get('message', state.get('error', ''))}", flush=True)

        if state.get("is_finished") or status in ("completed", "completed_with_rename_warning", "completed_with_download_warning", "error"):
            return state

    return {"status": "timeout", "error": f"超过 {max_wait}s 未完成"}


async def main():
    print("=" * 60)
    print("  MCP image_create 集成测试")
    print("=" * 60)
    print(f"  project_name   : {PROJECT_NAME!r} (留空自动选用最近项目)")
    print(f"  prompt       : {PROMPT}")
    print(f"  image_name   : {IMAGE_NAME}")
    print(f"  assets       : {ASSETS}")
    print(f"  aspect_ratio : {ASPECT_RATIO}")
    print(f"  model_name   : {MODEL_NAME}")
    print(f"  quantity     : {QUANTITY}")
    print(f"  download     : {DOWNLOAD}")
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
                    "prompt":       PROMPT,
                    "project_name":   PROJECT_NAME,
                    "assets":       ASSETS,
                    "image_name":   IMAGE_NAME,
                    "aspect_ratio": ASPECT_RATIO,
                    "model_name":   MODEL_NAME,
                    "quantity":     QUANTITY,
                    "download":     DOWNLOAD,
                },
            )
            raw_create = create_result.content[0].text
            print(f"   返回: {raw_create}")
            resp = json.loads(raw_create)

            assert resp.get("success"), f"❌ image_create 返回失败: {resp}"
            job_id = resp["job_id"]
            print(f"   ✅ job_id = {job_id}")

            # 3. 轮询 image_status
            final = await poll_status(session, job_id, max_wait=MAX_WAIT)
            elapsed = time.time() - t0
            print(f"\n{'='*60}")
            # Format printable details (truncate base64 to avoid flooding terminal)
            printable_final = dict(final)
            if printable_final.get("image_base64"):
                printable_final["image_base64"] = f"<base64 data: {len(printable_final['image_base64'])} chars>"
            if printable_final.get("base64"):
                printable_final["base64"] = f"<base64 data: {len(printable_final['base64'])} chars>"

            is_ok = (
                final.get("status") in ("completed", "completed_with_rename_warning", "completed_with_download_warning")
                and final.get("is_finished") is True
                and bool(final.get("image_url") or final.get("image_base64"))
            )
            if is_ok:
                print(f"✅ 测试通过！耗时 {elapsed:.1f}s")
                if final.get("image_local_path"):
                    print(f"   image_local_path: {final.get('image_local_path')}")
                print(f"   详情: {json.dumps(printable_final, indent=2, ensure_ascii=False)}")
            else:
                print(f"❌ 测试失败！耗时 {elapsed:.1f}s")
                print(f"   详情: {json.dumps(printable_final, indent=2, ensure_ascii=False)}")
            print("=" * 60)

            return is_ok


if __name__ == "__main__":
    ok = asyncio.run(main())
    exit(0 if ok else 1)
