r"""
通过 MCP Python 客户端测试 image_create_by_upload 工具
用途：验证在项目主页通过上传本地图片创建图片资产并重命名保存

运行方式:
    cd C:\dev\ai\mcp\google_flow_mcp
    uv run python tests/test_mcp_image_create_by_upload.py
"""

import asyncio
import io
import json
import sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ── 编码修复（Windows GBK 终端） ──────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() in ("gbk", "gb2312", "cp936"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── 测试参数（请根据实际环境调整） ──────────────────────────────────
PROJECT_ID           = "41ffbc19-48f6-44c0-8b2a-4745e26ddc74"  # 目标项目 ID
IMAGE_NAME           = "Uploaded Test Image"                    # 图片名称（自动转为 Uploaded_Test_Image）
IMAGE_PATH           = r"C:\Users\zgh\Downloads\google_flow\Test_Hero_Portrait.jpeg"
MAX_WAIT             = 120  # 上传创建通常很快，最多等待 2 分钟
# ─────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SERVER_PARAMS = StdioServerParameters(
    command="uv",
    args=["--directory", str(PROJECT_ROOT), "run", "google-flow-mcp"],
)


async def poll_status(session: ClientSession, job_id: str, max_wait: int = MAX_WAIT) -> dict:
    """轮询 image_status 直到任务完成或超时"""
    print(f"\n⏳ 轮询图片上传创建状态 (job_id={job_id[:8]}...)，最多等待 {max_wait}s", flush=True)
    for elapsed in range(0, max_wait, 3):
        await asyncio.sleep(3)
        result = await session.call_tool("image_status", arguments={"job_id": job_id})
        raw = result.content[0].text
        state = json.loads(raw)
        status = state.get("status", "unknown")
        print(f"  [{elapsed+3:3d}s] status={status} msg={state.get('message', state.get('error', ''))}", flush=True)

        if state.get("is_finished") or status in ("completed", "error"):
            return state

    return {"status": "timeout", "message": f"轮询超时 (>{max_wait}s)"}


async def main():
    print("=" * 60)
    print("🚀 测试 image_create_by_upload 工具")
    print(f"   项目 ID: {PROJECT_ID}")
    print(f"   图片名称: {IMAGE_NAME}")
    print(f"   本地图片: {IMAGE_PATH}")
    print("=" * 60)

    if not Path(IMAGE_PATH).is_file():
        print(f"\n⚠️  提示：测试图片不存在: {IMAGE_PATH}")

    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. 验证工具列表中是否存在 image_create_by_upload
            tools_result = await session.list_tools()
            tool_names = [t.name for t in tools_result.tools]
            print(f"\n📋 可用工具列表 ({len(tool_names)} 个): {tool_names}")
            assert "image_create_by_upload" in tool_names, "image_create_by_upload 未注册!"
            print("✅ image_create_by_upload 工具已成功注册并发现")

            if not Path(IMAGE_PATH).is_file():
                print("\nℹ️  本地缺少测试文件，仅执行工具注册检查完毕。")
                return True

            # 2. 发起图片上传创建
            print("\n▶️ 发起图片上传创建请求...")
            args = {
                "project_id": PROJECT_ID,
                "image_name": IMAGE_NAME,
                "image_path": IMAGE_PATH
            }
            call_res = await session.call_tool("image_create_by_upload", arguments=args)
            raw_text = call_res.content[0].text
            submit_data = json.loads(raw_text)
            print(f"   提交响应: {json.dumps(submit_data, indent=2, ensure_ascii=False)}")

            job_id = submit_data.get("job_id")
            if not job_id:
                print("❌ 提交任务失败，未返回 job_id")
                return False

            # 3. 轮询 image_status
            final = await poll_status(session, job_id)
            print("\n" + "=" * 60)
            is_ok = final.get("status") == "completed"
            if is_ok:
                print(f"🎉 图片创建成功: {final.get('image_name')}")
                print(f"   图片本地路径: {final.get('image_path')}")
            else:
                print(f"❌ 图片创建失败: {final.get('error', final.get('message'))}")
            print("=" * 60)
            return is_ok


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
