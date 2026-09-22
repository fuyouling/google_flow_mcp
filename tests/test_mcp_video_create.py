r"""
通过 MCP Python 客户端测试 video_create 工具
用途：验证视频生成流程（Omni/Veo 模型、首尾帧/素材模式、状态轮询、清晰度本地下载重命名保存流程）

运行方式:
    cd C:\dev\ai\mcp\google_flow_mcp
    uv run python tests/test_mcp_video_create.py
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
PROJECT_NAME   = "TestProject"  # 目标项目 ID (留空 "" 则自动选用最近访问的项目)
PROMPT       = "Mary Lennox 和 Officer Barney 正在吃饭"
VIDEO_NAME   = "SE_03_VIDEO"
MODEL_NAME   = "Veo 3.1 - Lite"  # 可选: "Omni 1.1 Flash", "Veo 3.1 - Lite", "Veo 3.1 - Fast", "Veo 3.1 - Quality"
MODE         = "frame"           # 生成模式: "frame" (首尾帧模式，需提供 start_frame 和 end_frame) 或 "asset" (纯文本/素材参考模式，默认)
START_FRAME  = "SE_01"           # [仅帧模式] 首帧图片名称 (项目内已有)
END_FRAME    = "SE_02"           # [仅帧模式] 尾帧图片名称 (项目内已有)
ASSETS       = ""                # [仅素材模式] 逗号分隔的参考素材名称列表 (帧模式必须为空)
ASPECT_RATIO = "9:16"            # 可选: "16:9", "9:16"
RESOLUTION   = "720p"            # 仅 Omni 模型生效: "360p", "720p"
DURATION     = 8                 # 仅 Omni 模型生效: 5 或 8
QUANTITY     = 1
DOWNLOAD     = "720p"            # 可选: "270p", "720p", "1080p"，留空 "" 则不自动下载
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
        progress = state.get("progress", state.get("progress_percent", ""))
        prog_str = f"({progress}%)" if progress else ""
        print(f"  [{elapsed+5:3d}s] status={status} {prog_str}  msg={state.get('message', state.get('error', ''))}", flush=True)

        if state.get("is_finished") or status in ("completed", "completed_with_rename_warning", "completed_with_download_warning", "error"):
            return state

    return {"status": "timeout", "error": f"超过 {max_wait}s 未完成"}


async def main():
    print("=" * 60)
    print("  MCP video_create 集成测试")
    print("=" * 60)
    print(f"  project_name  : {PROJECT_NAME!r} (留空自动选用最近项目)")
    print(f"  prompt      : {PROMPT}")
    print(f"  video_name  : {VIDEO_NAME}")
    print(f"  model_name  : {MODEL_NAME}")
    print(f"  mode        : {MODE}")
    print(f"  start_frame : {START_FRAME}")
    print(f"  end_frame   : {END_FRAME}")
    print(f"  assets      : {ASSETS}")
    print(f"  aspect_ratio: {ASPECT_RATIO}")
    print(f"  resolution  : {RESOLUTION}")
    print(f"  duration    : {DURATION}")
    print(f"  quantity    : {QUANTITY}")
    print(f"  download    : {DOWNLOAD}")
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
            print(f"\n🚀 调用 video_create (模式: {MODE}, 超时限制: 7分钟)...")
            t0 = time.time()
            create_result = await session.call_tool(
                "video_create",
                arguments={
                    "prompt":       PROMPT,
                    "project_name":   PROJECT_NAME,
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
                    "download":     DOWNLOAD,
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
                final.get("status") in ("completed", "completed_with_rename_warning", "completed_with_download_warning")
                and final.get("is_finished") is True
                and bool(final.get("video_url"))
            )

            if is_ok:
                print(f"✅ 测试通过！耗时 {elapsed:.1f}s")
                if final.get("video_local_path"):
                    print(f"   video_local_path: {final.get('video_local_path')}")
                print(f"   详情: {json.dumps(final, indent=2, ensure_ascii=False)}")
            else:
                print(f"❌ 测试失败！耗时 {elapsed:.1f}s")
                print(f"   详情: {json.dumps(final, indent=2, ensure_ascii=False)}")
            print("=" * 60)

            return is_ok


if __name__ == "__main__":
    ok = asyncio.run(main())
    exit(0 if ok else 1)
