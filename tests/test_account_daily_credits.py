import os
import json
import pytest
from datetime import datetime, timezone, timedelta
from google_flow_mcp.models import account_cache
from google_flow_mcp.models.account_cache import AccountCache


@pytest.fixture(autouse=True)
def temp_account_cache(tmp_path, monkeypatch):
    test_file = str(tmp_path / "test_account_cache.json")
    monkeypatch.setattr(account_cache, "ACCOUNT_CACHE_FILE", test_file)
    yield test_file
    if os.path.exists(test_file):
        try:
            os.remove(test_file)
        except Exception:
            pass


def test_get_current_cycle_date_utc_cutoff():
    # Before 05:00 UTC (e.g. 04:59:59 on 2026-09-21) -> belongs to 2026-09-20
    dt_before = datetime(2026, 9, 21, 4, 59, 59, tzinfo=timezone.utc)
    assert AccountCache.get_current_cycle_date(dt_before) == "2026-09-20"

    # Exactly at 05:00:00 UTC on 2026-09-21 -> belongs to 2026-09-21
    dt_at = datetime(2026, 9, 21, 5, 0, 0, tzinfo=timezone.utc)
    assert AccountCache.get_current_cycle_date(dt_at) == "2026-09-21"

    # After 05:00 UTC (e.g. 12:00:00 on 2026-09-21) -> belongs to 2026-09-21
    dt_after = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
    assert AccountCache.get_current_cycle_date(dt_after) == "2026-09-21"


def test_ensure_daily_grant_resets_on_new_cycle():
    email = "user@example.com"
    day1 = datetime(2026, 9, 21, 10, 0, 0, tzinfo=timezone.utc)
    AccountCache.update(email, credits=200, worker_id="w1")

    # Cycle 1: ensure daily grant gives 50
    entry1 = AccountCache.ensure_daily_grant(email, ref_time=day1)
    assert entry1["daily_free_credits_remaining"] == 50
    assert entry1["daily_cycle_date"] == "2026-09-21"

    # Deduct 20 credits on day 1
    free_ded, bal_ded = AccountCache.deduct_credits(email, cost=20, ref_time=day1)
    assert free_ded == 20
    assert bal_ded == 0
    assert AccountCache.get(email)["daily_free_credits_remaining"] == 30

    # Advance to Day 2 (2026-09-22 06:00 UTC, after 05:00 cutoff)
    day2 = datetime(2026, 9, 22, 6, 0, 0, tzinfo=timezone.utc)
    entry2 = AccountCache.ensure_daily_grant(email, ref_time=day2)
    assert entry2["daily_free_credits_remaining"] == 50
    assert entry2["daily_cycle_date"] == "2026-09-22"


def test_deduct_credits_combinations():
    email = "test_combo@example.com"
    now = datetime(2026, 9, 21, 10, 0, 0, tzinfo=timezone.utc)
    AccountCache.update(email, credits=100, worker_id="w1")
    AccountCache.ensure_daily_grant(email, ref_time=now)

    # 1. Deduct within daily free: cost=12 -> 50 free becomes 38, balance 100 unchanged
    f1, b1 = AccountCache.deduct_credits(email, cost=12, ref_time=now)
    assert f1 == 12
    assert b1 == 0
    acc = AccountCache.get(email)
    assert acc["daily_free_credits_remaining"] == 38
    assert acc["credits"] == 100

    # 2. Deduct partial combo: cost=50, while daily free is 38
    # -> free absorbs 38 (to 0), remaining 12 absorbed by balance (100 -> 88)
    f2, b2 = AccountCache.deduct_credits(email, cost=50, ref_time=now)
    assert f2 == 38
    assert b2 == 12
    acc = AccountCache.get(email)
    assert acc["daily_free_credits_remaining"] == 0
    assert acc["credits"] == 88

    # 3. Deduct pure balance: cost=20, daily free is 0 -> balance 88 -> 68
    f3, b3 = AccountCache.deduct_credits(email, cost=20, ref_time=now)
    assert f3 == 0
    assert b3 == 20
    acc = AccountCache.get(email)
    assert acc["daily_free_credits_remaining"] == 0
    assert acc["credits"] == 68


def test_refund_credits():
    email = "refund@example.com"
    now = datetime(2026, 9, 21, 10, 0, 0, tzinfo=timezone.utc)
    AccountCache.update(email, credits=100, worker_id="w1")
    AccountCache.ensure_daily_grant(email, ref_time=now)

    f, b = AccountCache.deduct_credits(email, cost=60, ref_time=now)
    assert f == 50
    assert b == 10
    acc = AccountCache.get(email)
    assert acc["daily_free_credits_remaining"] == 0
    assert acc["credits"] == 90

    # Refund
    AccountCache.refund_credits(email, daily_free=f, balance=b)
    acc_after = AccountCache.get(email)
    assert acc_after["daily_free_credits_remaining"] == 50
    assert acc_after["credits"] == 100
