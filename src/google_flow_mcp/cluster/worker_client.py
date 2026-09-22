import argparse
import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Set
from loguru import logger

import grpc
from grpc import aio as grpc_aio

from google_flow_mcp.cluster.proto import cluster_pb2, cluster_pb2_grpc
from google_flow_mcp.browser.session import get_browser
from google_flow_mcp.cluster.asset_syncer import AssetSyncer
from google_flow_mcp.cluster.models import (
    AssetType,
    TaskPayload,
    TaskResult,
    TaskStatus,
    TaskType,
)
from google_flow_mcp.pages.flow_home_page import FlowHomePage
from google_flow_mcp.models.project_cache import ProjectCache

# ── 全局单例注册 ────────────────────────────────────────────────
# 由 WorkerClient.__init__ 注册，供其他模块（如 website_open）通过
# get_worker_client() 获取当前进程的 WorkerClient 实例。
_worker_client_instance: Optional["WorkerClient"] = None


def get_worker_client() -> Optional["WorkerClient"]:
    """返回当前进程的 WorkerClient 单例，非 Worker 进程返回 None。"""
    return _worker_client_instance


def register_worker_client(client: Optional["WorkerClient"]) -> None:
    """注册（或注销）WorkerClient 单例。"""
    global _worker_client_instance
    _worker_client_instance = client


