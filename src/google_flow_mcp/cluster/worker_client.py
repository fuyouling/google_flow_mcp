import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Set
from loguru import logger
import websocket

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


class WorkerClient:
    """
    Worker client process running on each machine.
    Maintains an outbound WebSocket connection to Master,
    receives task assignments, executes JIT asset sync,
    automates Chrome via Page Objects, and uploads results.
    """

    def __init__(
        self,
        master_url: str = "http://127.0.0.1:8765",
        worker_id: str = "worker_1",
        account: str = "",
        cache_dir: Optional[Path] = None,
    ):
        self.master_url = master_url.rstrip("/")
        self.worker_id = worker_id
        self.account = account
        self.asset_syncer = AssetSyncer(self.master_url, cache_dir)

        # Mapping logical project alias -> local project UUID
        self.project_mappings: Dict[str, str] = {}
        # Set of assets uploaded into local project
        self.cached_assets: Set[str] = set()

        self._ws: Optional[websocket.WebSocketApp] = None
        self._running = False
        self._current_task: Optional[TaskPayload] = None
        self._cancel_flag = False

        self._load_local_project_cache()

    def _load_local_project_cache(self) -> None:
        """Load known projects from local projects_cache.json if available."""
        try:
            cache = ProjectCache.load()
            for pid, pdata in cache.get("projects", {}).items():
                title = pdata.get("name")
                if title:
                    self.project_mappings[title] = pid
            logger.info(f"Loaded {len(self.project_mappings)} local project mappings.")
        except Exception as e:
            logger.warning(f"Failed to load local project cache: {e}")

    def _resolve_project_id(self, tab, project_alias: str) -> str:
        """
        Resolve logical project alias to local Flow project UUID.
        If project alias looks like a UUID already present locally, use it.
        Otherwise, create the project on demand if not present.
        """
        # 1. Check existing mapping
        if project_alias in self.project_mappings:
            return self.project_mappings[project_alias]

        # 2. Check if alias is already a local UUID
        local_projects = ProjectCache.load().get("projects", {})
        if project_alias in local_projects:
            self.project_mappings[project_alias] = project_alias
            return project_alias

        # 3. Create new project in this worker's Flow account
        logger.info(f"Project '{project_alias}' not found in local account. Creating on demand...")
        home = FlowHomePage(tab)
        home.open()
        new_uuid = home.create_project()
        time.sleep(2)

        # Rename project to match alias
        try:
            home.open()
            home.rename_project(new_uuid, "Untitled project", project_alias)
        except Exception as e:
            logger.warning(f"Could not rename project on home page: {e}")

        self.project_mappings[project_alias] = new_uuid
        # Send update to Master
        self._send({
            "action": "update_project_mapping",
            "worker_id": self.worker_id,
            "project_alias": project_alias,
            "local_uuid": new_uuid,
        })
        logger.info(f"Project '{project_alias}' created locally with UUID: {new_uuid}")
        return new_uuid

    def _send(self, data: dict) -> None:
        if self._ws and self._ws.sock and self._ws.sock.connected:
            try:
                self._ws.send(json.dumps(data))
            except Exception as e:
                logger.error(f"WebSocket send error: {e}")

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            action = data.get("action")

            if action == "execute":
                task_payload = TaskPayload(**data["payload"])
                # Execute in background thread to avoid blocking WebSocket loop
                threading.Thread(
                    target=self._execute_task,
                    args=(task_payload,),
                    daemon=True,
                    name=f"TaskWorker-{task_payload.job_id[:8]}",
                ).start()

            elif action == "cancel":
                job_id = data.get("job_id")
                if self._current_task and self._current_task.job_id == job_id:
                    logger.warning(f"Cancellation received for job {job_id}")
                    self._cancel_flag = True

        except Exception as e:
            logger.error(f"Error processing WS message: {e}")

    def _on_open(self, ws):
        logger.info(f"Connected to Master at {self.master_url}")
        # Send registration
        reg_payload = {
            "action": "register",
            "worker_id": self.worker_id,
            "account": self.account,
            "project_mappings": self.project_mappings,
            "cached_assets": list(self.cached_assets),
        }
        self._send(reg_payload)

        # Start heartbeat
        def heartbeat_loop():
            while self._running and ws.sock and ws.sock.connected:
                time.sleep(5)
                self._send({"action": "heartbeat", "worker_id": self.worker_id})

        threading.Thread(target=heartbeat_loop, daemon=True, name="WorkerHeartbeat").start()

    def _on_error(self, ws, error):
        logger.warning(f"WebSocket connection error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        logger.warning(f"WebSocket closed: {close_status_code} - {close_msg}")

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

        def report_progress(status: str, msg: str):
            self._send({
                "action": "progress",
                "job_id": task.job_id,
                "status": status,
                "message": msg,
            })

        return execute_cluster_task(tab, project_id, task, progress_callback=report_progress)

    def run_forever(self) -> None:
        """Run WebSocket client loop with auto-reconnection."""
        self._running = True
        ws_url = self.master_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/worker"

        logger.info(f"Starting Worker {self.worker_id} connecting to {ws_url}...")

        while self._running:
            try:
                self._ws = websocket.WebSocketApp(
                    ws_url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(ping_interval=10, ping_timeout=5)
            except Exception as e:
                logger.error(f"Worker run error: {e}")

            if self._running:
                logger.info("Reconnecting to Master in 3 seconds...")
                time.sleep(3)

    def stop(self) -> None:
        self._running = False
        if self._ws:
            self._ws.close()


def main():
    import socket
    from google_flow_mcp.config import get_settings

    settings = get_settings()
    default_master = settings.cluster_master_url or "http://127.0.0.1:8765"
    default_id = (
        settings.worker_id
        if settings.worker_id and settings.worker_id != "master_local_worker"
        else f"worker_{socket.gethostname()}_{os.getpid()}"
    )
    default_account = settings.worker_account or ""

    parser = argparse.ArgumentParser(description="Google Flow MCP Cluster Worker Client")
    parser.add_argument("--master", default=default_master, help=f"Master server URL (default: {default_master})")
    parser.add_argument("--id", default=default_id, help=f"Unique Worker ID (default: {default_id})")
    parser.add_argument("--account", default=default_account, help=f"Google Account identifier (default: '{default_account}')")
    parser.add_argument("--auto-browser", action="store_true", help="Auto start browser on port 9222 if not running")
    args = parser.parse_args()

    if args.auto_browser:
        try:
            from utils.start_browser import is_port_in_use, launch_browser
            if not is_port_in_use(9222):
                logger.info("Auto-launching Chromium browser on port 9222...")
                launch_browser(detach=True, port=9222)
                time.sleep(2)
        except Exception as e:
            logger.warning(f"Failed to auto-launch browser: {e}")

    client = WorkerClient(
        master_url=args.master,
        worker_id=args.id,
        account=args.account,
    )
    try:
        client.run_forever()
    except KeyboardInterrupt:
        client.stop()


if __name__ == "__main__":
    main()

