r"""
通过 MCP Python 客户端测试 character_create 工具及图片下载
用途：验证角色创建流程（头像生成、重命名、声音配置、全身像生成、图片自动下载及本地重命名保存）

运行方式:
    cd C:\dev\ai\mcp\google_flow_mcp
    uv run python tests/test_mcp_character_create.py
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
PROJECT_NAME   = "TestProject"  # qqqq
CHARACTER_NAME   = "Test_Hero"
PORTRAIT_PROMPT  = "Medium studio shot of a brave knight in polished steel armor with blue accents. perfectly centered, forward-facing. Captured with a Hasselblad H6D-100c and a 50mm lens. The skin is rendered with biological realism, featuring natural textures. Clamshell lighting with a bottom silver reflector creates a luminous glow. The composition is a head and shoulders shot with clear headroom, ensuring the character's full head is entirely within the frame and not cropped by the top border against a seamless, solid white background."
FULLBODY_PROMPT  = "Full-body character design sheet, featuring a triptych of three different angles: front view, three-quarter view, and back view. High resolution, flat studio lighting, consistent body proportions across all views, solid white background. brave knight in polished steel armor with blue accents"
VOICE_NAME       = ""
VOICE_STYLE      = ""
MODEL_NAME       = "Nano banana pro"
DOWNLOAD         = True
IMAGE_BASE64     = False             # 默认为 False 不返回 base64 格式图片
MAX_WAIT         = 420  # 7 分钟超时 (420s)
# ─────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SERVER_PARAMS = StdioServerParameters(
    command="uv",
    args=["--directory", str(PROJECT_ROOT), "run", "google-flow-mcp"],
)


async def poll_status(session: ClientSession, job_id: str, max_wait: int = MAX_WAIT) -> dict:
    """轮询 character_status 直到任务完成或超时 (最多等待 7 分钟)"""
    print(f"\n⏳ 轮询角色创建状态 (job_id={job_id[:8]}...)，最多等待 {max_wait}s (7分钟)", flush=True)
    for elapsed in range(0, max_wait, 5):
        await asyncio.sleep(5)
        result = await session.call_tool("character_status", arguments={"job_id": job_id})
        raw = result.content[0].text
        state = json.loads(raw)
        status = state.get("status", "unknown")
        progress = state.get("progress", "")
        prog_str = f"({progress}%)" if progress else ""
        print(f"  [{elapsed+5:3d}s] status={status} {prog_str}  msg={state.get('message', state.get('error', ''))}", flush=True)

        if state.get("is_finished") or status in ("completed", "completed_with_download_warning", "error"):
            return state

    return {"status": "timeout", "error": f"超过 {max_wait}s 未完成"}


async def main():
    print("=" * 60)
    print("  MCP character_create 下载功能集成测试")
    print("=" * 60)
    print(f"  project_name      : {PROJECT_NAME}")
    print(f"  character_name  : {CHARACTER_NAME}")
    print(f"  portrait_prompt : {PORTRAIT_PROMPT[:45]}...")
    print(f"  fullbody_prompt : {FULLBODY_PROMPT[:45]}...")
    print(f"  model_name      : {MODEL_NAME}")
    print(f"  download        : {DOWNLOAD}")
    print("=" * 60)

    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. 列出工具，确认 character_create / character_status 已注册
            tools_resp = await session.list_tools()
            tool_names = [t.name for t in tools_resp.tools]
            print(f"\n✅ 已注册工具: {tool_names}")

            for required in ("character_create", "character_status"):
                assert required in tool_names, f"❌ 工具 {required} 未注册！"

            # 2. 调用 character_create
            print(f"\n🚀 调用 character_create (超时限制: 7分钟)...")
            t0 = time.time()
            create_result = await session.call_tool(
                "character_create",
                arguments={
                    "project_name":      PROJECT_NAME,
                    "character_name":  CHARACTER_NAME,
                    "portrait_prompt": PORTRAIT_PROMPT,
                    "fullbody_prompt": FULLBODY_PROMPT,
                    "voice_name":      VOICE_NAME,
                    "voice_style":     VOICE_STYLE,
                    "model_name":      MODEL_NAME,
                    "download":        DOWNLOAD,
                    "image_base64":    IMAGE_BASE64,
                },
            )
            raw_create = create_result.content[0].text
            print(f"   返回: {raw_create}")
            resp = json.loads(raw_create)

            assert resp.get("success"), f"❌ character_create 返回失败: {resp}"
            job_id = resp["job_id"]
            print(f"   ✅ job_id = {job_id}")

            # 3. 轮询 character_status
            final = await poll_status(session, job_id, max_wait=MAX_WAIT)
            elapsed = time.time() - t0
            print(f"\n{'='*60}")

            is_ok = (
                final.get("status") in ("completed", "completed_with_download_warning")
                and final.get("is_finished") is True
            )

            if is_ok:
                print(f"✅ 测试通过！耗时 {elapsed:.1f}s")
                print(f"   portrait_local_path: {final.get('portrait_local_path')}")
                print(f"   fullbody_local_path: {final.get('fullbody_local_path')}")
                print(f"   详情: {json.dumps(final, indent=2, ensure_ascii=False)}")
            else:
                print(f"❌ 测试失败！耗时 {elapsed:.1f}s")
                print(f"   详情: {json.dumps(final, indent=2, ensure_ascii=False)}")
            print("=" * 60)
            time.sleep(10)
            return is_ok


if __name__ == "__main__":
    ok = asyncio.run(main())
    exit(0 if ok else 1)