class WorkerClient:
    """
    Worker client process running on each machine.
    Maintains a gRPC bidirectional stream to Master via StreamTasks(),
    receives task assignments, executes JIT asset sync,
    automates Chrome via Page Objects, and uploads results.
    """

    def __init__(
        self,
        master_url: str = "http://127.0.0.1:8765",
        worker_id: str = "worker_1",
        account: str = "",
        cache_dir: Optional[Path] = None,
        grpc_target: str = "127.0.0.1:50051",
    ):
        self.master_url = master_url.rstrip("/")
        self.grpc_target = grpc_target
        self.worker_id = worker_id
        self.account = account
        self.asset_syncer = AssetSyncer(self.master_url, cache_dir)

        # Mapping logical project alias -> local project UUID
        self.project_mappings: Dict[str, str] = {}
        # Set of assets uploaded into local project
        self.cached_assets: Set[str] = set()

        self._running = False
        self._current_task: Optional[TaskPayload] = None
        self._cancel_flag = False

        # gRPC outbox: messages to send to Master via the bidirectional stream
        self._outbox: Optional[asyncio.Queue] = None
        # event loop of the gRPC stream (for cross-thread put_nowait)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        self._load_local_project_cache()

        # 注册为全局单例，供 website_open 等工具在 Worker 进程中调用
        register_worker_client(self)


    def _load_local_project_cache(self) -> None:
        """Load known projects from local projects_cache.json if available."""
        try:
            cache = ProjectCache.load()
            for pid, pdata in cache.get("projects", {}).items():
                title = pdata.get("name")
                if title:
                    self.project_mappings[title] = pid
                self.project_mappings[pid] = pid
            logger.info(f"Loaded {len(self.project_mappings)} local project mappings.")
        except Exception as e:
            logger.warning(f"Failed to load local project cache: {e}")

    def _resolve_project_id(self, tab, project_alias: str) -> str:
        """
        Resolve logical project alias to local Flow project UUID.
        If project alias looks like a UUID already present locally, use it.
        Otherwise, create the project on demand if not present.
        """
        clean_alias = (project_alias or "").strip()
        local_projects = ProjectCache.load().get("projects", {})

        # 0. If alias is empty, default to the most recently accessed local project
        if not clean_alias:
            if local_projects:
                latest_pid = max(
                    local_projects.keys(),
                    key=lambda k: local_projects[k].get("last_accessed", "")
                )
                logger.info(f"No project_alias specified. Defaulting to most recently accessed project: {latest_pid}")
                return latest_pid
            clean_alias = "default"

        # 1. Check existing mapping (name or UUID)
        if clean_alias in self.project_mappings:
            return self.project_mappings[clean_alias]

        # 2. Check if alias is already a local UUID
        if clean_alias in local_projects:
            self.project_mappings[clean_alias] = clean_alias
            return clean_alias

        # 3. Create new project in this worker's Flow account
        logger.info(f"Project '{clean_alias}' not found in local account. Creating on demand...")
        home = FlowHomePage(tab)
        home.open()
        new_uuid = home.create_project()
        time.sleep(2)

        # Rename project to match alias if not default
        if clean_alias and clean_alias != "default":
            try:
                home.open()
                home.rename_project(new_uuid, "Untitled project", clean_alias)
            except Exception as e:
                logger.warning(f"Could not rename project on home page: {e}")

        self.project_mappings[clean_alias] = new_uuid
        # Send update to Master
        self._send({
            "action": "update_project_mapping",
            "worker_id": self.worker_id,
            "project_alias": clean_alias,
            "local_uuid": new_uuid,
        })
        logger.info(f"Project '{clean_alias}' created locally with UUID: {new_uuid}")
        return new_uuid

    def _send(self, data: dict) -> None:
        """
        Send a message to Master via the gRPC stream outbox.
        Thread-safe: can be called from executor threads.
        """
        msg = self._dict_to_worker_message(data)
        if msg is None:
            return

        if self._outbox is None or self._loop is None:
            logger.warning("gRPC outbox not ready, dropping message")
            return

        try:
            if self._loop.is_running():
                self._loop.call_soon_threadsafe(self._outbox.put_nowait, msg)
            else:
                logger.warning("gRPC event loop not running, dropping message")
        except Exception as e:
            logger.error(f"gRPC send error: {e}")

    def _dict_to_worker_message(self, data: dict) -> Optional[cluster_pb2.WorkerMessage]:
        """Convert legacy dict format to Protobuf WorkerMessage."""
        action = data.get("action")

        if action == "heartbeat":
            return cluster_pb2.WorkerMessage(
                heartbeat=cluster_pb2.HeartbeatRequest(worker_id=self.worker_id)
            )
        elif action == "progress":
            return cluster_pb2.WorkerMessage(
                progress=cluster_pb2.TaskProgressReport(
                    job_id=data.get("job_id", ""),
                    status=data.get("status", ""),
                    message=data.get("message", ""),
                    progress_percent=data.get("progress", data.get("progress_percent", 0)),
                    progress_text=data.get("progress_text", ""),
                    elapsed_seconds=data.get("elapsed_seconds", 0.0),
                    next_action=data.get("next_action", ""),
                )
            )
        elif action == "completed":
            result = data.get("result", {})
            return cluster_pb2.WorkerMessage(
                completed=cluster_pb2.TaskCompletedReport(
                    job_id=result.get("job_id", ""),
                    worker_id=result.get("worker_id", self.worker_id),
                    status=result.get("status", "completed"),
                    result_json=json.dumps(result),
                )
            )
        elif action == "failed":
            return cluster_pb2.WorkerMessage(
                failed=cluster_pb2.TaskFailedReport(
                    job_id=data.get("job_id", ""),
                    worker_id=data.get("worker_id", self.worker_id),
                    error=data.get("error", "Unknown error"),
                )
            )
        elif action == "update_project_mapping":
            return cluster_pb2.WorkerMessage(
                project_mapping=cluster_pb2.ProjectMappingUpdate(
                    worker_id=data.get("worker_id", self.worker_id),
                    project_alias=data.get("project_alias", ""),
                    local_uuid=data.get("local_uuid", ""),
                )
            )
        elif action == "update_account_info":
            msg = cluster_pb2.WorkerMessage(
                account_info=cluster_pb2.AccountInfoUpdate(
                    worker_id=data.get("worker_id", self.worker_id),
                    email=data.get("email", ""),
                )
            )
            credits_val = data.get("credits")
            if credits_val is not None:
                msg.account_info.credits = int(credits_val)
            return msg
        else:
            logger.warning(f"Unknown action for WorkerMessage: {action}")
            return None

    async def _message_generator(self):
        """Async generator: yields WorkerMessage items to send to Master."""
        # First message: register
        yield cluster_pb2.WorkerMessage(
            register=cluster_pb2.RegisterRequest(
                worker_id=self.worker_id,
                account=self.account,
                project_mappings=self.project_mappings,
                cached_assets=list(self.cached_assets),
            )
        )

        # Then yield from outbox
        while self._running:
            try:
                msg = await asyncio.wait_for(self._outbox.get(), timeout=1.0)
                yield msg
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Message generator error: {e}")
                break

    async def _heartbeat_loop(self):
        """Send periodic heartbeat messages."""
        while self._running:
            await asyncio.sleep(5)
            self._send({"action": "heartbeat", "worker_id": self.worker_id})

    async def _run_stream(self):
        """Establish gRPC bidirectional stream and process messages."""
        self._outbox = asyncio.Queue()
        self._loop = asyncio.get_running_loop()

        channel = grpc_aio.insecure_channel(self.grpc_target)
        try:
            stub = cluster_pb2_grpc.ClusterServiceStub(channel)
            logger.info(f"Connecting to Master gRPC at {self.grpc_target}...")

            response_stream = stub.StreamTasks(self._message_generator())

            # Start heartbeat
            heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            try:
                async for msg in response_stream:
                    payload_type = msg.WhichOneof("payload")

                    if payload_type == "registered":
                        logger.info(f"Registered with Master: {msg.registered.worker_id}")

                    elif payload_type == "execute":
                        task_payload = TaskPayload(**json.loads(msg.execute.payload_json))
                        # Execute in background thread to avoid blocking gRPC loop
                        threading.Thread(
                            target=self._execute_task,
                            args=(task_payload,),
                            daemon=True,
                            name=f"TaskWorker-{task_payload.job_id[:8]}",
                        ).start()

                    elif payload_type == "cancel":
                        job_id = msg.cancel.job_id
                        if self._current_task and self._current_task.job_id == job_id:
                            logger.warning(f"Cancellation received for job {job_id}")
                            self._cancel_flag = True

            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
        finally:
            await channel.close()

    def _execute_task(self, task: TaskPayload) -> None:
        """Main task execution pipeline."""
        self._current_task = task
        self._cancel_flag = False
        job_id = task.job_id
        logger.info(f"Worker {self.worker_id} starting task {job_id} ({task.task_type.value})")

        try:
            # 1. Obtain browser session
            browser = get_browser()
            tab = browser.latest_tab

            # 2. Resolve local project UUID
            self._send({
                "action": "progress",
                "job_id": job_id,
                "status": "syncing_assets",
                "message": "Resolving local project UUID...",
            })
            local_project_id = self._resolve_project_id(tab, task.project_alias)

            # 3. JIT Asset Synchronization (no shared folders needed)
            if task.required_assets:
                self._send({
                    "action": "progress",
                    "job_id": job_id,
                    "status": "syncing_assets",
                    "message": f"Checking & downloading {len(task.required_assets)} reference assets...",
                })
                self.asset_syncer.ensure_assets(
                    tab, local_project_id, task.required_assets, self.cached_assets
                )

            if self._cancel_flag:
                raise Exception("Task was cancelled by user.")

            # 4. Execute specific generation task logic
            self._send({
                "action": "progress",
                "job_id": job_id,
                "status": "generating",
                "message": f"Running {task.task_type.value} in local Flow project...",
            })

            result_data, produced_assets = self._dispatch_to_page_objects(
                tab, local_project_id, task
            )

            # 5. Upload any produced assets back to Master
            for p in produced_assets:
                p_name = p.get("name")
                p_path = Path(p.get("local_path", ""))
                p_type = p.get("type", "image")
                if p_path.exists():
                    self.asset_syncer.upload_result_asset(
                        worker_id=self.worker_id,
                        asset_name=p_name,
                        file_path=p_path,
                        asset_type=p_type,
                    )
                    self.cached_assets.add(p_name)

            # 6. Report completion
            res = TaskResult(
                job_id=job_id,
                worker_id=self.worker_id,
                status=TaskStatus.COMPLETED,
                result_data=result_data,
                produced_assets=produced_assets,
            )
            self._send({
                "action": "completed",
                "result": res.model_dump(),
            })
            logger.info(f"Task {job_id} successfully executed and reported.")

        except Exception as e:
            logger.error(f"Task {job_id} execution failed on worker {self.worker_id}: {e}")
            self._send({
                "action": "failed",
                "job_id": job_id,
                "error": str(e),
                "worker_id": self.worker_id,
            })
        finally:
            self._current_task = None
            self._cancel_flag = False

    def _dispatch_to_page_objects(
        self, tab, project_id: str, task: TaskPayload
    ) -> tuple[dict, list]:
        """Dispatch task to executor logic."""
        from google_flow_mcp.cluster.executor import execute_cluster_task

        def report_progress(status: str, msg: str, extra: Optional[dict] = None):
            payload = {
                "action": "progress",
                "job_id": task.job_id,
                "status": status,
                "message": msg,
            }
            if extra:
                payload.update(extra)
            self._send(payload)

        return execute_cluster_task(tab, project_id, task, progress_callback=report_progress)

    def run_forever(self) -> None:
        """Run gRPC client loop with auto-reconnection."""
        self._running = True

        logger.info(f"Starting Worker {self.worker_id} connecting to gRPC {self.grpc_target}...")

        while self._running:
            try:
                asyncio.run(self._run_stream())
            except Exception as e:
                logger.error(f"Worker gRPC stream error: {e}")

            if self._running:
                logger.info("Reconnecting to Master in 3 seconds...")
                time.sleep(3)

    def stop(self) -> None:
        self._running = False
        # 注销全局单例
        register_worker_client(None)

    def report_account_info(self, email: str, credits: Optional[int]) -> None:
        """
        通过 gRPC 向 Master 上报账号信息与点数。
        Master 收到后会将数据写入 account_cache.json。
        """
        if not email:
            return
        self._send({
            "action": "update_account_info",
            "worker_id": self.worker_id,
            "email": email,
            "credits": credits,
        })
        logger.info(f"report_account_info: 上报 email={email}, credits={credits} 至 master")



