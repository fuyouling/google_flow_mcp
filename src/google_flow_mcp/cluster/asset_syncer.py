import tempfile
from pathlib import Path
from typing import List, Optional, Set, Tuple
from loguru import logger
import requests

from google_flow_mcp.pages.flow_character_page import FlowCharacterPage
from google_flow_mcp.pages.flow_image_page import FlowImagePage


class AssetSyncer:
    """
    Worker-side asset synchronizer.
    Responsible for:
    - JIT downloading missing reference assets from Master via HTTP
    - Injecting downloaded assets into the local Google Flow project
    - Uploading locally generated outputs (images/videos) back to Master
    """

    def __init__(self, master_url: str, cache_dir: Optional[Path] = None):
        self.master_url = master_url.rstrip("/")
        if cache_dir is None:
            self.cache_dir = Path(tempfile.gettempdir()) / "google_flow_mcp_cache"
        else:
            self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def download_asset(self, asset_name: str) -> Optional[Tuple[Path, str]]:
        """Download asset file from Master. Returns (file_path, asset_type)."""
        clean_name = asset_name.strip()
        info_url = f"{self.master_url}/api/assets/info/{clean_name}"
        asset_type = "image"

        try:
            r = requests.get(info_url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                if data.get("exists") and "asset" in data:
                    asset_type = data["asset"].get("asset_type", "image")
        except Exception as e:
            logger.warning(f"Failed to fetch asset info for '{clean_name}': {e}")

        download_url = f"{self.master_url}/api/assets/download/{clean_name}"
        dest_path = self.cache_dir / f"{clean_name}.png"

        try:
            logger.info(f"Downloading asset '{clean_name}' from Master ({download_url})...")
            with requests.get(download_url, stream=True, timeout=30) as r:
                if r.status_code != 200:
                    logger.error(f"Asset '{clean_name}' not found on Master (status: {r.status_code})")
                    return None
                with open(dest_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            logger.info(f"Asset '{clean_name}' downloaded successfully to {dest_path}")
            return dest_path, asset_type
        except Exception as e:
            logger.error(f"Error downloading asset '{clean_name}': {e}")
            return None

    def upload_to_flow(
        self, tab, project_id: str, asset_name: str, file_path: Path, asset_type: str
    ) -> bool:
        """Inject local file into worker's Google Flow project."""
        logger.info(f"JIT Uploading '{asset_name}' ({asset_type}) to local Flow project {project_id}...")
        try:
            if asset_type == "character":
                char_page = FlowCharacterPage(tab)
                char_page.navigate_to_characters(project_id)
                if not char_page.click_new_character():
                    raise Exception("Failed to open character editor in Flow")
                char_page.upload_portrait(str(file_path))
                char_page.rename_character(asset_name)
                char_page.save_character()
            else:
                img_page = FlowImagePage(tab)
                img_page.upload_image_on_project_page(project_id, str(file_path))
                img_page.rename_and_save_in_detail(asset_name)

            logger.info(f"JIT upload and save completed for asset: {asset_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to upload asset '{asset_name}' into Flow: {e}")
            return False

    def ensure_assets(
        self, tab, project_id: str, required_assets: List[str], cached_assets: Set[str]
    ) -> None:
        """
        Ensure all required assets exist in the local project before generating.
        Downloads missing assets from Master and uploads them to Flow.
        """
        for asset in required_assets:
            clean_name = asset.strip()
            if not clean_name:
                continue

            if clean_name in cached_assets:
                logger.info(f"Asset '{clean_name}' already verified in local project, skipping JIT.")
                continue

            res = self.download_asset(clean_name)
            if not res:
                logger.warning(
                    f"Asset '{clean_name}' could not be downloaded from Master. Skipping JIT upload."
                )
                continue

            file_path, asset_type = res
            success = self.upload_to_flow(tab, project_id, clean_name, file_path, asset_type)
            if success:
                cached_assets.add(clean_name)

    def upload_result_asset(
        self, worker_id: str, asset_name: str, file_path: Path, asset_type: str = "image"
    ) -> bool:
        """Upload a newly created asset (image/video) back to Master."""
        upload_url = f"{self.master_url}/api/assets/upload"
        if not file_path.exists():
            logger.error(f"Cannot upload non-existent result file: {file_path}")
            return False

        try:
            with open(file_path, "rb") as f:
                files = {"file": (file_path.name, f)}
                data = {
                    "name": asset_name,
                    "asset_type": asset_type,
                    "worker_id": worker_id,
                }
                r = requests.post(upload_url, data=data, files=files, timeout=60)
                if r.status_code == 200:
                    logger.info(f"Result asset '{asset_name}' uploaded back to Master successfully.")
                    return True
                else:
                    logger.error(f"Failed to upload result asset '{asset_name}': {r.status_code} {r.text}")
                    return False
        except Exception as e:
            logger.error(f"Exception uploading result asset '{asset_name}': {e}")
            return False
