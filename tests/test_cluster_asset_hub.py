import tempfile
from pathlib import Path
import pytest
from google_flow_mcp.cluster.asset_hub import AssetHub
from google_flow_mcp.cluster.models import AssetType


def test_asset_hub_save_and_retrieve():
    with tempfile.TemporaryDirectory() as tmp_dir:
        hub = AssetHub(base_dir=Path(tmp_dir))

        # Save dummy image bytes
        dummy_content = b"fake-png-binary-data"
        meta = hub.save_asset(
            name="scene01_garden",
            asset_type=AssetType.IMAGE,
            file_bytes=dummy_content,
            file_ext="png",
            worker_id="worker_1",
        )

        assert meta.name == "scene01_garden"
        assert meta.asset_type == AssetType.IMAGE
        assert meta.file_size == len(dummy_content)
        assert meta.sha256 != ""

        # Retrieve
        fetched = hub.get_asset("scene01_garden")
        assert fetched is not None
        assert fetched.sha256 == meta.sha256

        # Check file exists
        p = hub.get_asset_file_path("scene01_garden")
        assert p is not None
        assert p.exists()
        assert p.read_bytes() == dummy_content

        assert hub.has_asset("scene01_garden") is True
        assert hub.has_asset("non_existent") is False


def test_asset_hub_save_file_and_delete():
    with tempfile.TemporaryDirectory() as tmp_dir:
        hub = AssetHub(base_dir=Path(tmp_dir))

        # Create a source file
        src_file = Path(tmp_dir) / "source_char.png"
        src_file.write_bytes(b"portrait-bytes-here")

        meta = hub.save_asset_file(
            name="Alice",
            asset_type=AssetType.CHARACTER,
            src_file_path=src_file,
            worker_id="worker_2",
        )
        assert meta.name == "Alice"
        assert meta.asset_type == AssetType.CHARACTER
        assert hub.has_asset("Alice") is True

        # List
        chars = hub.list_assets(AssetType.CHARACTER)
        assert len(chars) == 1
        assert chars[0].name == "Alice"

        # Delete
        success = hub.delete_asset("Alice")
        assert success is True
        assert hub.has_asset("Alice") is False