def main():
    import socket
    from google_flow_mcp.config import get_settings

    settings = get_settings()
    default_grpc_target = settings.cluster_grpc_target or "127.0.0.1:50051"
    default_master = settings.cluster_master_url or "http://127.0.0.1:8765"
    default_id = (
        settings.worker_id
        if settings.worker_id and settings.worker_id != "master_local_worker"
        else f"worker_{socket.gethostname()}_{os.getpid()}"
    )
    default_account = settings.worker_account or ""

    parser = argparse.ArgumentParser(description="Google Flow MCP Cluster Worker Client")
    parser.add_argument("--master", default=default_master, help=f"Master HTTP URL for assets (default: {default_master})")
    parser.add_argument("--grpc-target", default=default_grpc_target, help=f"Master gRPC target (default: {default_grpc_target})")
    parser.add_argument("--id", default=default_id, help=f"Unique Worker ID (default: {default_id})")
    parser.add_argument("--account", default=default_account, help=f"Google Account identifier (default: '{default_account}')")
    parser.add_argument("--auto-browser", action="store_true", help="Auto start browser on configured port (default 9222) if not running")
    args = parser.parse_args()

    if args.auto_browser:
        try:
            from google_flow_mcp.browser.start_browser import is_port_in_use, launch_browser
            from google_flow_mcp.browser.launcher import get_browser_port
            port = get_browser_port()
            if not is_port_in_use(port):
                logger.info(f"Auto-launching Chromium browser on port {port}...")
                launch_browser(detach=True, port=port)
                time.sleep(2)
        except Exception as e:
            logger.warning(f"Failed to auto-launch browser: {e}")

    client = WorkerClient(
        master_url=args.master,
        worker_id=args.id,
        account=args.account,
        grpc_target=args.grpc_target,
    )
    try:
        client.run_forever()
    except KeyboardInterrupt:
        client.stop()


if __name__ == "__main__":
    main()
