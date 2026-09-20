import time
import threading
from collections import OrderedDict
from typing import Callable, Any
from loguru import logger


class TaskManager:
    """
    全局单任务并发控制与 FIFO 任务队列管理器。
    确保整个 MCP 服务同一时刻仅执行一个生成任务（视频/图片/人物），
    其他任务按提交先后顺序自动排队，并提供状态自愈、历史记录与取消能力。
    """
    MAX_QUEUE_SIZE = 20
    MAX_HISTORY_SIZE = 100

    def __init__(self):
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._stop_event = threading.Event()

        # 任务队列 (list of dict, 保证 FIFO 顺序及支持按 job_id 移除取消)
        self._queue: list[dict] = []

        # 当前正在执行的任务信息
        self._current_task: dict | None = None

        # 存储所有已知任务的最新状态字典，供外部直接读写及向下兼容
        self._all_jobs: dict[str, dict] = {}

        # 历史记录 (LRU 淘汰)
        self._history_jobs: OrderedDict[str, dict] = OrderedDict()

        # 集群调度器桥接（当启用多机模式时非空）
        self._cluster_scheduler = None

        # 后台消费线程
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="TaskManagerWorker")
        self._worker_thread.start()

    def set_cluster_scheduler(self, scheduler) -> None:
        """附加 ClusterScheduler 实例用于多节点集群分布式调度"""
        with self._lock:
            self._cluster_scheduler = scheduler
            # 共享全局 jobs 字典引用
            if scheduler and hasattr(scheduler, "jobs"):
                self._all_jobs = scheduler.jobs

    @property
    def jobs(self) -> dict[str, dict]:
        """暴露给外部的全局任务字典（向下兼容旧模块的 _jobs 字典访问）"""
        return self._all_jobs

    def reset(self) -> None:
        """重置队列与任务状态（供测试或异常恢复使用）"""
        with self._lock:
            self._queue.clear()
            self._current_task = None
            self._all_jobs.clear()
            self._history_jobs.clear()

    def is_browser_busy(self) -> tuple[bool, dict | None]:
        """
        判断当前是否有任务占用浏览器。
        返回 (True, current_task_info) 或 (False, None)。
        """
        with self._lock:
            # 1. 检查当前活跃任务
            if self._current_task is not None:
                c_id = self._current_task["job_id"]
                c_state = self._all_jobs.get(c_id, {})
                if not c_state.get("is_finished", False) and not self._current_task.get("is_finished", False):
                    return True, dict(self._current_task)
                else:
                    self._current_task = None

            # 2. 检查队列中等待被执行的任务
            active_id = self._current_task["job_id"] if self._current_task else None
            for item in self._queue:
                if item["job_id"] != active_id:
                    n_state = self._all_jobs.get(item["job_id"], {})
                    if not n_state.get("is_finished", False):
                        return True, dict(item)

            return False, None

    def submit_task(
        self,
        task_type: str,
        job_id: str,
        initial_state: dict,
        worker_fn: Callable[[], Any],
        project_id: str = "",
        task_name: str = "",
        params: dict | None = None,
        required_assets: list[str] | None = None,
    ) -> dict:
        """
        提交生成任务至全局队列。
        如果处于集群模式，任务将委托给 ClusterScheduler 进行跨机调度。
        如果处于单机模式，任务将排入单机 FIFO 队列顺序执行。
        """
        with self._lock:
            # ── 集群模式路由 ────────────────────────────────────
            if self._cluster_scheduler is not None:
                from google_flow_mcp.cluster.models import TaskType
                tt_map = {
                    "video": TaskType.VIDEO_CREATE,
                    "video_create": TaskType.VIDEO_CREATE,
                    "video_upload": TaskType.VIDEO_CREATE_BY_UPLOAD,
                    "video_create_by_upload": TaskType.VIDEO_CREATE_BY_UPLOAD,
                    "image": TaskType.IMAGE_CREATE,
                    "image_create": TaskType.IMAGE_CREATE,
                    "image_upload": TaskType.IMAGE_CREATE_BY_UPLOAD,
                    "image_create_by_upload": TaskType.IMAGE_CREATE_BY_UPLOAD,
                    "character": TaskType.CHARACTER_CREATE,
                    "character_create": TaskType.CHARACTER_CREATE,
                    "character_upload": TaskType.CHARACTER_CREATE_BY_UPLOAD,
                    "character_create_by_upload": TaskType.CHARACTER_CREATE_BY_UPLOAD,
                }
                tt = tt_map.get(task_type.lower(), TaskType.VIDEO_CREATE)
                self._cluster_scheduler.submit_task(
                    task_type=tt,
                    project_alias=project_id,
                    params=params or {},
                    required_assets=required_assets or [],
                    job_id=job_id,
                )
                if job_id in self._cluster_scheduler.jobs:
                    self._cluster_scheduler.jobs[job_id].update(initial_state)
                self._all_jobs[job_id] = self._cluster_scheduler.jobs[job_id]
                q_pos = len(self._cluster_scheduler.pending_tasks)
                logger.info(f"Task {job_id} routed to ClusterScheduler (pending: {q_pos})")
                return {
                    "success": True,
                    "status": "started" if q_pos == 0 else "queued",
                    "is_finished": False,
                    "job_id": job_id,
                    "queue_position": q_pos,
                    "message": f"任务已提交至集群调度器（队列位次: {q_pos}）。",
                    "next_action": f"请等待 5 秒后调用对应的 status(job_id='{job_id}') 查询进度。"
                }

            # ── 单机模式执行 ────────────────────────────────────
            # 清理已终态的 _current_task
            if self._current_task is not None:
                c_id = self._current_task["job_id"]
                c_state = self._all_jobs.get(c_id, {})
                if c_state.get("is_finished", False) or self._current_task.get("is_finished", False):
                    self._current_task = None

            # 清理队列中已标记完成的任务
            self._queue = [t for t in self._queue if not self._all_jobs.get(t["job_id"], {}).get("is_finished", False)]

            # 计算实际正在排队等待的任务数量（不含当前活跃任务）
            active_id = self._current_task["job_id"] if self._current_task else None
            waiting_tasks = [t for t in self._queue if t["job_id"] != active_id]

            if len(waiting_tasks) >= self.MAX_QUEUE_SIZE:
                error_msg = f"任务排队队列已满（当前已有 {len(waiting_tasks)} 个任务等待），最多支持 {self.MAX_QUEUE_SIZE} 个。请等待已有任务完成后再提交。"
                logger.warning(f"Queue full: rejected {task_type} task {job_id}")
                return {
                    "success": False,
                    "status": "error",
                    "is_finished": True,
                    "error": error_msg,
                    "message": error_msg,
                    "next_action": "任务队列已满，智能体请等待 30-60 秒后重试提交。"
                }

            is_idle = (self._current_task is None) and (len(self._queue) == 0)
            now = time.time()

            task_item = {
                "job_id": job_id,
                "task_type": task_type,
                "task_name": task_name or f"{task_type}_{job_id[:8]}",
                "project_id": project_id,
                "worker_fn": worker_fn,
                "created_at": now,
                "cancel_requested": False,
                "state": initial_state
            }

            # 写入全局字典供 status 实时查询
            self._all_jobs[job_id] = initial_state

            if is_idle:
                # 立即标记为当前任务，防止并发判定竞态
                self._current_task = task_item

                initial_state.setdefault("job_id", job_id)
                initial_state.setdefault("status", "pending")
                initial_state.setdefault("is_finished", False)
                initial_state.setdefault("progress", 0)
                initial_state.setdefault("progress_percent", 0)
                initial_state.setdefault("progress_text", "0%")
                initial_state.setdefault("elapsed_seconds", 0)
                initial_state.setdefault("created_at", now)

                self._queue.append(task_item)
                self._condition.notify()

                logger.info(f"Task {job_id} ({task_type}) submitted and set as active task.")
                return {
                    "success": True,
                    "status": "started",
                    "is_finished": False,
                    "job_id": job_id,
                    "queue_position": 0,
                    "message": f"{task_type} 任务已在后台启动。请调用对应的 status 工具轮询状态。",
                    "next_action": f"请等待 5 秒后调用对应的 status(job_id='{job_id}') 查询任务进度。"
                }
            else:
                # 前面有任务在运行或排队，进入排队状态
                queue_pos = len(waiting_tasks) + 1
                initial_state.update({
                    "job_id": job_id,
                    "status": "queued",
                    "is_finished": False,
                    "progress": 0,
                    "progress_percent": 0,
                    "progress_text": "排队中",
                    "queue_position": queue_pos,
                    "created_at": now,
                    "elapsed_seconds": 0,
                    "message": f"当前已有任务正在执行，该 {task_type} 任务已加入等待队列，当前排在第 {queue_pos} 位。前置任务完成后将自动执行。",
                    "next_action": f"任务排队中（第 {queue_pos} 位），请等待 5-10 秒后继续调用对应的 status(job_id='{job_id}') 检查进度。"
                })

                self._queue.append(task_item)
                self._condition.notify()

                logger.info(f"Task {job_id} ({task_type}) queued at position {queue_pos}.")
                return {
                    "success": True,
                    "status": "queued",
                    "is_finished": False,
                    "job_id": job_id,
                    "queue_position": queue_pos,
                    "message": f"当前已有任务正在执行中，该 {task_type} 任务已进入全局排队队列（排在第 {queue_pos} 位）。",
                    "next_action": f"任务排队中（第 {queue_pos} 位），请等待 5-10 秒后调用 status 工具查询状态。"
                }

    def get_task_status(self, job_id: str) -> dict:
        """
        查询任务最新状态。如果在排队中，自动计算并更新最新的队列位次。
        """
        with self._lock:
            state = self._all_jobs.get(job_id)
            if state is None:
                return {
                    "job_id": job_id,
                    "status": "error",
                    "is_finished": True,
                    "error": f"未找到任务 ID: {job_id}。任务可能不存在或服务已重启。",
                    "message": f"未找到任务 ID: {job_id}。任务可能不存在或服务已重启。",
                    "next_action": "未找到任务记录，智能体请停止轮询，请核对 job_id 或重新发起任务。"
                }

            # 仅当任务仍处于排队状态 (queued) 时动态更新等待位次
            if state.get("status") == "queued":
                active_id = self._current_task["job_id"] if self._current_task else None
                waiting_queue = [t for t in self._queue if t["job_id"] != active_id]
                for idx, task in enumerate(waiting_queue):
                    if task["job_id"] == job_id:
                        pos = idx + 1
                        elapsed = round(time.time() - task["created_at"], 1)
                        state.update({
                            "queue_position": pos,
                            "elapsed_seconds": elapsed,
                            "message": f"当前任务排队中（第 {pos} 位，已等待 {elapsed}s），前置任务完成后将自动开始。",
                            "next_action": f"任务排队中（第 {pos} 位），请等待 5-10 秒后继续查询进度。"
                        })
                        break

            return state

    def cancel_task(self, job_id: str) -> dict:
        """
        取消任务：
        - 集群模式：委托给 ClusterScheduler 取消。
        - 单机模式：若在队列中排队则移除，若正在执行中则触发取消标记。
        """
        with self._lock:
            if self._cluster_scheduler is not None:
                success = self._cluster_scheduler.cancel_task(job_id)
                return {
                    "success": success,
                    "job_id": job_id,
                    "status": "cancelled" if success else "not_found",
                    "message": "任务已从集群队列中成功取消。" if success else f"未找到任务 ID: {job_id}。"
                }

            # 1. 检查是否在排队中（未开始执行）
            is_active_current = (self._current_task is not None and self._current_task["job_id"] == job_id)
            for idx, task in enumerate(self._queue):
                if task["job_id"] == job_id and not is_active_current:
                    self._queue.pop(idx)
                    state = self._all_jobs.get(job_id, task["state"])
                    state.update({
                        "job_id": job_id,
                        "status": "cancelled",
                        "is_finished": True,
                        "message": "任务已从排队队列中成功取消。",
                        "next_action": "任务已被取消，智能体请停止轮询。"
                    })
                    self._record_history(job_id, state)
                    logger.info(f"Task {job_id} removed from queue and cancelled.")
                    return {
                        "success": True,
                        "job_id": job_id,
                        "status": "cancelled",
                        "message": "任务已从排队队列中成功取消。"
                    }

            # 2. 检查是否正在执行
            if is_active_current:
                self._current_task["cancel_requested"] = True
                state = self._all_jobs.get(job_id, self._current_task["state"])
                state.update({
                    "job_id": job_id,
                    "status": "cancelled",
                    "is_finished": True,
                    "message": "当前正在执行的任务已被用户请求取消，正在重置浏览器...",
                    "next_action": "任务已被取消，智能体请停止轮询。"
                })
                logger.info(f"Task {job_id} running in foreground requested cancellation.")

                # 尝试通过 CDP 或打开空白页打断当前阻塞操作
                try:
                    from google_flow_mcp.browser import session
                    if session._page is not None:
                        browser = session.get_browser()
                        if browser and browser.latest_tab:
                            browser.latest_tab.get("about:blank")
                except Exception as e:
                    logger.warning(f"Error resetting page during task cancel: {e}")

                self._record_history(job_id, state)
                return {
                    "success": True,
                    "job_id": job_id,
                    "status": "cancelled",
                    "message": "正在执行的任务已被中断并取消，浏览器环境正在自愈重置。"
                }

            # 3. 检查是否已完成
            if job_id in self._all_jobs:
                state = self._all_jobs[job_id]
                if state.get("is_finished", False):
                    return {
                        "success": False,
                        "job_id": job_id,
                        "status": state.get("status", "unknown"),
                        "message": f"任务已处于结束状态（status={state.get('status')}），无需重复取消。"
                    }

            return {
                "success": False,
                "job_id": job_id,
                "status": "not_found",
                "message": f"未找到任务 ID: {job_id}。"
            }

    def get_queue_summary(self) -> dict:
        """
        获取全局任务队列汇总状态（当前执行 + 排队列表）。
        """
        with self._lock:
            if self._cluster_scheduler is not None:
                workers = self._cluster_scheduler.get_workers()
                idle_count = len([w for w in workers if w.state.value == "idle"])
                pending_count = len(self._cluster_scheduler.pending_tasks)
                active_count = len(self._cluster_scheduler.active_tasks)
                return {
                    "is_busy": (idle_count == 0 and len(workers) > 0) or pending_count > 0,
                    "cluster_mode": True,
                    "worker_count": len(workers),
                    "idle_workers": idle_count,
                    "active_tasks": active_count,
                    "queue_length": pending_count,
                    "history_count": len(self._history_jobs),
                    "workers": [
                        {
                            "worker_id": w.worker_id,
                            "ip": w.ip,
                            "state": w.state.value,
                            "account": w.account,
                            "current_job_id": w.current_job_id,
                            "cached_asset_count": len(w.cached_assets),
                        }
                        for w in workers
                    ],
                }

            current_info = None
            if self._current_task is not None:
                c_id = self._current_task["job_id"]
                c_state = self._all_jobs.get(c_id, {})
                if not c_state.get("is_finished", False):
                    current_info = {
                        "job_id": c_id,
                        "task_type": self._current_task.get("task_type", "unknown"),
                        "task_name": self._current_task.get("task_name", ""),
                        "project_id": self._current_task.get("project_id", ""),
                        "status": c_state.get("status", "generating"),
                        "progress_percent": c_state.get("progress_percent", 0),
                        "elapsed_seconds": c_state.get("elapsed_seconds", 0),
                        "message": c_state.get("message", "")
                    }
                else:
                    self._current_task = None

            queued_list = []
            now = time.time()
            active_id = self._current_task["job_id"] if self._current_task else None
            for item in self._queue:
                q_id = item["job_id"]
                if active_id and q_id == active_id:
                    continue
                q_state = self._all_jobs.get(q_id, {})
                if q_state.get("is_finished", False):
                    continue
                queued_list.append({
                    "position": len(queued_list) + 1,
                    "job_id": q_id,
                    "task_type": item.get("task_type", "unknown"),
                    "task_name": item.get("task_name", ""),
                    "project_id": item.get("project_id", ""),
                    "wait_seconds": round(now - item.get("created_at", now), 1),
                    "message": q_state.get("message", "")
                })

            is_busy = (current_info is not None) or (len(queued_list) > 0)
            return {
                "is_busy": is_busy,
                "current_task": current_info,
                "queue_length": len(queued_list),
                "queued_tasks": queued_list,
                "history_count": len(self._history_jobs)
            }

    def _record_history(self, job_id: str, state: dict) -> None:
        """记录终态历史并维护 LRU 上限"""
        self._history_jobs[job_id] = state
        while len(self._history_jobs) > self.MAX_HISTORY_SIZE:
            self._history_jobs.popitem(last=False)

    def _clean_browser_overlay(self) -> None:
        """
        自愈清理：仅当浏览器已初始化时检查健康度并关闭残留遮罩和弹层。
        若浏览器无响应或出错，则安全关闭释放，不再同步重连以防阻塞队列。
        """
        try:
            from google_flow_mcp.browser import session
            if session._page is None:
                return

            browser = session.get_browser()
            if not browser:
                return

            # 验证浏览器通讯
            _ = browser.version
            tab = browser.latest_tab
            if tab:
                # 连续发送 ESC 键关闭可能阻挡后续操作的全局弹层
                for _ in range(2):
                    tab.run_cdp('Input.dispatchKeyEvent', type='rawKeyDown', windowsVirtualKeyCode=27)
                    tab.run_cdp('Input.dispatchKeyEvent', type='keyUp', windowsVirtualKeyCode=27)
                    time.sleep(0.1)
        except Exception as e:
            logger.warning(f"Browser health check or cleanup issue: {e}. Resetting session reference without killing browser...")
            try:
                from google_flow_mcp.browser import session
                session.set_browser(None)
            except Exception as e2:
                logger.error(f"Failed to reset browser session: {e2}")

    def _worker_loop(self) -> None:
        """
        单 Worker 线程主循环：串行消费任务队列。
        """
        logger.info("TaskManager worker loop started.")
        while not self._stop_event.is_set():
            task_item = None
            with self._condition:
                while not self._queue and not self._stop_event.is_set():
                    self._condition.wait(timeout=0.5)

                if self._stop_event.is_set():
                    break

                if self._queue:
                    task_item = self._queue.pop(0)
                    self._current_task = task_item

            if not task_item:
                continue

            job_id = task_item["job_id"]
            task_type = task_item["task_type"]
            worker_fn = task_item["worker_fn"]

            # 如果已经被取消或已在外部被标为完成，跳过执行
            curr_state = self._all_jobs.get(job_id, {})
            if curr_state.get("is_finished", False) or task_item.get("cancel_requested", False):
                logger.info(f"Worker skipping finished/cancelled task {job_id}")
                with self._lock:
                    if self._current_task and self._current_task.get("job_id") == job_id:
                        self._current_task = None
                continue

            logger.info(f"Worker starting task {job_id} ({task_type})")
            
            # 执行前自愈清理
            self._clean_browser_overlay()

            try:
                # 切换为 executing / pending
                with self._lock:
                    st = self._all_jobs.get(job_id, task_item["state"])
                    if st.get("status") == "queued":
                        st["status"] = "pending"
                        st["message"] = f"前置任务已完成，当前 {task_type} 任务开始执行..."
                        st["queue_position"] = 0

                # 如果在准备执行前已经被设置为 finished，跳过
                if self._all_jobs.get(job_id, {}).get("is_finished", False):
                    continue

                # 执行实际工具任务函数
                worker_fn()

            except Exception as e:
                logger.error(f"Task {job_id} worker execution error: {e}")
                with self._lock:
                    st = self._all_jobs.get(job_id, task_item["state"])
                    st.update({
                        "job_id": job_id,
                        "status": "error",
                        "is_finished": True,
                        "error": str(e),
                        "message": f"任务执行发生异常: {str(e)}",
                        "next_action": "任务失败，智能体请停止轮询。"
                    })
            finally:
                # 执行后记录历史并清理当前指针
                with self._lock:
                    final_state = self._all_jobs.get(job_id, task_item["state"])
                    self._record_history(job_id, final_state)
                    if self._current_task and self._current_task.get("job_id") == job_id:
                        self._current_task = None

                # 执行后自愈清理
                self._clean_browser_overlay()
                logger.info(f"Worker finished task {job_id} ({task_type})")

    def stop(self) -> None:
        """安全停止 TaskManager worker"""
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()


# 全局单例
task_manager = TaskManager()
