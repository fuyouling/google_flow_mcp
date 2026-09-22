import json
import os
import re
from unittest.mock import MagicMock, patch
import pytest

from google_flow_mcp.models.account_cache import AccountCache
from google_flow_mcp.pages.flow_home_page import FlowHomePage
from google_flow_mcp.tools.website_open import _fetch_and_cache_credits


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



# ── AccountCache Tests ──────────────────────────────────────────


def test_account_cache_update_preserves_existing_fields(clean_cache_db):
    # 1. 首次创建：包含 worker_id 和 credits
    AccountCache.update(email="user@example.com", credits=100, worker_id="worker_42")
    entry = AccountCache.get("user@example.com")
    assert entry is not None
    assert entry["credits"] == 100
    assert entry["worker_id"] == "worker_42"

    # 2. 第二次更新：未传 worker_id (留空)，应保留历史 worker_id
    AccountCache.update(email="user@example.com", credits=90, worker_id="")
    entry2 = AccountCache.get("user@example.com")
    assert entry2["credits"] == 90
    assert entry2["worker_id"] == "worker_42"

    # 3. 第三次更新：credits 传 None，应保留历史 credits
    AccountCache.update(email="user@example.com", credits=None, worker_id="worker_new")
    entry3 = AccountCache.get("user@example.com")
    assert entry3["credits"] == 90
    assert entry3["worker_id"] == "worker_new"


def test_account_cache_get_latest_credits(clean_cache_db):
    assert AccountCache.get_latest_credits() is None

    AccountCache.update(email="user1@example.com", credits=50)
    AccountCache.update(email="user2@example.com", credits=200)

    # user2 最近更新
    assert AccountCache.get_latest_credits() == 200

    # 如果 user3 更新为 credits=None，get_latest_credits 仍应取有数值的条目
    AccountCache.update(email="user3@example.com", credits=None)
    assert AccountCache.get_latest_credits() in (50, 200)


# ── FlowHomePage.get_credits Tests ──────────────────────────────

def test_flow_home_page_get_credits_comma_number():
    mock_tab = MagicMock()
    mock_btn = MagicMock()
    mock_credits_ele = MagicMock()
    mock_close_btn = MagicMock()

    mock_tab.ele.side_effect = lambda sel, timeout=None: (
        mock_btn if "aria-label=\"账号详情\"" in sel else
        mock_credits_ele if "credits-count" in sel else
        mock_close_btn if "aria-label=\"关闭账号面板\"" in sel else None
    )

    # 测试千分位逗号数字提取
    mock_credits_ele.text = "1,250 个 Google Flow 点数"

    page = FlowHomePage(mock_tab)
    credits = page.get_credits()

    assert credits == 1250
    mock_btn.click.assert_called_once()
    mock_close_btn.click.assert_called_once()


def test_flow_home_page_get_credits_zero_credits():
    mock_tab = MagicMock()
    mock_btn = MagicMock()
    mock_credits_ele = MagicMock()
    mock_close_btn = MagicMock()

    mock_tab.ele.side_effect = lambda sel, timeout=None: (
        mock_btn if "aria-label=\"账号详情\"" in sel else
        mock_credits_ele if "credits-count" in sel else
        mock_close_btn if "aria-label=\"关闭账号面板\"" in sel else None
    )

    mock_credits_ele.text = "0 个 Google Flow 点数"

    page = FlowHomePage(mock_tab)
    credits = page.get_credits()

    assert credits == 0


def test_flow_home_page_get_credits_button_not_found_no_close_attempt():
    mock_tab = MagicMock()
    # 账号按钮不存在
    mock_tab.ele.return_value = None

    page = FlowHomePage(mock_tab)
    credits = page.get_credits()

    assert credits is None
    # 仅调用了一次查找账号按钮，由于 panel_opened=False，不应再去查找关闭按钮
    assert mock_tab.ele.call_count == 1
    assert "aria-label=\"账号详情\"" in mock_tab.ele.call_args[0][0]


# ── website_open._fetch_and_cache_credits Tests ─────────────────

