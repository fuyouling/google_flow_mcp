import json
import time
import threading
import pytest
from mcp.server.fastmcp import FastMCP

from google_flow_mcp.tasks.manager import task_manager
from google_flow_mcp.tools.task_tools import register_task_tools
from google_flow_mcp.tools.project_create import register_project_create_tool
from google_flow_mcp.tools.project_open import register_project_open_tool
from google_flow_mcp.tools.project_rename import register_project_rename_tool
from google_flow_mcp.tools.project_list import register_project_list_tool
from google_flow_mcp.tools.website_open import register_website_open_tool


@pytest.fixture(autouse=True)
def clean_task_manager():
    """每个测试前后重置 task_manager 队列与任务状态"""
    task_manager.reset()
    yield
    task_manager.reset()


def get_tool(server: FastMCP, tool_name: str):
    for tool in server._tool_manager.list_tools():
        if tool.name == tool_name:
            return tool.fn
    raise ValueError(f"Tool {tool_name} not registered")


def test_single_concurrency_and_fifo_queue():
    """验证全局单任务并发限制：前置任务执行期间，后续任务自动进入 FIFO 排队并顺序执行"""
    execution_order = []

    def make_worker(name: str, delay: float):
        def worker():
            execution_order.append(f"{name}_start")
            time.sleep(delay)
            execution_order.append(f"{name}_end")
            task_manager.jobs[f"job_{name}"]["status"] = "completed"
            task_manager.jobs[f"job_{name}"]["is_finished"] = True
        return worker

    # 1. 提交任务 A (耗时 0.2s)
    res_a = task_manager.submit_task(
        task_type="image",
        job_id="job_a",
        initial_state={"job_id": "job_a", "status": "pending"},
        worker_fn=make_worker("a", 0.2),
        task_name="task_a"
    )
    assert res_a["status"] == "started"
    assert res_a["queue_position"] == 0

    # 2. 提交任务 B (耗时 0.1s)
    res_b = task_manager.submit_task(
        task_type="video",
        job_id="job_b",
        initial_state={"job_id": "job_b", "status": "pending"},
        worker_fn=make_worker("b", 0.1),
        task_name="task_b"
    )
    assert res_b["status"] == "queued"
    assert res_b["queue_position"] == 1

    # 3. 提交任务 C (耗时 0.05s)
    res_c = task_manager.submit_task(
        task_type="character",
        job_id="job_c",
        initial_state={"job_id": "job_c", "status": "pending"},
        worker_fn=make_worker("c", 0.05),
        task_name="task_c"
    )
    assert res_c["status"] == "queued"
    assert res_c["queue_position"] == 2

    # 检查状态
    st_b = task_manager.get_task_status("job_b")
    assert st_b["status"] == "queued"
    assert st_b["queue_position"] == 1

    st_c = task_manager.get_task_status("job_c")
    assert st_c["status"] == "queued"
    assert st_c["queue_position"] == 2

    # 等待全部执行完毕
    time.sleep(0.8)

    # 验证严格顺序执行：A 开始并结束 -> B 开始并结束 -> C 开始并结束
    assert execution_order == [
        "a_start", "a_end",
        "b_start", "b_end",
        "c_start", "c_end"
    ]

    assert task_manager.get_task_status("job_a")["status"] == "completed"
    assert task_manager.get_task_status("job_b")["status"] == "completed"
    assert task_manager.get_task_status("job_c")["status"] == "completed"


def test_queue_capacity_limit():
    """验证排队容量限制：队列达到 20 个后拒绝新任务"""
    blocker_started = threading.Event()
    blocker_finish = threading.Event()

    def blocker_worker():
        blocker_started.set()
        blocker_finish.wait(timeout=2.0)
        task_manager.jobs["blocker"]["is_finished"] = True

    # 占住 worker
    task_manager.submit_task(
        task_type="image",
        job_id="blocker",
        initial_state={"job_id": "blocker", "status": "pending"},
        worker_fn=blocker_worker
    )
    blocker_started.wait(timeout=1.0)

    try:
        # 填充 20 个排队任务
        for i in range(20):
            res = task_manager.submit_task(
                task_type="image",
                job_id=f"queued_{i}",
                initial_state={"job_id": f"queued_{i}", "status": "pending"},
                worker_fn=lambda: None
            )
            assert res["status"] == "queued"
            assert res["queue_position"] == i + 1

        # 第 21 个排队任务应该被拒绝
        res_overflow = task_manager.submit_task(
            task_type="video",
            job_id="overflow_job",
            initial_state={"job_id": "overflow_job", "status": "pending"},
            worker_fn=lambda: None
        )
        assert res_overflow["success"] is False
        assert res_overflow["status"] == "error"
        assert "队列已满" in res_overflow["message"]
    finally:
        blocker_finish.set()


