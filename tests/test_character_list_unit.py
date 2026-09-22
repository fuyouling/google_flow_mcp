import json
import pytest
from unittest.mock import MagicMock, patch
from google_flow_mcp.models.project_cache import ProjectCache
from google_flow_mcp.tasks.manager import TaskManager


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



def test_project_cache_characters(tmp_path, monkeypatch):
    test_cache_file = str(tmp_path / "test_projects_cache.json")

    ProjectCache.update_project("proj-123", "https://flow.google.com/project/proj-123")
    
    chars = [
        {"index": 1, "name": "角色Alpha", "thumbnail_url": "https://example.com/a.png"},
        {"index": 2, "name": "角色Beta", "thumbnail_url": "https://example.com/b.png"}
    ]
    ProjectCache.update_project_characters("proj-123", chars)

    cached_chars = ProjectCache.get_project_characters("proj-123")
    assert cached_chars == chars

    # Verify existing project fields preserved
    proj = ProjectCache.get_project_by_name("proj-123")
    assert proj["name"] == "proj-123"
    assert proj["characters"] == chars


def test_character_list_when_browser_busy(tmp_path, monkeypatch):
    test_cache_file = str(tmp_path / "test_projects_cache.json")

    chars = [{"index": 1, "name": "已缓存角色", "thumbnail_url": ""}]
    ProjectCache.update_project("Busy Project", "https://flow.google.com/project/proj-busy")
    ProjectCache.update_project_characters("proj-busy", chars)

    from google_flow_mcp.tools.character_list import register_character_list_tool
    mock_mcp = MagicMock()
    tool_func = None

    def capture_tool():
        def decorator(fn):
            nonlocal tool_func
            tool_func = fn
            return fn
        return decorator

    mock_mcp.tool = capture_tool
    register_character_list_tool(mock_mcp)
    assert tool_func is not None

    # Mock task_manager.is_browser_busy to True
    with patch("google_flow_mcp.tools.character_list.task_manager.is_browser_busy") as mock_busy:
        mock_busy.return_value = (True, {"job_id": "job-999", "task_type": "图片生成"})
        res_raw = tool_func(project_name="proj-busy")
        data = json.loads(res_raw)
        assert data["success"] is True
        assert data["is_cached"] is True
        assert "降级返回本地历史缓存数据" in data["warning"]
        assert data["total"] == 1
        assert data["characters"][0]["name"] == "已缓存角色"


def test_character_list_success(monkeypatch):
    from google_flow_mcp.tools.character_list import register_character_list_tool
    mock_mcp = MagicMock()
    tool_func = None

    def capture_tool():
        def decorator(fn):
            nonlocal tool_func
            tool_func = fn
            return fn
        return decorator

    mock_mcp.tool = capture_tool
    register_character_list_tool(mock_mcp)

    with patch("google_flow_mcp.tools.character_list.task_manager.is_browser_busy", return_value=(False, None)), \
         patch("google_flow_mcp.tools.character_list.get_browser") as mock_browser, \
         patch("google_flow_mcp.tools.character_list.FlowCharacterPage") as mock_page_cls, \
         patch("google_flow_mcp.tools.character_list.ProjectCache.update_project_characters") as mock_cache_update:

        mock_tab = MagicMock()
        mock_tab.url = "https://flow.google.com/project/proj-auto"
        ProjectCache.update_project("proj-auto", "https://flow.google.com/project/proj-auto")
        mock_browser.return_value.latest_tab = mock_tab

        mock_page = MagicMock()
        mock_page.list_characters.return_value = [
            {"index": 1, "name": "主角小明", "thumbnail_url": "https://flow-content.google/image/1.png"}
        ]
        mock_page_cls.return_value = mock_page

        # Call with empty project_name -> auto infer from tab.url
        res_raw = tool_func(project_name="")
        data = json.loads(res_raw)

        assert data["success"] is True
        assert data["project_name"] == "proj-auto"
        assert data["total"] == 1
        assert data["characters"][0]["name"] == "主角小明"
        mock_cache_update.assert_called_once_with(
            "proj-auto",
            [{"index": 1, "name": "主角小明", "thumbnail_url": "https://flow-content.google/image/1.png"}]
        )