def test_fetch_and_cache_credits_homepage_success(clean_cache_db):
    mock_tab = MagicMock()
    with patch("google_flow_mcp.pages.flow_home_page.FlowHomePage.get_credits", return_value=888):
        credits = _fetch_and_cache_credits(
            tab=mock_tab,
            account_email="alice@example.com",
            is_homepage=True,
        )

    assert credits == 888
    cached = AccountCache.get("alice@example.com")
    assert cached is not None
    assert cached["credits"] == 888


def test_fetch_and_cache_credits_non_homepage_matches_account(clean_cache_db):
    # 预设两个账号缓存
    AccountCache.update("alice@example.com", credits=300)
    AccountCache.update("bob@example.com", credits=999)

    mock_tab = MagicMock()
    # 非首页，已知账号是 alice，应优先返回 alice 的 300，而不是 bob 的 999
    credits = _fetch_and_cache_credits(
        tab=mock_tab,
        account_email="alice@example.com",
        is_homepage=False,
    )

    assert credits == 300


def test_fetch_and_cache_credits_fallback_when_email_missing(clean_cache_db):
    mock_tab = MagicMock()
    with patch("google_flow_mcp.pages.flow_home_page.FlowHomePage.get_credits", return_value=666):
        credits = _fetch_and_cache_credits(
            tab=mock_tab,
            account_email=None,
            is_homepage=True,
        )

    assert credits == 666
    # 验证点数没有被直接丢弃，而是降级存入
    latest = AccountCache.get_latest_credits()
    assert latest == 666


# ── website_open top-level and start_browser integration tests ──

def test_website_open_top_level_callable():
    """验证 website_open 可以从模块顶层直接调用并返回预期的 JSON 数据"""
    from google_flow_mcp.tools.website_open import website_open

    mock_browser = MagicMock()
    mock_tab = MagicMock()
    mock_tab.url = "https://flow.google.com"
    mock_tab.title = "Google Flow"
    mock_browser.latest_tab = mock_tab

    with patch("google_flow_mcp.tools.website_open.get_browser", return_value=mock_browser), \
         patch("google_flow_mcp.utils.project_utils.ensure_project_exists", return_value="TestProject"), \
         patch("google_flow_mcp.pages.base_page.BasePage.navigate"), \
         patch("google_flow_mcp.tools.website_open._fetch_and_cache_credits", return_value=123):
        res_raw = website_open(url="https://flow.google.com")
        res = json.loads(res_raw)
        assert res["success"] is True
        assert res["data"]["credits"] == 123
        assert res["data"]["url"] == "https://flow.google.com"


def test_launch_browser_calls_website_open_for_initialization():
    """验证 start_browser.launch_browser 在打开浏览器后不直接访问网页，而是调用 website_open 完成初始化"""
    from google_flow_mcp.browser.start_browser import launch_browser
    from google_flow_mcp.browser.session import get_browser

    mock_browser = MagicMock()
    mock_tab = MagicMock()
    mock_browser.latest_tab = mock_tab

    dummy_response = json.dumps({
        "success": True,
        "data": {
            "title": "Google Flow",
            "url": "https://flow.google.com",
            "is_logged_in": True,
            "account_email": "testuser@gmail.com",
            "credits": 500,
            "message": "Website opened successfully",
        }
    })

    with patch("google_flow_mcp.browser.start_browser.get_cdp_version", return_value=None), \
         patch("google_flow_mcp.browser.start_browser.is_port_in_use", return_value=False), \
         patch("google_flow_mcp.browser.start_browser.Chromium", return_value=mock_browser), \
         patch("google_flow_mcp.browser.start_browser.website_open", return_value=dummy_response) as mock_website_open:
        
        # 运行 detach 模式以避免进入交互循环
        launch_browser(target_url="https://flow.google.com", detach=True)

        # 验证未在 start_browser 中直接调用 mock_tab.get
        mock_tab.get.assert_not_called()

        # 验证调用了 website_open 完成初始化
        mock_website_open.assert_called_once_with(url="https://flow.google.com")

        # 验证 browser session 已经注册为当前 browser 实例
        assert get_browser() is mock_browser

