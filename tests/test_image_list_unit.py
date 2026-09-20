import json
import pytest
from unittest.mock import MagicMock, patch
from google_flow_mcp.models.project_cache import ProjectCache


def test_project_cache_images(tmp_path, monkeypatch):
    test_cache_file = str(tmp_path / "test_projects_cache.json")
    monkeypatch.setattr("google_flow_mcp.models.project_cache.CACHE_FILE", test_cache_file)

    ProjectCache.update_project("proj-img-1", "Image Project", "https://flow.google.com/project/proj-img-1")
    
    images = [
        {"index": 1, "name": "风景照 01", "thumbnail_url": "https://example.com/img1.png"},
        {"index": 2, "name": "赛博朋克城市", "thumbnail_url": "https://example.com/img2.png"}
    ]
    ProjectCache.update_project_images("proj-img-1", images)

    cached_images = ProjectCache.get_project_images("proj-img-1")
    assert cached_images == images

    proj = ProjectCache.get_project_by_id("proj-img-1")
    assert proj["name"] == "Image Project"
    assert proj["images"] == images


def test_image_list_when_browser_busy(tmp_path, monkeypatch):
    test_cache_file = str(tmp_path / "test_projects_cache.json")
    monkeypatch.setattr("google_flow_mcp.models.project_cache.CACHE_FILE", test_cache_file)

    images = [{"index": 1, "name": "已缓存图片", "thumbnail_url": "https://example.com/cached.png"}]
    ProjectCache.update_project("proj-busy-img", "Busy Img Project", "https://flow.google.com/project/proj-busy-img")
    ProjectCache.update_project_images("proj-busy-img", images)

    from google_flow_mcp.tools.image_list import register_image_list_tool
    mock_mcp = MagicMock()
    tool_func = None

    def capture_tool():
        def decorator(fn):
            nonlocal tool_func
            tool_func = fn
            return fn
        return decorator

    mock_mcp.tool = capture_tool
    register_image_list_tool(mock_mcp)
    assert tool_func is not None

    with patch("google_flow_mcp.tools.image_list.task_manager.is_browser_busy") as mock_busy:
        mock_busy.return_value = (True, {"job_id": "job-img-999", "task_type": "视频生成"})
        res_raw = tool_func(project_id="proj-busy-img")
        data = json.loads(res_raw)
        assert data["success"] is True
        assert data["is_cached"] is True
        assert "降级返回本地历史缓存数据" in data["warning"]
        assert data["total"] == 1
        assert data["images"][0]["name"] == "已缓存图片"


def test_image_list_no_images_button(monkeypatch):
    from google_flow_mcp.tools.image_list import register_image_list_tool
    mock_mcp = MagicMock()
    tool_func = None

    def capture_tool():
        def decorator(fn):
            nonlocal tool_func
            tool_func = fn
            return fn
        return decorator

    mock_mcp.tool = capture_tool
    register_image_list_tool(mock_mcp)

    with patch("google_flow_mcp.tools.image_list.task_manager.is_browser_busy", return_value=(False, None)), \
         patch("google_flow_mcp.tools.image_list.get_browser") as mock_browser:

        mock_tab = MagicMock()
        mock_tab.url = "https://flow.google.com/project/proj-empty"
        mock_tab.ele.return_value = None  # No '图片' button and no tiles
        mock_tab.eles.return_value = []
        mock_browser.return_value.latest_tab = mock_tab

        res_raw = tool_func(project_id="proj-empty")
        data = json.loads(res_raw)

        assert data["success"] is True
        assert data["total"] == 0
        assert data["images"] == []


def test_image_list_success_with_tiles(monkeypatch):
    from google_flow_mcp.tools.image_list import register_image_list_tool
    mock_mcp = MagicMock()
    tool_func = None

    def capture_tool():
        def decorator(fn):
            nonlocal tool_func
            tool_func = fn
            return fn
        return decorator

    mock_mcp.tool = capture_tool
    register_image_list_tool(mock_mcp)

    with patch("google_flow_mcp.tools.image_list.task_manager.is_browser_busy", return_value=(False, None)), \
         patch("google_flow_mcp.tools.image_list.get_browser") as mock_browser, \
         patch("google_flow_mcp.tools.image_list.ProjectCache.update_project_images") as mock_cache_update:

        mock_tab = MagicMock()
        mock_tab.url = "https://flow.google.com/project/proj-tiles"
        
        # img_btn found
        mock_btn = MagicMock()
        mock_tab.ele.side_effect = lambda loc, timeout=0: mock_btn if "图片" in loc else None
        
        tile1 = MagicMock()
        name_ele1 = MagicMock()
        name_ele1.text = "月球基地外景"
        img_ele1 = MagicMock()
        img_ele1.attr.side_effect = lambda attr: "https://flow-content.google/image/m1.png" if attr == "src" else ""
        link_ele1 = MagicMock()
        link_ele1.attr.side_effect = lambda attr: "/project/proj-tiles/edit/media-1" if attr == "href" else ""

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

        res_raw = tool_func(project_id="proj-tiles")
        data = json.loads(res_raw)

        assert data["success"] is True
        assert data["total"] == 1
        assert data["images"][0]["name"] == "月球基地外景"
        assert data["images"][0]["thumbnail_url"] == "https://flow-content.google/image/m1.png"
        assert data["images"][0]["href"] == "/project/proj-tiles/edit/media-1"
        mock_cache_update.assert_called_once()
