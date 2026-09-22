import os
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple
from loguru import logger
from google_flow_mcp.models.db import get_connection

DAILY_GRANT_AMOUNT = 50
UTC_RESET_HOUR = 5  # UTC 05:00 (13:00 Beijing time)


class AccountCache:
    """
    Manages persistent local storage for Google Flow account info (email, total credits,
    daily free credits, and cycle date) using SQLite.
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
    def ensure_daily_grant(cls, email: str, ref_time: Optional[datetime] = None) -> dict:
        """
        Check whether the account's grant cycle is up-to-date with current UTC 05:00 cutoff.
        If a new cycle has begun, grant DAILY_GRANT_AMOUNT (50) free credits and update cycle date.
        """
        if not email:
            return {}
            
        current_cycle = cls.get_current_cycle_date(ref_time)
        
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM accounts WHERE email = ?", (email,))
            row = cursor.fetchone()
            
            if row:
                existing = dict(row)
                last_cycle = existing.get("daily_cycle_date")
                
                if last_cycle != current_cycle:
                    existing["daily_free_credits_remaining"] = DAILY_GRANT_AMOUNT
                    existing["daily_cycle_date"] = current_cycle
                    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
                    
                    cursor.execute("""
                        UPDATE accounts 
                        SET daily_free_credits_remaining = ?, daily_cycle_date = ?, updated_at = ?
                        WHERE email = ?
                    """, (DAILY_GRANT_AMOUNT, current_cycle, existing["updated_at"], email))
                    conn.commit()
                    
                    logger.info(
                        f"AccountCache: Granted daily {DAILY_GRANT_AMOUNT} credits to {email} "
                        f"for cycle {current_cycle} (was {last_cycle})"
                    )
                return existing
            else:
                return {}

    @classmethod
    def update(cls, email: str, credits: Optional[int], worker_id: str = "") -> None:
        """Update or create an account entry with the given email, credits, and worker_id."""
        if not email:
            return
            
        current_cycle = cls.get_current_cycle_date()
        updated_at = datetime.now(timezone.utc).isoformat()
        
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM accounts WHERE email = ?", (email,))
            row = cursor.fetchone()
            
            if row:
                existing = dict(row)
                new_credits = credits if credits is not None else existing.get("credits")
                new_worker_id = worker_id or existing.get("worker_id", "")
                
                daily_free = existing.get("daily_free_credits_remaining", DAILY_GRANT_AMOUNT)
                daily_cycle = existing.get("daily_cycle_date", current_cycle)

                # If crossing cycle during update
                if daily_cycle != current_cycle:
                    daily_free = DAILY_GRANT_AMOUNT
                    daily_cycle = current_cycle
                    
                cursor.execute("""
                    UPDATE accounts
                    SET credits = ?, daily_free_credits_remaining = ?, daily_cycle_date = ?, worker_id = ?, updated_at = ?
                    WHERE email = ?
                """, (new_credits, daily_free, daily_cycle, new_worker_id, updated_at, email))
            else:
                new_credits = credits
                new_worker_id = worker_id
                daily_free = DAILY_GRANT_AMOUNT
                daily_cycle = current_cycle
                
                cursor.execute("""
                    INSERT INTO accounts (email, credits, daily_free_credits_remaining, daily_cycle_date, worker_id, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (email, new_credits, daily_free, daily_cycle, new_worker_id, updated_at))
            
            conn.commit()
            
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

        current_cycle = cls.get_current_cycle_date(ref_time)
        updated_at = datetime.now(timezone.utc).isoformat()

        with get_connection() as conn:
            cursor = conn.cursor()
            # Use a write lock transaction by starting with BEGIN IMMEDIATE
            conn.execute("BEGIN IMMEDIATE")
            
            cursor.execute("SELECT * FROM accounts WHERE email = ?", (email,))
            row = cursor.fetchone()
            if not row:
                conn.commit()
                return 0, 0
                
            existing = dict(row)
            daily_cycle = existing.get("daily_cycle_date")
            daily_free = existing.get("daily_free_credits_remaining", DAILY_GRANT_AMOUNT)
            
            # Check daily grant reset
            if daily_cycle != current_cycle:
                daily_free = DAILY_GRANT_AMOUNT
                daily_cycle = current_cycle

            balance = existing.get("credits") or 0

            deduct_free = min(daily_free, cost)
            remain_cost = cost - deduct_free
            deduct_bal = min(balance, remain_cost)

            new_daily_free = daily_free - deduct_free
            new_credits = max(0, balance - deduct_bal) if existing.get("credits") is not None else None

            cursor.execute("""
                UPDATE accounts
                SET credits = ?, daily_free_credits_remaining = ?, daily_cycle_date = ?, updated_at = ?
                WHERE email = ?
            """, (new_credits, new_daily_free, daily_cycle, updated_at, email))
            
            conn.commit()

            logger.info(
                f"AccountCache: Deducted {cost} credits for {email} "
                f"(daily_free: -{deduct_free} => {new_daily_free}, "
                f"balance: -{deduct_bal} => {new_credits})"
            )
            return deduct_free, deduct_bal

    @classmethod
    def refund_credits(cls, email: str, daily_free: int, balance: int) -> None:
        """
        Refund deducted credits if a task fails before actual generation starts.
        """
        if not email or (daily_free <= 0 and balance <= 0):
            return

        updated_at = datetime.now(timezone.utc).isoformat()

        with get_connection() as conn:
            cursor = conn.cursor()
            conn.execute("BEGIN IMMEDIATE")
            
            cursor.execute("SELECT * FROM accounts WHERE email = ?", (email,))
            row = cursor.fetchone()
            if not row:
                conn.commit()
                return
                
            existing = dict(row)
            cur_free = existing.get("daily_free_credits_remaining", 0)
            cur_bal = existing.get("credits") or 0

            new_daily_free = cur_free + daily_free
            new_credits = cur_bal + balance if existing.get("credits") is not None else None

            cursor.execute("""
                UPDATE accounts
                SET credits = ?, daily_free_credits_remaining = ?, updated_at = ?
                WHERE email = ?
            """, (new_credits, new_daily_free, updated_at, email))
            
            conn.commit()

            logger.info(
                f"AccountCache: Refunded credits for {email} "
                f"(daily_free: +{daily_free} => {new_daily_free}, "
                f"balance: +{balance} => {new_credits})"
            )

    @classmethod
    def get(cls, email: str) -> Optional[dict]:
        """Get account entry by email."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM accounts WHERE email = ?", (email,))
            row = cursor.fetchone()
            return dict(row) if row else None

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
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT email FROM accounts")
            emails = [row["email"] for row in cursor.fetchall()]
            
        result = []
        for email in emails:
            refreshed = cls.ensure_daily_grant(email)
            if refreshed:
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
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT credits FROM accounts WHERE credits IS NOT NULL ORDER BY updated_at DESC LIMIT 1")
            row = cursor.fetchone()
            return row["credits"] if row else None
