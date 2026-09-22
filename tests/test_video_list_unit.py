import json
import pytest
from unittest.mock import MagicMock, patch
from google_flow_mcp.models.project_cache import ProjectCache


from google_flow_mcp.models.db import init_db

@pytest.fixture(autouse=True)
def clean_cache_db(tmp_path, monkeypatch):
    db_path = tmp_path / "flow_cache.db"
    monkeypatch.setenv("FLOW_CACHE_DB", str(db_path))
    monkeypatch.setattr("google_flow_mcp.models.db.DB_FILE", str(db_path))
    init_db()
    yield db_path
    if db_path.exists():
        try:
            db_path.unlink()
        except:
            pass



def test_project_cache_videos(tmp_path, monkeypatch):
    test_cache_file = str(tmp_path / "test_projects_cache.json")

    ProjectCache.update_project("proj-vid-1", "https://flow.google.com/project/proj-vid-1")
    
    videos = [
        {"index": 1, "name": "镜头A_特写", "thumbnail_url": "https://example.com/v1.png"},
        {"index": 2, "name": "镜头B_全景", "thumbnail_url": "https://example.com/v2.mp4"}
    ]
    ProjectCache.update_project_videos("proj-vid-1", videos)

    cached_videos = ProjectCache.get_project_videos("proj-vid-1")
    assert cached_videos == videos

    proj = ProjectCache.get_project_by_name("proj-vid-1")
    assert proj["name"] == "proj-vid-1"
    assert proj["videos"] == videos


def test_video_list_when_browser_busy(tmp_path, monkeypatch):
    test_cache_file = str(tmp_path / "test_projects_cache.json")

    videos = [{"index": 1, "name": "已缓存视频", "thumbnail_url": "https://example.com/cached.mp4"}]
    ProjectCache.update_project("Busy Vid Project", "https://flow.google.com/project/proj-busy-vid")
    ProjectCache.update_project_videos("proj-busy-vid", videos)

    from google_flow_mcp.tools.video_list import register_video_list_tool
    mock_mcp = MagicMock()
    tool_func = None

    def capture_tool():
        def decorator(fn):
            nonlocal tool_func
            tool_func = fn
            return fn
        return decorator

    mock_mcp.tool = capture_tool
    register_video_list_tool(mock_mcp)
    assert tool_func is not None

    with patch("google_flow_mcp.tools.video_list.task_manager.is_browser_busy") as mock_busy:
        mock_busy.return_value = (True, {"job_id": "job-vid-999", "task_type": "图片生成"})
        res_raw = tool_func(project_name="proj-busy-vid")
        data = json.loads(res_raw)
        assert data["success"] is True
        assert data["is_cached"] is True
        assert "降级返回本地历史缓存数据" in data["warning"]
        assert data["total"] == 1
        assert data["videos"][0]["name"] == "已缓存视频"


def test_video_list_no_videos_button(tmp_path, monkeypatch):
    test_cache_file = str(tmp_path / "test_projects_cache.json")

    from google_flow_mcp.tools.video_list import register_video_list_tool
    mock_mcp = MagicMock()
    tool_func = None

    def capture_tool():
        def decorator(fn):
            nonlocal tool_func
            tool_func = fn
            return fn
        return decorator

    mock_mcp.tool = capture_tool
    register_video_list_tool(mock_mcp)

    with patch("google_flow_mcp.tools.video_list.task_manager.is_browser_busy", return_value=(False, None)), \
         patch("google_flow_mcp.tools.video_list.get_browser") as mock_browser:

        mock_tab = MagicMock()
        mock_tab.url = "https://flow.google.com/project/proj-empty-vid"
        mock_tab.ele.return_value = None  # No '视频' button and no tiles
        mock_tab.eles.return_value = []
        mock_browser.latest_tab = mock_tab

        res_raw = tool_func(project_name="proj-empty-vid")
        data = json.loads(res_raw)

        assert data["success"] is True
        assert data["total"] == 0
        assert data["videos"] == []


def test_video_list_success_with_tiles(monkeypatch):
    from google_flow_mcp.tools.video_list import register_video_list_tool
    mock_mcp = MagicMock()
    tool_func = None

    def capture_tool():
        def decorator(fn):
            nonlocal tool_func
            tool_func = fn
            return fn
        return decorator

    mock_mcp.tool = capture_tool
    register_video_list_tool(mock_mcp)

    with patch("google_flow_mcp.tools.video_list.task_manager.is_browser_busy", return_value=(False, None)), \
         patch("google_flow_mcp.tools.video_list.get_browser") as mock_browser, \
         patch("google_flow_mcp.tools.video_list.ProjectCache.update_project_videos") as mock_cache_update:

        mock_tab = MagicMock()
        mock_tab.url = "https://flow.google.com/project/proj-vid-tiles"
        
        # video_btn found
        mock_btn = MagicMock()
        mock_tab.ele.side_effect = lambda loc, timeout=0: mock_btn if "视频" in loc else None
        
        tile1 = MagicMock()
        name_ele1 = MagicMock()
        name_ele1.text = "森林日出延时摄影"
        img_ele1 = MagicMock()
        img_ele1.attr.side_effect = lambda attr: "https://flow-content.google/video/thumb1.png" if attr == "src" else ""
        link_ele1 = MagicMock()
        link_ele1.attr.side_effect = lambda attr: "/project/proj-vid-tiles/edit/vid-1" if attr == "href" else ""

        def tile1_ele(loc, timeout=0):
            if "hover-footer" in loc or "span" in loc:
                return name_ele1
            if "img" in loc:
                return img_ele1
            if "a" in loc:
                return link_ele1
            return None

        tile1.ele = tile1_ele

        mock_tab.eles.return_value = [tile1]
        mock_browser.return_value.latest_tab = mock_tab

        res_raw = tool_func(project_name="proj-vid-tiles")
        data = json.loads(res_raw)

        assert data["success"] is True
        assert data["total"] == 1
        assert data["videos"][0]["name"] == "森林日出延时摄影"
        assert data["videos"][0]["thumbnail_url"] == "https://flow-content.google/video/thumb1.png"
        assert data["videos"][0]["href"] == "/project/proj-vid-tiles/edit/vid-1"
        mock_cache_update.assert_called_once()
