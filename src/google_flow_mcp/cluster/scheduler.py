import time
import uuid
import threading
from typing import Callable, Dict, List, Optional, Set
from collections import deque
from loguru import logger

from google_flow_mcp.cluster.models import (
    TaskPayload,
    TaskResult,
    TaskType,
    WorkerInfo,
    WorkerState,
)
from google_flow_mcp.models.account_cache import AccountCache
from google_flow_mcp.models.credit_calculator import calc_task_credits
from google_flow_mcp.models.project_cache import ProjectCache


class ClusterScheduler:
    """
    Centralized task scheduler on the Master node.
    Features:
    - Worker pool & heartbeat tracking
    - FIFO Task Queue with Credit-Prioritized Affinity Routing
      (Prioritizes workers with daily free 50 credits, then combo, then asset affinity)
    - Automatic Failover, Refund & Retry when workers disconnect or fail
    - Compatible with legacy task_manager job dictionary format
    """

    def __init__(self, max_retries: int = 2, heartbeat_timeout: float = 30.0, asset_hub=None):
        self.max_retries = max_retries
        self.heartbeat_timeout = heartbeat_timeout
        self._asset_hub = asset_hub  # Optional[AssetHub] — used to register master-local generated assets
        self._lock = threading.RLock()

        self.workers: Dict[str, WorkerInfo] = {}
        # worker_id -> message sender callback (e.g., ws.send_json or queue.put)
        self._worker_senders: Dict[str, Callable[[dict], None]] = {}

        self.pending_tasks: deque[TaskPayload] = deque()
        self.active_tasks: Dict[str, TaskPayload] = {}  # job_id -> TaskPayload
        self.jobs: Dict[str, dict] = {}  # job_id -> legacy job dict for status queries

        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._health_check_loop, daemon=True, name="SchedulerHealthMonitor"
        )
        self._monitor_thread.start()

    def stop(self) -> None:
        self._running = False

    # ── Worker Management ────────────────────────────────────

    def register_worker(
        self,
        worker_id: str,
        ip: str = "127.0.0.1",
        account: str = "",
        project_mappings: Optional[Dict[str, str]] = None,
        cached_assets: Optional[Set[str]] = None,
        sender: Optional[Callable[[dict], None]] = None,
    ) -> WorkerInfo:
        with self._lock:
            init_credits = None
            init_daily_free = 50
            if account:
                acc_info = AccountCache.get_account_credits(account)
                init_credits = acc_info.get("credits")
                init_daily_free = acc_info.get("daily_free_remaining", 50)

            # Check if this worker had an active task that didn't finish (e.g. connection drop / restart)
            orphaned_task_id = None
            for jid, atask in list(self.active_tasks.items()):
                if atask.target_worker_id == worker_id:
                    orphaned_task_id = jid
                    break

            if orphaned_task_id:
                logger.warning(
                    f"Worker {worker_id} re-registered while task {orphaned_task_id} was active. "
                    "Triggering failover/cleanup for orphaned task."
                )
                self._handle_worker_failure(worker_id, "Worker re-registered during execution", orphaned_task_id)

            info = WorkerInfo(
                worker_id=worker_id,
                ip=ip,
                account=account,
                credits=init_credits,
                daily_free_remaining=init_daily_free,
                state=WorkerState.IDLE,
                project_mappings=project_mappings or {},
                cached_assets=cached_assets or set(),
                last_heartbeat=time.time(),
            )
            self.workers[worker_id] = info
            if sender:
                self._worker_senders[worker_id] = sender
            
            # --- DB Persistence ---
            if account:
                AccountCache.update(email=account, credits=init_credits, worker_id=worker_id)
            if project_mappings:
                for proj_alias, local_uuid in project_mappings.items():
                    if proj_alias != local_uuid:
                        ProjectCache.update_project(project_name=proj_alias, local_uuid=local_uuid, worker_id=worker_id)
            # ----------------------
            
            logger.info(
                f"Worker registered: {worker_id} (IP: {ip}, Account: {account}, "
                f"DailyFree: {init_daily_free}, Balance: {init_credits})"
            )
            self._schedule_next()
            return info

    def update_sender(self, worker_id: str, sender: Optional[Callable[[dict], None]]) -> None:
        with self._lock:
            if sender:
                self._worker_senders[worker_id] = sender
            else:
                self._worker_senders.pop(worker_id, None)

    def heartbeat(self, worker_id: str) -> None:
        with self._lock:
            if worker_id in self.workers:
                self.workers[worker_id].last_heartbeat = time.time()
                if self.workers[worker_id].state == WorkerState.DISCONNECTED:
                    self.workers[worker_id].state = WorkerState.IDLE
                    self._schedule_next()

    def unregister_worker(self, worker_id: str) -> None:
        with self._lock:
            worker = self.workers.get(worker_id)
            if worker:
                logger.warning(f"Unregistering worker: {worker_id}")
                worker.state = WorkerState.DISCONNECTED
                self._worker_senders.pop(worker_id, None)
                if worker.current_job_id:
                    self._handle_worker_failure(worker_id, "Worker disconnected")

    def get_workers(self) -> List[WorkerInfo]:
        with self._lock:
            for w in self.workers.values():
                if w.account:
                    acc_info = AccountCache.get_account_credits(w.account)
                    w.credits = acc_info.get("credits")
                    w.daily_free_remaining = acc_info.get("daily_free_remaining", 50)
            return list(self.workers.values())

    def update_worker_project_mapping(self, worker_id: str, project_alias: str, local_uuid: str) -> None:
        with self._lock:
            worker = self.workers.get(worker_id)
            if worker:
                worker.project_mappings[project_alias] = local_uuid
                if project_alias != local_uuid:
                    ProjectCache.update_project(project_name=project_alias, local_uuid=local_uuid, worker_id=worker_id)
                logger.info(f"Updated project mapping for {worker_id}: {project_alias} -> {local_uuid}")

    def add_worker_cached_asset(self, worker_id: str, asset_name: str) -> None:
        with self._lock:
            worker = self.workers.get(worker_id)
            if worker:
                worker.cached_assets.add(asset_name)

    # ── Task Submission & Scheduling ──────────────────────────

    def submit_task(
        self,
        task_type: TaskType,
        project_alias: str,
        params: dict,
        required_assets: Optional[List[str]] = None,
        job_id: Optional[str] = None,
        target_worker_id: Optional[str] = None,
    ) -> str:
        with self._lock:
            jid = job_id or str(uuid.uuid4())
            req_assets = required_assets or []
            cost = calc_task_credits(task_type.value, params)
            task = TaskPayload(
                job_id=jid,
                task_type=task_type,
                project_alias=project_alias,
                params=params,
                required_assets=req_assets,
                cost_credits=cost,
                target_worker_id=target_worker_id,
            )

            # Initialize legacy status dict
            self.jobs[jid] = {
                "job_id": jid,
                "status": "queued",
                "is_finished": False,
                "task_type": task_type.value,
                "project_alias": project_alias,
                "cost_credits": cost,
                "message": f"Task queued in cluster (cost: {cost} pt). Queue position: {len(self.pending_tasks) + 1}",
                "queue_position": len(self.pending_tasks) + 1,
            }

            self.pending_tasks.append(task)
            logger.info(f"Task submitted to cluster: job_id={jid}, type={task_type.value}, cost={cost}")
            self._schedule_next()
            return jid

    def cancel_task(self, job_id: str) -> bool:
        with self._lock:
            # 1. Check pending queue
            for t in list(self.pending_tasks):
                if t.job_id == job_id:
                    self.pending_tasks.remove(t)
                    self.jobs[job_id].update({
                        "job_id": job_id,
                        "status": "cancelled",
                        "is_finished": True,
                        "message": "Task was cancelled before execution.",
                    })
                    logger.info(f"Task {job_id} cancelled from queue.")
                    return True

            # 2. Check active tasks
            if job_id in self.active_tasks:
                task = self.active_tasks.pop(job_id, None)
                worker_id = task.target_worker_id if task else None
                worker = self.workers.get(worker_id) if worker_id else None
                sender = self._worker_senders.get(worker_id) if worker_id else None
                if sender:
                    try:
                        sender({"action": "cancel", "job_id": job_id})
                    except Exception as e:
                        logger.error(f"Failed to send cancel signal to {worker_id}: {e}")

                # Refund if cancelled before actual generation started
                last_status = self.jobs.get(job_id, {}).get("status", "")
                if task and last_status != "generating" and (task.deducted_daily_free > 0 or task.deducted_balance > 0):
                    if worker and worker.account:
                        AccountCache.refund_credits(
                            worker.account,
                            task.deducted_daily_free,
                            task.deducted_balance,
                        )
                    task.deducted_daily_free = 0
                    task.deducted_balance = 0

                if worker and worker.current_job_id == job_id:
                    worker.state = WorkerState.IDLE
                    worker.current_job_id = None

                self.jobs[job_id]["status"] = "cancelled"
                self.jobs[job_id]["is_finished"] = True
                self.jobs[job_id]["message"] = "Task execution cancelled."
                self._schedule_next()
                return True

            return False

    def _select_best_worker(self, task: TaskPayload) -> Optional[str]:
        """
        Prioritized worker selection:
        1. Only consider IDLE workers.
        2. Refresh each worker's daily cycle & ensure daily grant.
        3. Check total available credits (daily_free + balance >= cost). Exclude if insufficient.
        4. Priority Tiers:
           - Tier 1: daily_free >= cost (full daily grant coverage).
             Rank by: (daily_free, hit_count, -consecutive_failures)
           - Tier 2: 0 < daily_free < cost (partial daily grant combo).
             Rank by: (daily_free, hit_count, -consecutive_failures)
           - Tier 3: daily_free == 0 (consume regular balance).
             Rank by: (hit_count, balance or 0, -consecutive_failures)
        """
        candidate_ids = [
            wid
            for wid, w in self.workers.items()
            if w.state == WorkerState.IDLE and wid in self._worker_senders
        ]
        
        if task.target_worker_id:
            if task.target_worker_id in candidate_ids:
                candidate_ids = [task.target_worker_id]
            else:
                return None

        if not candidate_ids:
            return None

        req_set = set(task.required_assets)
        cost = task.cost_credits

        # Refresh credit info for candidate workers
        worker_credits_map = {}
        for wid in candidate_ids:
            w = self.workers[wid]
            if w.account:
                acc_info = AccountCache.get_account_credits(w.account)
                daily_free = acc_info.get("daily_free_remaining", 50)
                balance = acc_info.get("credits")
            else:
                daily_free = 50
                balance = None

            # Sync to WorkerInfo
            w.daily_free_remaining = daily_free
            w.credits = balance

            # If balance is None (not fetched yet or anonymous), assume sufficient
            tot_avail = daily_free + (balance if balance is not None else 999999)
            worker_credits_map[wid] = {
                "daily_free": daily_free,
                "balance": balance,
                "total_available": tot_avail,
            }

        # Filter candidates by solvency if cost > 0
        solvent_candidates = [
            wid for wid in candidate_ids
            if cost <= 0 or worker_credits_map[wid]["total_available"] >= cost
        ]
        if not solvent_candidates:
            logger.warning(
                f"No solvent workers available for task {task.job_id} requiring {cost} credits."
            )
            return None

        # Partition into Tiers
        tier1 = []
        tier2 = []
        tier3 = []

        for wid in solvent_candidates:
            df = worker_credits_map[wid]["daily_free"]
            if df >= cost:
                tier1.append(wid)
            elif df > 0:
                tier2.append(wid)
            else:
                tier3.append(wid)

        if tier1:
            def tier1_score(wid: str) -> tuple[int, int, int]:
                w = self.workers[wid]
                df = worker_credits_map[wid]["daily_free"]
                hit_count = len(w.cached_assets.intersection(req_set))
                return (df, hit_count, -w.consecutive_failures)
            best_wid = max(tier1, key=tier1_score)
            logger.debug(f"Tier 1 (full daily free) selected worker: {best_wid}")
            return best_wid
        elif tier2:
            def tier2_score(wid: str) -> tuple[int, int, int]:
                w = self.workers[wid]
                df = worker_credits_map[wid]["daily_free"]
                hit_count = len(w.cached_assets.intersection(req_set))
                return (df, hit_count, -w.consecutive_failures)
            best_wid = max(tier2, key=tier2_score)
            logger.debug(f"Tier 2 (partial daily free combo) selected worker: {best_wid}")
            return best_wid
        else:
            def tier3_score(wid: str) -> tuple[int, int, int]:
                w = self.workers[wid]
                bal = worker_credits_map[wid]["balance"] or 0
                hit_count = len(w.cached_assets.intersection(req_set))
                return (hit_count, bal, -w.consecutive_failures)
            best_wid = max(tier3, key=tier3_score)
            logger.debug(f"Tier 3 (regular balance) selected worker: {best_wid}")
            return best_wid

    def _schedule_next(self) -> None:
        """Attempt to dispatch the head of the queue to an idle worker."""
        with self._lock:
            if not self.pending_tasks:
                return

            task = self.pending_tasks[0]
            best_worker_id = self._select_best_worker(task)

            if not best_worker_id:
                # No idle worker right now, remains queued
                return

            self.pending_tasks.popleft()
            task.target_worker_id = best_worker_id
            self.active_tasks[task.job_id] = task

            worker = self.workers[best_worker_id]
            worker.state = WorkerState.BUSY
            worker.current_job_id = task.job_id

            # Deduct credits if cost > 0 and account is bound
            if task.cost_credits > 0 and worker.account:
                deduct_free, deduct_bal = AccountCache.deduct_credits(worker.account, task.cost_credits)
                task.deducted_daily_free = deduct_free
                task.deducted_balance = deduct_bal
                acc_info = AccountCache.get_account_credits(worker.account)
                worker.credits = acc_info.get("credits")
                worker.daily_free_remaining = acc_info.get("daily_free_remaining", 0)

            # Update job status
            self.jobs[task.job_id].update({
                "status": "assigned",
                "worker_id": best_worker_id,
                "message": f"Task assigned to worker {best_worker_id}. Starting asset prep / generation.",
            })

            # Send task payload to worker
            sender = self._worker_senders.get(best_worker_id)
            if sender:
                try:
                    payload_dict = {
                        "action": "execute",
                        "payload": task.model_dump(mode="json"),
                    }
                    sender(payload_dict)
                    logger.info(
                        f"Task {task.job_id} dispatched to worker {best_worker_id} "
                        f"(affinity match: {len(worker.cached_assets.intersection(set(task.required_assets)))}/{len(task.required_assets)}, "
                        f"cost: {task.cost_credits}, deducted_free: {task.deducted_daily_free}, deducted_bal: {task.deducted_balance})"
                    )
                except Exception as e:
                    logger.error(f"Failed to send task to {best_worker_id}: {e}")
                    self._handle_worker_failure(best_worker_id, f"Send failure: {e}")

    # ── Task Execution Feedback ──────────────────────────────

    def on_task_progress(self, job_id: str, status: str, message: str, extra: Optional[dict] = None) -> None:
        with self._lock:
            if job_id in self.jobs:
                self.jobs[job_id]["status"] = status
                self.jobs[job_id]["message"] = message
                if extra:
                    for k in ("progress", "progress_percent", "progress_text", "elapsed_seconds", "next_action"):
                        if k in extra:
                            self.jobs[job_id][k] = extra[k]

    def on_task_completed(self, result: TaskResult) -> None:
        with self._lock:
            job_id = result.job_id
            worker_id = result.worker_id

            logger.info(f"Task {job_id} completed successfully by worker {worker_id}")

            # Update worker state
            worker = self.workers.get(worker_id)
            if worker:
                worker.state = WorkerState.IDLE
                worker.current_job_id = None
                worker.consecutive_failures = 0
                # Record any produced assets into worker's cached assets
                for p in result.produced_assets:
                    if "name" in p:
                        worker.cached_assets.add(p["name"])

            # Clean up active tasks
            task = self.active_tasks.pop(job_id, None)
            if task and worker:
                # Add all required assets to worker cache as well
                for a in task.required_assets:
                    worker.cached_assets.add(a)

            # --- Broadcast new image/character to all other projects ---
            if task and task.task_type in (
                TaskType.IMAGE_CREATE, TaskType.IMAGE_CREATE_BY_UPLOAD,
                TaskType.CHARACTER_CREATE, TaskType.CHARACTER_CREATE_BY_UPLOAD
            ):
                is_bcast_task = task.task_type in (
                    TaskType.IMAGE_CREATE_BY_UPLOAD, TaskType.CHARACTER_CREATE_BY_UPLOAD
                )

                # --- Handle broadcast result callback ---
                if is_bcast_task:
                    origin_job_id = task.params.get("origin_job_id")
                    if origin_job_id and origin_job_id in self.jobs:
                        self.jobs[origin_job_id].setdefault("broadcast_results", {})
                        self.jobs[origin_job_id]["broadcast_results"][worker_id] = "success"
                        logger.info(f"Broadcast task {job_id} succeeded on {worker_id}, recorded in job {origin_job_id}")

                # --- Originating task: register assets into AssetHub + broadcast to other workers ---
                elif task.task_type in (TaskType.IMAGE_CREATE, TaskType.CHARACTER_CREATE):
                    is_image = task.task_type == TaskType.IMAGE_CREATE

                    # Register produced assets into AssetHub (covers master-local execution;
                    # worker-side uploads are handled via HTTP by upload_result_asset).
                    if self._asset_hub and result.produced_assets:
                        from pathlib import Path
                        from google_flow_mcp.cluster.models import AssetType
                        for p in result.produced_assets:
                            p_path = Path(p.get("local_path", ""))
                            p_name = p.get("name", "")
                            p_type = p.get("type", "image")
                            if p_path.exists() and p_name:
                                try:
                                    at = AssetType.CHARACTER if p_type == "character" else AssetType.IMAGE
                                    self._asset_hub.save_asset_file(
                                        name=p_name, asset_type=at,
                                        src_file_path=p_path, worker_id=worker_id
                                    )
                                    self.add_worker_cached_asset(worker_id, p_name)
                                    logger.info(f"Asset '{p_name}' registered into AssetHub from {p_path}")
                                except Exception as ae:
                                    logger.warning(f"Failed to register asset '{p_name}' into AssetHub: {ae}")

                    # Determine asset_name for broadcast
                    asset_name = None
                    if is_image:
                        for p in result.produced_assets:
                            if p.get("type") == "image" and "name" in p:
                                asset_name = p["name"]
                                break
                        if not asset_name:
                            asset_name = task.params.get("image_name")
                    else:
                        asset_name = task.params.get("character_name")

                    if asset_name:
                        # Initialize broadcast_results with the executing worker as 'success'
                        self.jobs[job_id].setdefault("broadcast_results", {})
                        self.jobs[job_id]["broadcast_results"][worker_id] = "success"

                        try:
                            # Broadcast to all other workers using the original project alias
                            original_project = task.project_alias

                            for wid, w in self.workers.items():
                                if wid == worker_id:
                                    continue
                                
                                broadcast_job_id = f"bcast_{uuid.uuid4().hex[:8]}"
                                if is_image:
                                    self.submit_task(
                                        task_type=TaskType.IMAGE_CREATE_BY_UPLOAD,
                                        project_alias=original_project,
                                        params={
                                            "image_name": asset_name,
                                            "origin_job_id": job_id,
                                        },
                                        required_assets=[asset_name],
                                        job_id=broadcast_job_id,
                                        target_worker_id=wid
                                    )
                                else:
                                    self.submit_task(
                                        task_type=TaskType.CHARACTER_CREATE_BY_UPLOAD,
                                        project_alias=original_project,
                                        params={
                                            "character_name": asset_name,
                                            "origin_job_id": job_id,
                                        },
                                        required_assets=[f"{asset_name}_Portrait", f"{asset_name}_Fullbody"],
                                        job_id=broadcast_job_id,
                                        target_worker_id=wid
                                    )
                                logger.info(
                                    f"Broadcasted {'image' if is_image else 'character'} '{asset_name}' "
                                    f"to worker {wid} project {original_project} (bcast_job={broadcast_job_id})"
                                )
                        except Exception as e:
                            logger.error(f"Failed to broadcast {'image' if is_image else 'character'} {asset_name}: {e}")

            # Update legacy job status dictionary
            job_dict = {
                "job_id": job_id,
                "status": "completed",
                "is_finished": True,
                "progress": 100,
                "progress_percent": 100,
                "progress_text": "100%",
                "worker_id": worker_id,
                "message": "Task completed successfully.",
                "next_action": "任务已顺利完成，智能体请停止轮询，可直接向用户汇报视频链接及本地文件。",
                **result.result_data,
            }
            if job_id in self.jobs:
                self.jobs[job_id].update(job_dict)
            else:
                self.jobs[job_id] = job_dict

            # Schedule next pending task
            self._schedule_next()

    def on_task_failed(self, job_id: str, error: str, worker_id: str = "") -> None:
        with self._lock:
            logger.error(f"Task {job_id} failed on worker {worker_id}: {error}")
            self._handle_worker_failure(worker_id, error, job_id)

    def _handle_worker_failure(self, worker_id: str, reason: str, failed_job_id: Optional[str] = None) -> None:
        """Handle worker failure or disconnect with automatic failover."""
        worker = self.workers.get(worker_id)
        job_id = failed_job_id or (worker.current_job_id if worker else None)

        if worker:
            worker.consecutive_failures += 1
            worker.current_job_id = None
            if worker.consecutive_failures >= 3:
                worker.state = WorkerState.UNHEALTHY
                logger.warning(f"Worker {worker_id} marked UNHEALTHY after 3 consecutive failures")
            else:
                worker.state = WorkerState.IDLE

        if not job_id:
            return

        task = self.active_tasks.pop(job_id, None)
        if not task:
            return

        # --- Broadcast task failure: write 'failed' into origin job's broadcast_results ---
        if task.task_type in (TaskType.IMAGE_CREATE_BY_UPLOAD, TaskType.CHARACTER_CREATE_BY_UPLOAD):
            origin_job_id = task.params.get("origin_job_id")
            if origin_job_id and origin_job_id in self.jobs:
                self.jobs[origin_job_id].setdefault("broadcast_results", {})
                self.jobs[origin_job_id]["broadcast_results"][worker_id] = "failed"
                logger.warning(f"Broadcast task {job_id} failed on {worker_id}, recorded in job {origin_job_id}")

        # Check if credits should be refunded (if failure occurred before generation started)
        last_status = self.jobs.get(job_id, {}).get("status", "")
        if last_status != "generating" and (task.deducted_daily_free > 0 or task.deducted_balance > 0):
            if worker and worker.account:
                AccountCache.refund_credits(
                    worker.account,
                    task.deducted_daily_free,
                    task.deducted_balance,
                )
                logger.info(
                    f"Refunded credits for job {job_id} on {worker.account}: "
                    f"free={task.deducted_daily_free}, bal={task.deducted_balance}"
                )
            task.deducted_daily_free = 0
            task.deducted_balance = 0

        # Failover logic
        if task.retry_count < self.max_retries:
            task.retry_count += 1
            if not task.target_worker_id:
                logger.warning(
                    f"Failover: Re-queueing task {job_id} (retry {task.retry_count}/{self.max_retries}) due to: {reason}"
                )
            else:
                logger.warning(
                    f"Re-queueing targeted task {job_id} for worker {task.target_worker_id} (retry {task.retry_count}/{self.max_retries}) due to: {reason}"
                )
            self.jobs[job_id].update({
                "status": "queued",
                "message": f"Retrying task after worker {worker_id} failure: {reason}. Retry {task.retry_count}/{self.max_retries}",
            })
            self.pending_tasks.appendleft(task)  # High priority retry
            self._schedule_next()
        else:
            logger.error(f"Task {job_id} permanently failed after {self.max_retries} retries: {reason}")
            self.jobs[job_id].update({
                "status": "error",
                "is_finished": True,
                "error": f"Max retries exceeded. Last error on {worker_id}: {reason}",
                "message": f"Task failed: {reason}",
            })

    def _health_check_loop(self) -> None:
        """Periodic health check detecting lost workers."""
        while self._running:
            time.sleep(5)
            with self._lock:
                now = time.time()
                for wid, w in list(self.workers.items()):
                    if w.state != WorkerState.DISCONNECTED and (now - w.last_heartbeat > self.heartbeat_timeout):
                        logger.warning(f"Worker {wid} heartbeat timeout ({now - w.last_heartbeat:.1f}s). Disconnecting.")
                        w.state = WorkerState.DISCONNECTED
                        self._worker_senders.pop(wid, None)
                        if w.current_job_id:
                            self._handle_worker_failure(wid, "Heartbeat timeout")
