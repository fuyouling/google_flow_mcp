import asyncio
import json
import threading
from pathlib import Path
from typing import Optional
from loguru import logger

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from google_flow_mcp.cluster.asset_hub import AssetHub
from google_flow_mcp.cluster.models import AssetType, TaskResult
from google_flow_mcp.cluster.scheduler import ClusterScheduler


class MasterServer:
    """
    HTTP and WebSocket Master Server.
    Provides:
    - WebSocket endpoint for Worker connections, dispatching, and heartbeats
    - HTTP file streaming endpoints for JIT asset downloading and result uploading
    - Runs cleanly in a background daemon thread
    """

    def __init__(
        self,
        scheduler: ClusterScheduler,
        asset_hub: AssetHub,
        host: str = "0.0.0.0",
        port: int = 8765,
    ):
        self.scheduler = scheduler
        self.asset_hub = asset_hub
        self.host = host
        self.port = port

        self._uvicorn_server: Optional[uvicorn.Server] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.app = self._build_app()

    def _build_app(self) -> Starlette:
        routes = [
            WebSocketRoute("/ws/worker", self._handle_worker_ws),
            Route("/api/assets/download/{asset_name:path}", self._handle_asset_download, methods=["GET"]),
            Route("/api/assets/upload", self._handle_asset_upload, methods=["POST"]),
            Route("/api/assets/info/{asset_name:path}", self._handle_asset_info, methods=["GET"]),
            Route("/api/cluster/status", self._handle_cluster_status, methods=["GET"]),
        ]
        return Starlette(routes=routes)

    # ── WebSocket Handler ────────────────────────────────────

    async def _handle_worker_ws(self, ws: WebSocket) -> None:
        await ws.accept()
        worker_id = None
        client_ip = ws.client.host if ws.client else "unknown"

        try:
            # First message must be registration
            init_data = await ws.receive_json()
            if init_data.get("action") != "register":
                await ws.close(code=1008)
                return

            worker_id = init_data.get("worker_id")
            if not worker_id:
                await ws.close(code=1008)
                return

            account = init_data.get("account", "")
            project_mappings = init_data.get("project_mappings", {})
            cached_assets = set(init_data.get("cached_assets", []))

            current_loop = asyncio.get_running_loop()

            # Thread-safe sender function to push to this websocket
            def send_to_worker(msg: dict) -> None:
                target_loop = self._loop or current_loop
                try:
                    running = asyncio.get_running_loop()
                    if running is target_loop:
                        target_loop.create_task(ws.send_json(msg))
                        return
                except RuntimeError:
                    pass
                if target_loop and target_loop.is_running():
                    asyncio.run_coroutine_threadsafe(ws.send_json(msg), target_loop)

            self.scheduler.register_worker(
                worker_id=worker_id,
                ip=client_ip,
                account=account,
                project_mappings=project_mappings,
                cached_assets=cached_assets,
                sender=send_to_worker,
            )

            await ws.send_json({"action": "registered", "worker_id": worker_id})

            # Process incoming messages from worker
            while True:
                data = await ws.receive_json()
                action = data.get("action")

                if action == "heartbeat":
                    self.scheduler.heartbeat(worker_id)
                elif action == "progress":
                    self.scheduler.on_task_progress(
                        job_id=data.get("job_id", ""),
                        status=data.get("status", ""),
                        message=data.get("message", ""),
                    )
                elif action == "completed":
                    result_data = data.get("result", {})
                    task_result = TaskResult(**result_data)
                    self.scheduler.on_task_completed(task_result)
                elif action == "failed":
                    self.scheduler.on_task_failed(
                        job_id=data.get("job_id", ""),
                        error=data.get("error", "Unknown execution error"),
                        worker_id=worker_id,
                    )
                elif action == "update_project_mapping":
                    self.scheduler.update_worker_project_mapping(
                        worker_id=worker_id,
                        project_alias=data.get("project_alias", ""),
                        local_uuid=data.get("local_uuid", ""),
                    )

        except WebSocketDisconnect:
            logger.warning(f"Worker {worker_id} disconnected.")
        except Exception as e:
            logger.error(f"Error on worker {worker_id} WS: {e}")
        finally:
            if worker_id:
                self.scheduler.unregister_worker(worker_id)

    # ── HTTP Handlers ────────────────────────────────────────

    async def _handle_asset_download(self, request: Request) -> Response:
        asset_name = request.path_params.get("asset_name", "")
        file_path = self.asset_hub.get_asset_file_path(asset_name)

        if not file_path or not file_path.exists():
            return JSONResponse(
                {"error": f"Asset '{asset_name}' not found in hub."}, status_code=404
            )

        return FileResponse(
            path=file_path,
            filename=file_path.name,
        )

    async def _handle_asset_upload(self, request: Request) -> Response:
        try:
            form = await request.form()
            name = form.get("name")
            asset_type_str = form.get("asset_type", "image")
            worker_id = form.get("worker_id", "")
            upload_file = form.get("file")

            if not name or not upload_file:
                return JSONResponse(
                    {"error": "Missing 'name' or 'file' form field."}, status_code=400
                )

            content = await upload_file.read()
            ext = Path(upload_file.filename).suffix.lstrip(".") if upload_file.filename else "png"

            try:
                asset_type = AssetType(asset_type_str)
            except ValueError:
                asset_type = AssetType.IMAGE

            meta = self.asset_hub.save_asset(
                name=name,
                asset_type=asset_type,
                file_bytes=content,
                file_ext=ext,
                worker_id=worker_id,
            )

            # Inform scheduler that this asset is available
            if worker_id:
                self.scheduler.add_worker_cached_asset(worker_id, name)

            return JSONResponse({
                "success": True,
                "asset": meta.model_dump(),
            })
        except Exception as e:
            logger.error(f"Asset upload failed: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    async def _handle_asset_info(self, request: Request) -> Response:
        asset_name = request.path_params.get("asset_name", "")
        meta = self.asset_hub.get_asset(asset_name)
        if not meta:
            return JSONResponse({"exists": False}, status_code=404)
        return JSONResponse({"exists": True, "asset": meta.model_dump()})

    async def _handle_cluster_status(self, request: Request) -> Response:
        workers = [w.model_dump() for w in self.scheduler.get_workers()]
        # Convert sets to lists in WorkerInfo dump
        for w in workers:
            if "cached_assets" in w and isinstance(w["cached_assets"], set):
                w["cached_assets"] = list(w["cached_assets"])

        return JSONResponse({
            "worker_count": len(workers),
            "pending_tasks": len(self.scheduler.pending_tasks),
            "active_tasks": len(self.scheduler.active_tasks),
            "workers": workers,
        })

    # ── Server Lifecycle ─────────────────────────────────────

    def start(self) -> None:
        """Start the Uvicorn server in a background thread."""
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self._uvicorn_server = uvicorn.Server(config)

        def run_server():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._uvicorn_server.run()

        self._thread = threading.Thread(target=run_server, daemon=True, name="ClusterMasterServer")
        self._thread.start()
        logger.info(f"Cluster Master Server started on http://{self.host}:{self.port}")

    def stop(self) -> None:
        if self._uvicorn_server:
            self._uvicorn_server.should_exit = True
            logger.info("Cluster Master Server stopping...")
