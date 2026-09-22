import asyncio
import json
import threading
from pathlib import Path
from typing import Optional
from loguru import logger

import grpc
from grpc import aio as grpc_aio

import uvicorn
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse

from google_flow_mcp.cluster.proto import cluster_pb2, cluster_pb2_grpc
from google_flow_mcp.cluster.asset_hub import AssetHub
from google_flow_mcp.cluster.models import AssetType, TaskResult
from google_flow_mcp.cluster.scheduler import ClusterScheduler


class ClusterServiceServicer(cluster_pb2_grpc.ClusterServiceServicer):
    """
    gRPC Bidirectional-stream handler for Worker connections.
    Each Worker opens a StreamTasks() RPC; messages flow in both directions.
    """

    def __init__(self, scheduler: ClusterScheduler):
        self.scheduler = scheduler

    async def StreamTasks(self, request_iterator, context):
        worker_id = None
        # Per-worker outbox: Scheduler writes here, this coroutine reads and yields
        outbox: asyncio.Queue = asyncio.Queue()

        try:
            # ── 1. First message must be RegisterRequest ─────────────
            first_msg: cluster_pb2.WorkerMessage = await context.read()
            if first_msg is None or first_msg.WhichOneof("payload") != "register":
                await context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    "First message must be RegisterRequest",
                )
                return

            reg = first_msg.register
            worker_id = reg.worker_id
            client_ip = context.peer() or "unknown"

            # sender callback: Scheduler calls this to push messages to Worker
            def sender(msg: dict) -> None:
                try:
                    outbox.put_nowait(msg)
                except Exception as e:
                    logger.error(f"Failed to enqueue message for worker {worker_id}: {e}")

            self.scheduler.register_worker(
                worker_id=worker_id,
                ip=client_ip,
                account=reg.account,
                project_mappings=dict(reg.project_mappings),
                cached_assets=set(reg.cached_assets),
                sender=sender,
            )

            # Send registration confirmation
            await context.write(
                cluster_pb2.MasterMessage(
                    registered=cluster_pb2.RegisterResponse(
                        worker_id=worker_id, success=True
                    )
                )
            )
            logger.info(f"Worker {worker_id} registered via gRPC from {client_ip}")

            # ── 2. Bidirectional message loop ────────────────────────
            # Two concurrent coroutines:
            #   - reader: reads Worker→Master messages from the stream
            #   - writer: reads from outbox and writes Master→Worker messages

            read_done = asyncio.Event()

            async def reader():
                """Read incoming Worker messages."""
                try:
                    while True:
                        msg = await context.read()
                        if msg == grpc_aio.EOF:
                            break
                        self._handle_worker_message(worker_id, msg)
                except Exception as e:
                    logger.warning(f"Worker {worker_id} reader error: {e}")
                finally:
                    read_done.set()

            async def writer():
                """Write outgoing Master messages to the Worker."""
                try:
                    while not read_done.is_set():
                        try:
                            msg_dict = await asyncio.wait_for(outbox.get(), timeout=1.0)
                        except asyncio.TimeoutError:
                            continue

                        master_msg = self._dict_to_master_message(msg_dict)
                        if master_msg:
                            await context.write(master_msg)
                except Exception as e:
                    logger.warning(f"Worker {worker_id} writer error: {e}")

            reader_task = asyncio.create_task(reader())
            writer_task = asyncio.create_task(writer())

            # Wait until the reader finishes (Worker disconnected)
            await reader_task
            # Signal writer to stop and wait
            read_done.set()
            await writer_task

        except Exception as e:
            logger.error(f"Error in StreamTasks for worker {worker_id}: {e}")
        finally:
            if worker_id:
                self.scheduler.unregister_worker(worker_id)
                logger.info(f"Worker {worker_id} disconnected from gRPC stream.")

    def _handle_worker_message(self, worker_id: str, msg: cluster_pb2.WorkerMessage) -> None:
        """Dispatch an incoming Worker message to the scheduler."""
        payload_type = msg.WhichOneof("payload")

        if payload_type == "heartbeat":
            self.scheduler.heartbeat(worker_id)

        elif payload_type == "progress":
            p = msg.progress
            extra = {}
            if p.progress_percent:
                extra["progress"] = p.progress_percent
                extra["progress_percent"] = p.progress_percent
            if p.progress_text:
                extra["progress_text"] = p.progress_text
            if p.elapsed_seconds:
                extra["elapsed_seconds"] = p.elapsed_seconds
            if p.next_action:
                extra["next_action"] = p.next_action
            self.scheduler.on_task_progress(
                job_id=p.job_id,
                status=p.status,
                message=p.message,
                extra=extra if extra else None,
            )

        elif payload_type == "completed":
            c = msg.completed
            try:
                result_data = json.loads(c.result_json) if c.result_json else {}
                task_result = TaskResult(**result_data)
                self.scheduler.on_task_completed(task_result)
            except Exception as e:
                logger.error(f"Failed to parse TaskResult from worker {worker_id}: {e}")
                self.scheduler.on_task_failed(
                    job_id=c.job_id, error=f"Result parse error: {e}", worker_id=worker_id
                )

        elif payload_type == "failed":
            f = msg.failed
            self.scheduler.on_task_failed(
                job_id=f.job_id, error=f.error, worker_id=f.worker_id or worker_id
            )

        elif payload_type == "project_mapping":
            pm = msg.project_mapping
            self.scheduler.update_worker_project_mapping(
                worker_id=worker_id,
                project_alias=pm.project_alias,
                local_uuid=pm.local_uuid,
            )

        elif payload_type == "account_info":
            ai = msg.account_info
            from google_flow_mcp.models.account_cache import AccountCache
            email = ai.email
            credits = ai.credits if ai.HasField("credits") else None
            if email:
                AccountCache.update(email=email, credits=credits, worker_id=worker_id)
                if worker_id in self.scheduler.workers:
                    w = self.scheduler.workers[worker_id]
                    w.account = email
                    acc_info = AccountCache.get_account_credits(email)
                    w.credits = acc_info.get("credits")
                    w.daily_free_remaining = acc_info.get("daily_free_remaining", 50)
                logger.info(
                    f"Master: account_cache updated from worker {worker_id} "
                    f"(email={email}, credits={credits})"
                )

    @staticmethod
    def _dict_to_master_message(msg: dict) -> Optional[cluster_pb2.MasterMessage]:
        """Convert a scheduler dict message to a Protobuf MasterMessage."""
        action = msg.get("action")
        if action == "execute":
            return cluster_pb2.MasterMessage(
                execute=cluster_pb2.ExecuteTask(
                    payload_json=json.dumps(msg.get("payload", {}))
                )
            )
        elif action == "cancel":
            return cluster_pb2.MasterMessage(
                cancel=cluster_pb2.CancelTask(job_id=msg.get("job_id", ""))
            )
        else:
            logger.warning(f"Unknown action in outbox message: {action}")
            return None


