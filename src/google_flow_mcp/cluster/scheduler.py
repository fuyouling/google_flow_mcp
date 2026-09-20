import time
import uuid
import threading
from typing import Callable, Dict, List, Optional, Set
from collections import deque
from loguru import logger

from google_flow_mcp.cluster.models import (
    TaskPayload,
    TaskResult,
    TaskStatus,
    TaskType,
    WorkerInfo,
    WorkerState,
)


class ClusterScheduler:
    """
    Centralized task scheduler on the Master node.
    Features:
    - Worker pool & heartbeat tracking
    - FIFO Task Queue with Affinity Routing (routes to workers that already have required assets)
    - Automatic Failover & Retry when workers disconnect or fail
    - Compatible with legacy task_manager job dictionary format
    """

    def __init__(self, max_retries: int = 2, heartbeat_timeout: float = 30.0):
        self.max_retries = max_retries
        self.heartbeat_timeout = heartbeat_timeout
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
            info = WorkerInfo(
                worker_id=worker_id,
                ip=ip,
                account=account,
                state=WorkerState.IDLE,
                project_mappings=project_mappings or {},
                cached_assets=cached_assets or set(),
                last_heartbeat=time.time(),
            )
            self.workers[worker_id] = info
            if sender:
                self._worker_senders[worker_id] = sender
            logger.info(f"Worker registered: {worker_id} (IP: {ip}, Account: {account})")
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
            return list(self.workers.values())

    def update_worker_project_mapping(self, worker_id: str, project_alias: str, local_uuid: str) -> None:
        with self._lock:
            worker = self.workers.get(worker_id)
            if worker:
                worker.project_mappings[project_alias] = local_uuid
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
    ) -> str:
        with self._lock:
            jid = job_id or str(uuid.uuid4())
            req_assets = required_assets or []
            task = TaskPayload(
                job_id=jid,
                task_type=task_type,
                project_alias=project_alias,
                params=params,
                required_assets=req_assets,
            )

            # Initialize legacy status dict
            self.jobs[jid] = {
                "job_id": jid,
                "status": "queued",
                "is_finished": False,
                "task_type": task_type.value,
                "project_alias": project_alias,
                "message": f"Task queued in cluster. Queue position: {len(self.pending_tasks) + 1}",
                "queue_position": len(self.pending_tasks) + 1,
            }

            self.pending_tasks.append(task)
            logger.info(f"Task submitted to cluster: job_id={jid}, type={task_type.value}")
            self._schedule_next()
            return jid

    def cancel_task(self, job_id: str) -> bool:
        with self._lock:
            # 1. Check pending queue
            for t in list(self.pending_tasks):
                if t.job_id == job_id:
                    self.pending_tasks.remove(t)
                    self.jobs[job_id] = {
                        "job_id": job_id,
                        "status": "cancelled",
                        "is_finished": True,
                        "message": "Task was cancelled before execution.",
                    }
                    logger.info(f"Task {job_id} cancelled from queue.")
                    return True

            # 2. Check active tasks
            if job_id in self.active_tasks:
                task = self.active_tasks[job_id]
                worker_id = task.target_worker_id
                sender = self._worker_senders.get(worker_id)
                if sender:
                    try:
                        sender({"action": "cancel", "job_id": job_id})
                    except Exception as e:
                        logger.error(f"Failed to send cancel signal to {worker_id}: {e}")

                self.jobs[job_id]["status"] = "cancelled"
                self.jobs[job_id]["is_finished"] = True
                self.jobs[job_id]["message"] = "Task execution cancelled."
                return True

            return False

    def _select_best_worker(self, task: TaskPayload) -> Optional[str]:
        """
        Affinity routing:
        1. Only consider IDLE workers.
        2. Score workers based on how many required_assets they already have cached.
        3. Break ties by fewest consecutive failures.
        """
        candidate_ids = [
            wid
            for wid, w in self.workers.items()
            if w.state == WorkerState.IDLE and wid in self._worker_senders
        ]
        if not candidate_ids:
            return None

        if not task.required_assets:
            # No specific asset affinity needed, pick worker with fewest failures
            return min(candidate_ids, key=lambda wid: self.workers[wid].consecutive_failures)

        req_set = set(task.required_assets)

        def worker_score(wid: str) -> tuple[int, int]:
            w = self.workers[wid]
            hit_count = len(w.cached_assets.intersection(req_set))
            # higher hit_count is better; lower consecutive_failures is better
            return (hit_count, -w.consecutive_failures)

        best_wid = max(candidate_ids, key=worker_score)
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
                        "payload": task.model_dump(),
                    }
                    sender(payload_dict)
                    logger.info(
                        f"Task {task.job_id} dispatched to worker {best_worker_id} "
                        f"(affinity match: {len(worker.cached_assets.intersection(set(task.required_assets)))}/{len(task.required_assets)})"
                    )
                except Exception as e:
                    logger.error(f"Failed to send task to {best_worker_id}: {e}")
                    self._handle_worker_failure(best_worker_id, f"Send failure: {e}")

    # ── Task Execution Feedback ──────────────────────────────

    def on_task_progress(self, job_id: str, status: str, message: str) -> None:
        with self._lock:
            if job_id in self.jobs:
                self.jobs[job_id]["status"] = status
                self.jobs[job_id]["message"] = message

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

            # Update legacy job status dictionary
            job_dict = {
                "job_id": job_id,
                "status": "completed",
                "is_finished": True,
                "worker_id": worker_id,
                "message": "Task completed successfully.",
                **result.result_data,
            }
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

        # Failover logic
        if task.retry_count < self.max_retries:
            task.retry_count += 1
            task.target_worker_id = None
            logger.warning(
                f"Failover: Re-queueing task {job_id} (retry {task.retry_count}/{self.max_retries}) due to: {reason}"
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
