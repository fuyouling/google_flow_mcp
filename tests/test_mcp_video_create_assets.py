"""
通过 MCP Python 客户端测试 video_create 工具（素材模式 mode="asset"）
用途：验证视频生成流程中选择素材（如角色 Mary Lennox、Officer Barney）的创建流程及视频下载连接提取

运行方式:
    cd /home/ubuntu/google_flow_mcp
    uv run python tests/test_mcp_video_create_assets.py
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
PROMPT       = "Mary Lennox 和 Officer Barney 正在走廊奔跑"
VIDEO_NAME   = "SE_04_VIDEO_ASSET"
MODEL_NAME   = "Omni 1.1 Flash"  # 可选: "Omni 1.1 Flash", "Veo 3.1 - Lite" 等
MODE         = "asset"           # 素材模式
START_FRAME  = ""                # 素材模式下必须为空
END_FRAME    = ""                # 素材模式下必须为空
ASSETS       = "Mary Lennox,Officer Barney"  # 项目内已有角色素材名称
ASPECT_RATIO = "16:9"
RESOLUTION   = "360p"            # 仅 Omni 模型生效
DURATION     = 8                 # 仅 Omni 模型生效
QUANTITY     = 1
MAX_WAIT     = 420               # 7 分钟超时 (420s)
# ─────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SERVER_PARAMS = StdioServerParameters(
    command="uv",
    args=["--directory", str(PROJECT_ROOT), "run", "google-flow-mcp"],
)


async def poll_status(session: ClientSession, job_id: str, max_wait: int = MAX_WAIT) -> dict:
    """轮询 video_status 直到任务完成或超时 (最多等待 7 分钟)"""
    print(f"\n⏳ 轮询视频生成状态 (job_id={job_id[:8]}...)，最多等待 {max_wait}s (7分钟)", flush=True)
    for elapsed in range(0, max_wait, 5):
        await asyncio.sleep(5)
        result = await session.call_tool("video_status", arguments={"job_id": job_id})
        raw = result.content[0].text
        state = json.loads(raw)
        status = state.get("status", "unknown")
        progress = state.get("progress", "")
        prog_str = f"({progress}%)" if progress else ""
        print(f"  [{elapsed+5:3d}s] status={status} {prog_str}  msg={state.get('message', state.get('error', ''))}", flush=True)

        if status in ("completed", "completed_with_rename_warning", "error"):
            return state

    return {"status": "timeout", "error": f"超过 {max_wait}s 未完成"}


async def main():
    print("=" * 60)
    print("  MCP video_create 素材模式 (assets) 集成测试")
    print("=" * 60)
    print(f"  project_id  : {PROJECT_ID}")
    print(f"  prompt      : {PROMPT}")
    print(f"  video_name  : {VIDEO_NAME}")
    print(f"  model_name  : {MODEL_NAME}")
    print(f"  mode        : {MODE}")
    print(f"  start_frame : {START_FRAME!r} (素材模式需为空)")
    print(f"  end_frame   : {END_FRAME!r} (素材模式需为空)")
    print(f"  assets      : {ASSETS}")
    print(f"  aspect_ratio: {ASPECT_RATIO}")
    print(f"  resolution  : {RESOLUTION}")
    print(f"  duration    : {DURATION}")
    print(f"  quantity    : {QUANTITY}")
    print("=" * 60)

    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. 列出工具，确认 video_create / video_status 已注册
            tools_resp = await session.list_tools()
            tool_names = [t.name for t in tools_resp.tools]
            print(f"\n✅ 已注册工具: {tool_names}")

            for required in ("video_create", "video_status"):
                assert required in tool_names, f"❌ 工具 {required} 未注册！"

            # 2. 调用 video_create
            print(f"\n🚀 调用 video_create (模式: asset, 超时限制: 7分钟)...")
            t0 = time.time()
            create_result = await session.call_tool(
                "video_create",
                arguments={
                    "project_id":   PROJECT_ID,
                    "prompt":       PROMPT,
                    "video_name":   VIDEO_NAME,
                    "model_name":   MODEL_NAME,
                    "mode":         MODE,
                    "start_frame":  START_FRAME,
                    "end_frame":    END_FRAME,
                    "assets":       ASSETS,
                    "aspect_ratio": ASPECT_RATIO,
                    "resolution":   RESOLUTION,
                    "duration":     DURATION,
                    "quantity":     QUANTITY,
                },
            )
            raw_create = create_result.content[0].text
            print(f"   返回: {raw_create}")
            resp = json.loads(raw_create)

            assert resp.get("success"), f"❌ video_create 返回失败: {resp}"
            job_id = resp["job_id"]
            print(f"   ✅ job_id = {job_id}")

            # 3. 轮询 video_status
            final = await poll_status(session, job_id, max_wait=MAX_WAIT)
            elapsed = time.time() - t0
            print(f"\n{'='*60}")

            is_ok = (
                final.get("status") in ("completed", "completed_with_rename_warning")
                and bool(final.get("video_url"))
            )

            if is_ok:
                print(f"✅ 测试通过！耗时 {elapsed:.1f}s")
                print(f"   详情: {json.dumps(final, indent=2, ensure_ascii=False)}")
            else:
                print(f"❌ 测试失败！耗时 {elapsed:.1f}s")
                print(f"   详情: {json.dumps(final, indent=2, ensure_ascii=False)}")
            print("=" * 60)

            return is_ok


if __name__ == "__main__":
    ok = asyncio.run(main())
    exit(0 if ok else 1)