class MasterServer:
    """
    Dual-port Master Server:
    - gRPC server (default :50051): Worker bidirectional streaming
    - HTTP server (default :8765):  Asset download/upload, cluster status API
    """

    def __init__(
        self,
        scheduler: ClusterScheduler,
        asset_hub: AssetHub,
        host: str = "0.0.0.0",
        grpc_port: int = 50051,
        http_port: int = 8765,
    ):
        self.scheduler = scheduler
        self.asset_hub = asset_hub
        self.host = host
        self.grpc_port = grpc_port
        self.http_port = http_port

        self._grpc_server: Optional[grpc_aio.Server] = None
        self._grpc_thread: Optional[threading.Thread] = None
        self._http_thread: Optional[threading.Thread] = None
        self._fastapi_app = self._build_fastapi_app()

    # ── FastAPI HTTP App (Assets + Status) ───────────────────

    def _build_fastapi_app(self) -> FastAPI:
        app = FastAPI(title="Google Flow MCP Cluster", docs_url=None, redoc_url=None)

        @app.get("/api/assets/download/{asset_name:path}")
        async def download_asset(asset_name: str):
            file_path = self.asset_hub.get_asset_file_path(asset_name)
            if not file_path or not file_path.exists():
                return JSONResponse(
                    {"error": f"Asset '{asset_name}' not found in hub."}, status_code=404
                )
            return FileResponse(path=file_path, filename=file_path.name)

        @app.post("/api/assets/upload")
        async def upload_asset(
            name: str = Form(...),
            asset_type: str = Form("image"),
            worker_id: str = Form(""),
            file: UploadFile = File(...),
        ):
            try:
                content = await file.read()
                ext = Path(file.filename).suffix.lstrip(".") if file.filename else "png"
                try:
                    at = AssetType(asset_type)
                except ValueError:
                    at = AssetType.IMAGE
                meta = self.asset_hub.save_asset(
                    name=name, asset_type=at, file_bytes=content,
                    file_ext=ext, worker_id=worker_id,
                )
                if worker_id:
                    self.scheduler.add_worker_cached_asset(worker_id, name)
                return JSONResponse({"success": True, "asset": meta.model_dump()})
            except Exception as e:
                logger.error(f"Asset upload failed: {e}")
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/assets/info/{asset_name:path}")
        async def asset_info(asset_name: str):
            meta = self.asset_hub.get_asset(asset_name)
            if not meta:
                return JSONResponse({"exists": False}, status_code=404)
            return JSONResponse({"exists": True, "asset": meta.model_dump()})

        @app.get("/api/cluster/status")
        async def cluster_status():
            workers = [w.model_dump() for w in self.scheduler.get_workers()]
            for w in workers:
                if "cached_assets" in w and isinstance(w["cached_assets"], set):
                    w["cached_assets"] = list(w["cached_assets"])
            return JSONResponse({
                "worker_count": len(workers),
                "pending_tasks": len(self.scheduler.pending_tasks),
                "active_tasks": len(self.scheduler.active_tasks),
                "workers": workers,
            })

        @app.post("/api/account/update")
        async def account_update(
            email: str = Form(...),
            credits: int = Form(None),
            worker_id: str = Form(""),
        ):
            from google_flow_mcp.models.account_cache import AccountCache
            try:
                if email:
                    AccountCache.update(email=email, credits=credits, worker_id=worker_id)
                    if worker_id and worker_id in self.scheduler.workers:
                        w = self.scheduler.workers[worker_id]
                        w.account = email
                        acc_info = AccountCache.get_account_credits(email)
                        w.credits = acc_info.get("credits")
                        w.daily_free_remaining = acc_info.get("daily_free_remaining", 50)
                    logger.info(f"Master API: account updated (email={email}, credits={credits}, worker={worker_id})")
                return JSONResponse({"success": True})
            except Exception as e:
                logger.error(f"Account update API failed: {e}")
                return JSONResponse({"error": str(e)}, status_code=500)

        return app

    # ── Server Lifecycle ─────────────────────────────────────

    def start(self) -> None:
        """Start both gRPC and HTTP servers in background daemon threads."""
        # gRPC server thread
        self._grpc_thread = threading.Thread(
            target=self._run_grpc_server, daemon=True, name="ClusterGrpcServer"
        )
        self._grpc_thread.start()

        # HTTP server thread
        self._http_thread = threading.Thread(
            target=self._run_http_server, daemon=True, name="ClusterHttpServer"
        )
        self._http_thread.start()

        logger.info(
            f"Cluster Master started: gRPC on {self.host}:{self.grpc_port}, "
            f"HTTP on {self.host}:{self.http_port}"
        )

    def _run_grpc_server(self) -> None:
        """Run the async gRPC server in its own event loop."""
        async def serve():
            self._grpc_server = grpc_aio.server()
            cluster_pb2_grpc.add_ClusterServiceServicer_to_server(
                ClusterServiceServicer(self.scheduler), self._grpc_server
            )
            listen_addr = f"{self.host}:{self.grpc_port}"
            self._grpc_server.add_insecure_port(listen_addr)
            await self._grpc_server.start()
            logger.info(f"gRPC server listening on {listen_addr}")
            await self._grpc_server.wait_for_termination()

        try:
            asyncio.run(serve())
        except Exception as e:
            logger.error(f"Cluster gRPC Server failed to start: {e}")
            import os
            os._exit(1)

    def _run_http_server(self) -> None:
        """Run the FastAPI/uvicorn HTTP server."""
        try:
            config = uvicorn.Config(
                app=self._fastapi_app,
                host=self.host,
                port=self.http_port,
                log_level="warning",
                access_log=False,
            )
            server = uvicorn.Server(config)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(server.serve())
        except Exception as e:
            logger.error(f"Cluster HTTP Server failed to start: {e}")
            import os
            os._exit(1)

    def stop(self) -> None:
        """Gracefully stop both servers."""
        if self._grpc_server:
            # Schedule graceful shutdown from any thread
            try:
                loop = self._grpc_server._loop
                if loop and loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._grpc_server.stop(grace=2.0), loop
                    )
            except Exception:
                pass
        logger.info("Cluster Master Server stopping...")