def test_task_cancel_queued():
    """验证取消排队中的任务"""
    worker_started = threading.Event()
    worker_finish = threading.Event()

    def running_worker():
        worker_started.set()
        worker_finish.wait(timeout=2.0)
        task_manager.jobs["running_1"]["is_finished"] = True

    # 占住 worker
    task_manager.submit_task(
        task_type="image",
        job_id="running_1",
        initial_state={"job_id": "running_1", "status": "pending"},
        worker_fn=running_worker
    )
    worker_started.wait(timeout=1.0)

    try:
        # 提交排队任务
        task_manager.submit_task(
            task_type="video",
            job_id="to_cancel",
            initial_state={"job_id": "to_cancel", "status": "pending"},
            worker_fn=lambda: None
        )

        cancel_res = task_manager.cancel_task("to_cancel")
        assert cancel_res["success"] is True
        assert cancel_res["status"] == "cancelled"

        st = task_manager.get_task_status("to_cancel")
        assert st["status"] == "cancelled"
        assert st["is_finished"] is True
    finally:
        worker_finish.set()


def test_task_queue_status_and_cancel_tools():
    """验证 task_queue_status 和 task_cancel MCP 工具"""
    server = FastMCP("test_tools_server")
    register_task_tools(server)

    queue_status_fn = get_tool(server, "task_queue_status")
    cancel_fn = get_tool(server, "task_cancel")

    # 空闲状态查询
    raw_status = queue_status_fn()
    data = json.loads(raw_status)
    assert data["is_busy"] is False
    assert data["queue_length"] == 0

    active_started = threading.Event()
    active_finish = threading.Event()

    def active_worker():
        active_started.set()
        active_finish.wait(timeout=2.0)
        task_manager.jobs["job_active"]["is_finished"] = True

    # 启动任务
    task_manager.submit_task(
        task_type="video",
        job_id="job_active",
        initial_state={"job_id": "job_active", "status": "generating", "progress_percent": 30},
        worker_fn=active_worker,
        task_name="my_video"
    )
    active_started.wait(timeout=1.0)

    try:
        # 提交排队任务
        task_manager.submit_task(
            task_type="image",
            job_id="job_waiting",
            initial_state={"job_id": "job_waiting", "status": "queued"},
            worker_fn=lambda: None,
            task_name="my_image"
        )

        raw_status2 = queue_status_fn()
        data2 = json.loads(raw_status2)
        assert data2["is_busy"] is True
        assert data2["current_task"]["job_id"] == "job_active"
        assert data2["queue_length"] == 1
        assert data2["queued_tasks"][0]["job_id"] == "job_waiting"

        # 使用工具取消排队任务
        raw_cancel = cancel_fn(job_id="job_waiting")
        cancel_data = json.loads(raw_cancel)
        assert cancel_data["success"] is True
        assert cancel_data["status"] == "cancelled"
    finally:
        active_finish.set()


def test_browser_busy_blocks_project_tools():
    """验证在后台生成任务运行期间，项目类网页工具被互斥拦截"""
    server = FastMCP("test_browser_lock_server")
    register_project_create_tool(server)
    register_project_open_tool(server)
    register_project_rename_tool(server)
    register_project_list_tool(server)
    register_website_open_tool(server)

    create_fn = get_tool(server, "project_create")
    open_fn = get_tool(server, "project_open")
    rename_fn = get_tool(server, "project_rename")
    list_fn = get_tool(server, "project_list")
    website_fn = get_tool(server, "website_open")

    busy_started = threading.Event()
    busy_finish = threading.Event()

    def busy_worker():
        busy_started.set()
        busy_finish.wait(timeout=2.0)
        if "active_gen_job" in task_manager.jobs:
            task_manager.jobs["active_gen_job"]["is_finished"] = True

    # 提交正在运行的任务
    task_manager.submit_task(
        task_type="video",
        job_id="active_gen_job",
        initial_state={"job_id": "active_gen_job", "status": "generating"},
        worker_fn=busy_worker
    )
    busy_started.wait(timeout=1.0)

    try:
        assert task_manager.is_browser_busy()[0] is True

        # 1. project_create 应当被拦截
        res_create = json.loads(create_fn(title="New Proj"))
        assert res_create["success"] is False
        assert "active_gen_job" in res_create["error"]

        # 2. project_open 应当被拦截
        res_open = json.loads(open_fn(project_id="test_uuid"))
        assert res_open["success"] is False
        assert "active_gen_job" in res_open["error"]

        # 3. project_rename 应当被拦截
        res_rename = json.loads(rename_fn(project_id="test_uuid", new_name="New Name"))
        assert res_rename["success"] is False
        assert "active_gen_job" in res_rename["error"]

        # 4. website_open 应当被拦截
        res_web = json.loads(website_fn(url="https://flow.google.com"))
        assert res_web["success"] is False
        assert "active_gen_job" in res_web["error"]

        # 5. project_list(force_refresh=True) 应当被拦截
        res_list = json.loads(list_fn(force_refresh=True))
        assert ("active_gen_job" in res_list.get("error", "")) or ("active_gen_job" in res_list.get("warning", ""))
    finally:
        busy_finish.set()
