import hashlib
import json
import threading
from pathlib import Path
from typing import Dict, List, Optional
from loguru import logger

from google_flow_mcp.cluster.models import AssetMetadata, AssetType


class AssetHub:
    """
    Centralized Asset Hub on the Master node.
    Stores asset files (images, characters, videos) and maintains a thread-safe registry.
    """

    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            # Default to data/assets inside project root
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            base_dir = project_root / "data" / "assets"
        self.base_dir = Path(base_dir).resolve()
        self.registry_file = self.base_dir / "assets_registry.json"
        self._lock = threading.RLock()
        self._registry: Dict[str, AssetMetadata] = {}

        self._ensure_dirs()
        self._load_registry()

    def _ensure_dirs(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "images").mkdir(exist_ok=True)
        (self.base_dir / "characters").mkdir(exist_ok=True)
        (self.base_dir / "videos").mkdir(exist_ok=True)

    def _load_registry(self) -> None:
        with self._lock:
            if not self.registry_file.exists():
                self._registry = {}
                return
            try:
                with open(self.registry_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._registry = {
                        k: AssetMetadata(**v) for k, v in data.items()
                    }
            except Exception as e:
                logger.error(f"Failed to load assets registry: {e}")
                self._registry = {}

    def _save_registry(self) -> None:
        with self._lock:
            try:
                data = {k: v.model_dump() for k, v in self._registry.items()}
                temp_file = self.registry_file.with_suffix(".tmp")
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                temp_file.replace(self.registry_file)
            except Exception as e:
                logger.error(f"Failed to save assets registry: {e}")

    def save_asset(
        self,
        name: str,
        asset_type: AssetType,
        file_bytes: bytes,
        file_ext: str = "png",
        worker_id: str = "",
    ) -> AssetMetadata:
        """Save raw bytes as an asset in the central hub."""
        with self._lock:
            ext = file_ext.lstrip(".")
            subdir = f"{asset_type.value}s"
            clean_name = name.strip()
            target_filename = f"{clean_name}.{ext}"
            target_path = self.base_dir / subdir / target_filename

            # Calculate SHA256
            sha256 = hashlib.sha256(file_bytes).hexdigest()

            with open(target_path, "wb") as f:
                f.write(file_bytes)

            meta = AssetMetadata(
                name=clean_name,
                asset_type=asset_type,
                file_name=target_filename,
                file_path=str(target_path),
                file_size=len(file_bytes),
                sha256=sha256,
                created_by_worker=worker_id,
            )
            self._registry[clean_name] = meta
            self._save_registry()
            logger.info(f"Asset '{clean_name}' saved to hub at {target_path}")
            return meta

    def save_asset_file(
        self,
        name: str,
        asset_type: AssetType,
        src_file_path: Path,
        worker_id: str = "",
    ) -> AssetMetadata:
        """Copy a local file into the central asset hub."""
        with self._lock:
            src = Path(src_file_path)
            if not src.exists():
                raise FileNotFoundError(f"Source asset file not found: {src}")

            with open(src, "rb") as f:
                content = f.read()

            ext = src.suffix.lstrip(".") or "png"
            return self.save_asset(
                name=name,
                asset_type=asset_type,
                file_bytes=content,
                file_ext=ext,
                worker_id=worker_id,
            )

    def get_asset(self, name: str) -> Optional[AssetMetadata]:
        with self._lock:
            return self._registry.get(name.strip())

    def get_asset_file_path(self, name: str) -> Optional[Path]:
        with self._lock:
            meta = self._registry.get(name.strip())
            if meta and meta.file_path:
                p = Path(meta.file_path)
                if p.exists():
                    return p
            return None

    def has_asset(self, name: str) -> bool:
        with self._lock:
            path = self.get_asset_file_path(name)
            return path is not None and path.exists()

    def list_assets(self, asset_type: Optional[AssetType] = None) -> List[AssetMetadata]:
        with self._lock:
            if asset_type:
                return [m for m in self._registry.values() if m.asset_type == asset_type]
            return list(self._registry.values())

    def delete_asset(self, name: str) -> bool:
        with self._lock:
            clean_name = name.strip()
            meta = self._registry.get(clean_name)
            if not meta:
                return False
            try:
                p = Path(meta.file_path)
                if p.exists():
                    p.unlink()
                del self._registry[clean_name]
                self._save_registry()
                logger.info(f"Asset '{clean_name}' deleted from hub.")
                return True
            except Exception as e:
                logger.error(f"Failed to delete asset '{clean_name}': {e}")
                return False
