import json
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from loguru import logger

ACCOUNT_CACHE_FILE = "account_cache.json"
DAILY_GRANT_AMOUNT = 50
UTC_RESET_HOUR = 5  # UTC 05:00 (13:00 Beijing time)


class AccountCache:
    """
    Manages persistent local storage for Google Flow account info (email, total credits,
    daily free credits, and cycle date).
    Data is stored in account_cache.json in the current working directory.

    JSON structure:
    {
      "accounts": {
        "user@example.com": {
          "email": "user@example.com",
          "credits": 556,
          "daily_free_credits_remaining": 50,
          "daily_cycle_date": "2026-09-21",
          "worker_id": "worker_1",
          "updated_at": "2026-09-21T12:00:00+00:00"
        }
      }
    }
    """

    @classmethod
    def get_current_cycle_date(cls, ref_time: Optional[datetime] = None) -> str:
        """
        Calculate current grant cycle date based on UTC 05:00 cutoff.
        If current UTC hour < 5, cycle date is yesterday's date.
        If current UTC hour >= 5, cycle date is today's date.
        """
        now = ref_time or datetime.now(timezone.utc)
        cycle_dt = now - timedelta(hours=UTC_RESET_HOUR)
        return cycle_dt.date().isoformat()

    @classmethod
    def load(cls) -> dict:
        if not os.path.exists(ACCOUNT_CACHE_FILE):
            return {"accounts": {}}
        try:
            with open(ACCOUNT_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load account cache: {e}")
            return {"accounts": {}}

    @classmethod
    def save(cls, data: dict) -> None:
        temp_file = f"{ACCOUNT_CACHE_FILE}.tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, ACCOUNT_CACHE_FILE)
        except Exception as e:
            logger.error(f"Failed to save account cache: {e}")
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

    @classmethod
    def ensure_daily_grant(cls, email: str, ref_time: Optional[datetime] = None) -> dict:
        """
        Check whether the account's grant cycle is up-to-date with current UTC 05:00 cutoff.
        If a new cycle has begun, grant DAILY_GRANT_AMOUNT (50) free credits and update cycle date.
        """
        if not email:
            return {}
        data = cls.load()
        existing = data.setdefault("accounts", {}).get(email, {})
        current_cycle = cls.get_current_cycle_date(ref_time)

        last_cycle = existing.get("daily_cycle_date")
        needs_save = False

        if last_cycle != current_cycle:
            existing["daily_free_credits_remaining"] = DAILY_GRANT_AMOUNT
            existing["daily_cycle_date"] = current_cycle
            existing["updated_at"] = datetime.now(timezone.utc).isoformat()
            needs_save = True
            logger.info(
                f"AccountCache: Granted daily {DAILY_GRANT_AMOUNT} credits to {email} "
                f"for cycle {current_cycle} (was {last_cycle})"
            )
        elif "daily_free_credits_remaining" not in existing:
            existing["daily_free_credits_remaining"] = DAILY_GRANT_AMOUNT
            existing["daily_cycle_date"] = current_cycle
            needs_save = True

        if needs_save:
            data["accounts"][email] = existing
            cls.save(data)

        return existing

    @classmethod
    def update(cls, email: str, credits: Optional[int], worker_id: str = "") -> None:
        """Update or create an account entry with the given email, credits, and worker_id."""
        if not email:
            return
        data = cls.load()
        existing = data.get("accounts", {}).get(email, {})
        new_credits = credits if credits is not None else existing.get("credits")
        new_worker_id = worker_id or existing.get("worker_id", "")

        current_cycle = cls.get_current_cycle_date()
        daily_free = existing.get("daily_free_credits_remaining", DAILY_GRANT_AMOUNT)
        daily_cycle = existing.get("daily_cycle_date", current_cycle)

        # If crossing cycle during update
        if daily_cycle != current_cycle:
            daily_free = DAILY_GRANT_AMOUNT
            daily_cycle = current_cycle

        data.setdefault("accounts", {})[email] = {
            **existing,
            "email": email,
            "credits": new_credits,
            "daily_free_credits_remaining": daily_free,
            "daily_cycle_date": daily_cycle,
            "worker_id": new_worker_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        cls.save(data)
        logger.info(
            f"AccountCache updated: email={email}, credits={new_credits}, "
            f"daily_free={daily_free}, cycle={daily_cycle}, worker={new_worker_id}"
        )

    @classmethod
    def deduct_credits(
        cls, email: str, cost: int, ref_time: Optional[datetime] = None
    ) -> Tuple[int, int]:
        """
        Deduct task credits from the account.
        Priority:
        1. Deduct from daily_free_credits_remaining first.
        2. Deduct remaining deficit from total credits (balance).
        Returns (deducted_daily_free, deducted_balance).
        """
        if not email or cost <= 0:
            return 0, 0

        data = cls.load()
        existing = data.setdefault("accounts", {}).get(email, {})
        current_cycle = cls.get_current_cycle_date(ref_time)

        # Check daily grant reset
        if existing.get("daily_cycle_date") != current_cycle:
            existing["daily_free_credits_remaining"] = DAILY_GRANT_AMOUNT
            existing["daily_cycle_date"] = current_cycle

        daily_free = existing.get("daily_free_credits_remaining", DAILY_GRANT_AMOUNT)
        balance = existing.get("credits") or 0

        deduct_free = min(daily_free, cost)
        remain_cost = cost - deduct_free
        deduct_bal = min(balance, remain_cost)

        existing["daily_free_credits_remaining"] = daily_free - deduct_free
        if existing.get("credits") is not None:
            existing["credits"] = max(0, balance - deduct_bal)
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()

        data["accounts"][email] = existing
        cls.save(data)

        logger.info(
            f"AccountCache: Deducted {cost} credits for {email} "
            f"(daily_free: -{deduct_free} => {existing['daily_free_credits_remaining']}, "
            f"balance: -{deduct_bal} => {existing.get('credits')})"
        )
        return deduct_free, deduct_bal

    @classmethod
    def refund_credits(cls, email: str, daily_free: int, balance: int) -> None:
        """
        Refund deducted credits if a task fails before actual generation starts.
        """
        if not email or (daily_free <= 0 and balance <= 0):
            return

        data = cls.load()
        existing = data.setdefault("accounts", {}).get(email)
        if not existing:
            return

        cur_free = existing.get("daily_free_credits_remaining", 0)
        cur_bal = existing.get("credits") or 0

        existing["daily_free_credits_remaining"] = cur_free + daily_free
        if existing.get("credits") is not None:
            existing["credits"] = cur_bal + balance
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()

        data["accounts"][email] = existing
        cls.save(data)

        logger.info(
            f"AccountCache: Refunded credits for {email} "
            f"(daily_free: +{daily_free} => {existing['daily_free_credits_remaining']}, "
            f"balance: +{balance} => {existing.get('credits')})"
        )

    @classmethod
    def get(cls, email: str) -> Optional[dict]:
        """Get account entry by email."""
        data = cls.load()
        return data.get("accounts", {}).get(email)

    @classmethod
    def get_account_credits(cls, email: str) -> dict:
        """Get sanitized account credits breakdown."""
        entry = cls.ensure_daily_grant(email)
        return {
            "email": email,
            "credits": entry.get("credits"),
            "daily_free_remaining": entry.get("daily_free_credits_remaining", DAILY_GRANT_AMOUNT),
            "daily_cycle_date": entry.get("daily_cycle_date", cls.get_current_cycle_date()),
            "worker_id": entry.get("worker_id", ""),
        }

    @classmethod
    def list_accounts(cls) -> List[dict]:
        """List all accounts with refreshed daily grant info."""
        data = cls.load()
        accounts = data.get("accounts", {})
        result = []
        for email in list(accounts.keys()):
            refreshed = cls.ensure_daily_grant(email)
            result.append({
                "email": email,
                "credits": refreshed.get("credits"),
                "daily_free_remaining": refreshed.get("daily_free_credits_remaining", DAILY_GRANT_AMOUNT),
                "daily_cycle_date": refreshed.get("daily_cycle_date", cls.get_current_cycle_date()),
                "worker_id": refreshed.get("worker_id", ""),
                "updated_at": refreshed.get("updated_at", ""),
            })
        return result

    @classmethod
    def get_latest_credits(cls) -> Optional[int]:
        """
        Return credits from the most recently updated account entry.
        Useful as a fallback when credits cannot be freshly fetched.
        """
        data = cls.load()
        accounts = data.get("accounts", {})
        if not accounts:
            return None
        try:
            valid_accounts = [a for a in accounts.values() if a.get("credits") is not None]
            target_list = valid_accounts if valid_accounts else list(accounts.values())
            latest = max(
                target_list,
                key=lambda a: a.get("updated_at", ""),
            )
            return latest.get("credits")
        except Exception:
            return None
