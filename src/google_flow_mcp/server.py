import atexit
from loguru import logger
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.browser.session import close_browser
from google_flow_mcp.tools.website_open import register_website_open_tool
from google_flow_mcp.tools.project_list import register_project_list_tool
from google_flow_mcp.tools.project_open import register_project_open_tool
from google_flow_mcp.tools.project_rename import register_project_rename_tool
from google_flow_mcp.tools.project_create import register_project_create_tool
from google_flow_mcp.tools.character_create import (
    register_character_create_tool,
    register_character_status_tool,
)
from google_flow_mcp.tools.character_create_by_upload import (
    register_character_create_by_upload_tool,
)
from google_flow_mcp.tools.character_list import register_character_list_tool
from google_flow_mcp.tools.image_create import (
    register_image_create_tool,
    register_image_status_tool,
)
from google_flow_mcp.tools.image_create_by_upload import (
    register_image_create_by_upload_tool,
)
from google_flow_mcp.tools.image_list import register_image_list_tool
from google_flow_mcp.tools.video_create import (
    register_video_create_tool,
    register_video_status_tool,
)
from google_flow_mcp.tools.video_create_by_upload import (
    register_video_create_by_upload_tool,
)
from google_flow_mcp.tools.video_list import register_video_list_tool
from google_flow_mcp.tools.task_tools import register_task_tools
from google_flow_mcp.tasks.manager import task_manager

mcp = FastMCP(
    name="google-flow-mcp",
    dependencies=["DrissionPage"],
    instructions="""Google Agentspace Flow 网页端操作工具集。

【核心任务调度与并发架构（重要）】
1. 全局单任务排队：由于全服务共用单一浏览器实例，所有生成与上传任务（涵盖 image_create / image_create_by_upload 图片、video_create / video_create_by_upload 视频、character_create / character_create_by_upload 虚拟角色）均受全局单任务队列统一串行调度。同一时刻全服务仅允许一个任务处于生成中。
2. 自动排队机制：若当前已有任务在生成，新发起的生成请求会自动进入 FIFO 排队队列（返回 status='queued'、分配独立 job_id 并标明 queue_position 位次）。前置任务完成后将自动无缝开始执行，智能体【严禁】因看到 queued 而重复发起调用。
3. 状态轮询：智能体只需使用对应的 status 工具（image_status / video_status / character_status）定期轮询对应 job_id 的进度。当返回 is_finished=True 时方可结束轮询。
4. 全局队列管理：智能体可随时调用 task_queue_status 工具查看全局是否繁忙、当前运行任务及等待队列；可通过 task_cancel(job_id) 取消排队任务或中断正在执行的任务。
5. 浏览器互斥保护：生成任务执行期间，project_create、project_open 等页面跳转类工具会被互斥保护并返回繁忙提示，需等待生成完成或取消任务后再操作。
6. 视频生成模型特性与素材引用限制（重要）：
   - Omni 1.1 Flash：支持调节清晰度（360p/720p）与时长（如 8s），且在素材模式（mode='asset'）下支持添加参考素材（Asset-to-Video）。
   - Veo 3.1 系列（Lite/Fast/Quality）：高画质影视级运镜；【极重要】Veo 系列模型除了在帧模式（mode='frame'）可以添加首帧（start_frame）和尾帧（end_frame）之外，不能再添加其它素材作为参考；在素材模式（mode='asset'）时即使添加了素材作为参考，Veo 模型也不会引用！因此 Veo 模型仅支持首尾帧模式或纯文本生视频模式，若需引用素材作为参考请务必选择 Omni 模型。
""",
)

# Register all MCP tools
register_website_open_tool(mcp)
register_project_list_tool(mcp)
register_project_open_tool(mcp)
register_project_rename_tool(mcp)
register_project_create_tool(mcp)
register_character_create_tool(mcp)
register_character_create_by_upload_tool(mcp)
register_character_status_tool(mcp)
register_character_list_tool(mcp)
register_image_create_tool(mcp)
register_image_create_by_upload_tool(mcp)
register_image_status_tool(mcp)
register_image_list_tool(mcp)
register_video_create_tool(mcp)
register_video_create_by_upload_tool(mcp)
register_video_status_tool(mcp)
register_video_list_tool(mcp)
register_task_tools(mcp)


# Ensure task manager worker is safely stopped on process exit
atexit.register(task_manager.stop)
# 注意：不在 atexit 中自动关闭浏览器，以保留常驻浏览器供后续智能体对话/工具调用直接连接复用


def main() -> None:
    """Run the MCP server in stdio transport mode with cluster support."""
    from pathlib import Path
    import threading
    from google_flow_mcp.config import get_settings

    settings = get_settings()

    if settings.is_cluster_enabled:
        from google_flow_mcp.cluster.asset_hub import AssetHub
        from google_flow_mcp.cluster.scheduler import ClusterScheduler
        from google_flow_mcp.cluster.master_server import MasterServer
        from google_flow_mcp.cluster.worker_client import WorkerClient
        from google_flow_mcp.cluster.launcher import get_lan_ips

        lan_ips = get_lan_ips()
        primary_ip = lan_ips[0] if lan_ips else "127.0.0.1"

        logger.info(
            f"Initializing Cluster Master on {settings.cluster_master_host}:{settings.cluster_master_port}..."
        )
        logger.info(
            f"Cluster Master active on 0.0.0.0:{settings.cluster_master_port} (LAN IP: {primary_ip})"
        )
        logger.info(f"Workers can connect to: http://{primary_ip}:{settings.cluster_master_port}")

        asset_hub = AssetHub(Path(settings.cluster_asset_dir))
        cluster_scheduler = ClusterScheduler()
        master_server = MasterServer(
            scheduler=cluster_scheduler,
            asset_hub=asset_hub,
            host=settings.cluster_master_host,
            port=settings.cluster_master_port,
        )
        master_server.start()

        # Connect task_manager to cluster_scheduler
        task_manager.set_cluster_scheduler(cluster_scheduler)

        # Start Local Worker 0
        local_worker = WorkerClient(
            master_url=f"http://127.0.0.1:{settings.cluster_master_port}",
            worker_id=settings.worker_id,
            account=settings.worker_account,
        )
        threading.Thread(
            target=local_worker.run_forever, daemon=True, name="MasterLocalWorker"
        ).start()

        atexit.register(master_server.stop)
        atexit.register(local_worker.stop)

    logger.info("Starting google-flow-mcp server (stdio mode)...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
