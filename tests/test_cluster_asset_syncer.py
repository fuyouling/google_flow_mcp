import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from google_flow_mcp.cluster.asset_syncer import AssetSyncer


def test_asset_syncer_ensure_assets_skips_cached():
    with tempfile.TemporaryDirectory() as tmp_dir:
        syncer = AssetSyncer(master_url="http://127.0.0.1:8765", cache_dir=Path(tmp_dir))
        mock_tab = MagicMock()
        cached = {"already_present_img"}

        # Should skip download/upload because it's in cached
        syncer.ensure_assets(mock_tab, "proj-1", ["already_present_img"], cached)
        assert "already_present_img" in cached
        mock_tab.ele.assert_not_called()


def test_asset_syncer_download_and_upload_flow():
    with tempfile.TemporaryDirectory() as tmp_dir:
        syncer = AssetSyncer(master_url="http://127.0.0.1:8765", cache_dir=Path(tmp_dir))
        mock_tab = MagicMock()
        cached = set()

        dummy_img = Path(tmp_dir) / "dummy.png"
        dummy_img.write_bytes(b"image-content")

        with patch.object(syncer, "download_asset", return_value=(dummy_img, "image")) as mock_dl:
            with patch.object(syncer, "upload_to_flow", return_value=True) as mock_up:
                syncer.ensure_assets(mock_tab, "proj-123", ["new_hero_img"], cached)

                mock_dl.assert_called_once_with("new_hero_img")
                mock_up.assert_called_once_with(mock_tab, "proj-123", "new_hero_img", dummy_img, "image")
                assert "new_hero_img" in cached


def test_asset_syncer_upload_result():
    with tempfile.TemporaryDirectory() as tmp_dir:
        syncer = AssetSyncer(master_url="http://127.0.0.1:8765", cache_dir=Path(tmp_dir))
        res_file = Path(tmp_dir) / "video_res.mp4"
        res_file.write_bytes(b"mp4-video-bytes")

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("requests.post", return_value=mock_resp) as mock_post:
            success = syncer.upload_result_asset(
                worker_id="w1",
                asset_name="video_res",
                file_path=res_file,
                asset_type="video",
            )
            assert success is True
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            assert "name" in kwargs["data"]
            assert kwargs["data"]["name"] == "video_res"
            assert kwargs["data"]["asset_type"] == "video"
