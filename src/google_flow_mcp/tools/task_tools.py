import json
from typing import Annotated
from pydantic import Field
from loguru import logger
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.tasks.manager import task_manager


def register_task_tools(mcp: FastMCP) -> None:
    """注册全局任务队列查询与取消工具。"""

    @mcp.tool()
    def task_queue_status() -> str:
        """
        查询 Google Flow MCP 全局任务队列的当前状态。

        【用途与返回字段说明】
        1. is_busy: (bool) 当前是否有生成任务正在占用浏览器执行。
        2. current_task: (dict | None) 当前正在执行的任务信息（包含 job_id、task_type、status、progress_percent、已耗时等）。
        3. queue_length: (int) 当前正在排队等待的任务数量。
        4. queued_tasks: (list) 正在排队的任务列表（含等待位次 position、job_id、task_type、已等待时长 wait_seconds 等）。
        5. history_count: (int) 内存中已记录的历史终态任务数。
        """
        logger.info("Executing task_queue_status")
        summary = task_manager.get_queue_summary()
        return json.dumps(summary, ensure_ascii=False, indent=2)

    @mcp.tool()
    def task_cancel(
        job_id: Annotated[str, Field(description="要取消的任务唯一 ID (job_id)")]
    ) -> str:
        """
        取消指定的生成任务（包括排队中任务及正在执行中的任务）。

        【执行规则】
        1. 若任务正在排队中：立即从队列中移除并标记为 cancelled，后续任务自动前移。
        2. 若任务正在执行中：触发取消中断信号，重置浏览器页面并标记为 cancelled。
        3. 若任务已结束或不存在：返回相应提示信息。
        """
        logger.info(f"Executing task_cancel for job_id={job_id}")
        result = task_manager.cancel_task(job_id)
        return json.dumps(result, ensure_ascii=False)
