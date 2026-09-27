import os
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta

import os
DB_NAME = "/data/finance.db"


# ============================================================
#                  ПАРОЛИ
# ============================================================
def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
    ).hex()


# ============================================================
#                    БАЗОВЫЕ ОПЕРАЦИИ
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            comment TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def add_operation(user_id: int, op_type: str, amount: float,
                  category: str, comment: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO operations (user_id, type, amount, category, comment, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, op_type, amount, category, comment,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()


def get_months(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT substr(created_at, 1, 7) AS month
        FROM operations
        WHERE user_id = ?
        ORDER BY month DESC
    """, (user_id,))
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def get_operations_for_month(user_id: int, month: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT type, amount, category, comment, created_at
        FROM operations
        WHERE user_id = ? AND substr(created_at, 1, 7) = ?
        ORDER BY created_at ASC
    """, (user_id, month))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_all_operations_for_month(user_id: int, month: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, type, amount, category, comment, created_at
        FROM operations
        WHERE user_id = ? AND substr(created_at, 1, 7) = ?
        ORDER BY created_at ASC
    """, (user_id, month))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_operations_for_range(user_id: int, start_date: str, end_date: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT type, amount, category, comment, created_at
        FROM operations
        WHERE user_id = ?
          AND substr(created_at, 1, 10) BETWEEN ? AND ?
        ORDER BY created_at ASC
    """, (user_id, start_date, end_date))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_prev_month(month: str) -> str:
    y, m = map(int, month.split("-"))
    if m == 1:
        return f"{y - 1}-12"
    return f"{y}-{m - 1:02d}"


def get_month_totals(user_id: int, month: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT type, SUM(amount)
        FROM operations
        WHERE user_id = ? AND substr(created_at, 1, 7) = ?
        GROUP BY type
    """, (user_id, month))
    rows = cur.fetchall()
    conn.close()
    totals = {"expense": 0.0, "income": 0.0}
    for t, s in rows:
        totals[t] = s or 0.0
    return totals["expense"], totals["income"]


def get_last_operation_dt(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT created_at FROM operations
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 1
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def get_earliest_operation_date(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT MIN(created_at) FROM operations WHERE user_id = ?",
                (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0][:10] if row and row[0] else None


# ============================================================
#                       НАСТРОЙКИ
# ============================================================
def init_settings_table():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            weekly_enabled INTEGER NOT NULL DEFAULT 0,
            weekly_time TEXT,
            tz_offset INTEGER DEFAULT 3,
            weekly_send_excel INTEGER NOT NULL DEFAULT 0,
            daily_enabled INTEGER NOT NULL DEFAULT 0,
            daily_time TEXT,
            daily_send_excel INTEGER NOT NULL DEFAULT 0,
            excel_include_ops INTEGER NOT NULL DEFAULT 1,
            excel_include_debts INTEGER NOT NULL DEFAULT 1,
            excel_include_payments INTEGER NOT NULL DEFAULT 1,
            excel_include_invest INTEGER NOT NULL DEFAULT 1,
            excel_include_profits INTEGER NOT NULL DEFAULT 1,
            reminder_enabled INTEGER NOT NULL DEFAULT 0,
            reminder_interval_hours INTEGER DEFAULT 4,
            reminder_last_sent TEXT,
            reminder_silent_from INTEGER DEFAULT 23,
            reminder_silent_to INTEGER DEFAULT 8,
            excel_on_debt_close INTEGER NOT NULL DEFAULT 0,
            excel_on_big_op INTEGER NOT NULL DEFAULT 0,
            excel_big_op_threshold REAL DEFAULT 10000,
            autoexport_enabled INTEGER NOT NULL DEFAULT 0,
            autoexport_weekday INTEGER DEFAULT 6,
            autoexport_time TEXT,
            autoexport_period TEXT DEFAULT 'week'
        )
    """)
    cur.execute("PRAGMA table_info(user_settings)")
    cols = [c[1] for c in cur.fetchall()]
    migrations = [
        ("weekly_send_excel", "INTEGER NOT NULL DEFAULT 0"),
        ("daily_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ("daily_time", "TEXT"),
        ("daily_send_excel", "INTEGER NOT NULL DEFAULT 0"),
        ("excel_include_ops", "INTEGER NOT NULL DEFAULT 1"),
        ("excel_include_debts", "INTEGER NOT NULL DEFAULT 1"),
        ("excel_include_payments", "INTEGER NOT NULL DEFAULT 1"),
        ("excel_include_invest", "INTEGER NOT NULL DEFAULT 1"),
        ("excel_include_profits", "INTEGER NOT NULL DEFAULT 1"),
        ("reminder_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ("reminder_interval_hours", "INTEGER DEFAULT 4"),
        ("reminder_last_sent", "TEXT"),
        ("reminder_silent_from", "INTEGER DEFAULT 23"),
        ("reminder_silent_to", "INTEGER DEFAULT 8"),
        ("excel_on_debt_close", "INTEGER NOT NULL DEFAULT 0"),
        ("excel_on_big_op", "INTEGER NOT NULL DEFAULT 0"),
        ("excel_big_op_threshold", "REAL DEFAULT 10000"),
        ("autoexport_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ("autoexport_weekday", "INTEGER DEFAULT 6"),
        ("autoexport_time", "TEXT"),
        ("autoexport_period", "TEXT DEFAULT 'week'"),
    ]
    for name, typ in migrations:
        if name not in cols:
            cur.execute(f"ALTER TABLE user_settings ADD COLUMN {name} {typ}")
    conn.commit()
    conn.close()


def get_settings(user_id: int):
    defaults = {
        "weekly_enabled": 0, "weekly_time": None, "tz_offset": 3,
        "weekly_send_excel": 0,
        "daily_enabled": 0, "daily_time": None, "daily_send_excel": 0,
        "excel_include_ops": 1, "excel_include_debts": 1,
        "excel_include_payments": 1, "excel_include_invest": 1,
        "excel_include_profits": 1,
        "reminder_enabled": 0, "reminder_interval_hours": 4,
        "reminder_last_sent": None,
        "reminder_silent_from": 23, "reminder_silent_to": 8,
        "excel_on_debt_close": 0, "excel_on_big_op": 0,
        "excel_big_op_threshold": 10000,
        "autoexport_enabled": 0, "autoexport_weekday": 6,
        "autoexport_time": None, "autoexport_period": "week",
    }
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT weekly_enabled, weekly_time, tz_offset, weekly_send_excel,
               daily_enabled, daily_time, daily_send_excel,
               excel_include_ops, excel_include_debts, excel_include_payments,
               excel_include_invest, excel_include_profits,
               reminder_enabled, reminder_interval_hours, reminder_last_sent,
               reminder_silent_from, reminder_silent_to,
               excel_on_debt_close, excel_on_big_op, excel_big_op_threshold,
               autoexport_enabled, autoexport_weekday, autoexport_time,
               autoexport_period
        FROM user_settings WHERE user_id = ?
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return defaults
    keys = list(defaults.keys())
    return {k: row[i] for i, k in enumerate(keys)}


def save_settings(user_id: int, **fields):
    if not fields:
        return
    current = get_settings(user_id)
    current.update(fields)
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO user_settings (
            user_id,
            weekly_enabled, weekly_time, tz_offset, weekly_send_excel,
            daily_enabled, daily_time, daily_send_excel,
            excel_include_ops, excel_include_debts, excel_include_payments,
            excel_include_invest, excel_include_profits,
            reminder_enabled, reminder_interval_hours, reminder_last_sent,
            reminder_silent_from, reminder_silent_to,
            excel_on_debt_close, excel_on_big_op, excel_big_op_threshold,
            autoexport_enabled, autoexport_weekday, autoexport_time,
            autoexport_period
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            weekly_enabled = excluded.weekly_enabled,
            weekly_time = excluded.weekly_time,
            tz_offset = excluded.tz_offset,
            weekly_send_excel = excluded.weekly_send_excel,
            daily_enabled = excluded.daily_enabled,
            daily_time = excluded.daily_time,
            daily_send_excel = excluded.daily_send_excel,
            excel_include_ops = excluded.excel_include_ops,
            excel_include_debts = excluded.excel_include_debts,
            excel_include_payments = excluded.excel_include_payments,
            excel_include_invest = excluded.excel_include_invest,
            excel_include_profits = excluded.excel_include_profits,
            reminder_enabled = excluded.reminder_enabled,
            reminder_interval_hours = excluded.reminder_interval_hours,
            reminder_last_sent = excluded.reminder_last_sent,
            reminder_silent_from = excluded.reminder_silent_from,
            reminder_silent_to = excluded.reminder_silent_to,
            excel_on_debt_close = excluded.excel_on_debt_close,
            excel_on_big_op = excluded.excel_on_big_op,
            excel_big_op_threshold = excluded.excel_big_op_threshold,
            autoexport_enabled = excluded.autoexport_enabled,
            autoexport_weekday = excluded.autoexport_weekday,
            autoexport_time = excluded.autoexport_time,
            autoexport_period = excluded.autoexport_period
    """, (
        user_id,
        current["weekly_enabled"], current["weekly_time"],
        current["tz_offset"], current["weekly_send_excel"],
        current["daily_enabled"], current["daily_time"], current["daily_send_excel"],
        current["excel_include_ops"], current["excel_include_debts"],
        current["excel_include_payments"], current["excel_include_invest"],
        current["excel_include_profits"],
        current["reminder_enabled"], current["reminder_interval_hours"],
        current["reminder_last_sent"],
        current["reminder_silent_from"], current["reminder_silent_to"],
        current["excel_on_debt_close"], current["excel_on_big_op"],
        current["excel_big_op_threshold"],
        current["autoexport_enabled"], current["autoexport_weekday"],
        current["autoexport_time"], current["autoexport_period"],
    ))
    conn.commit()
    conn.close()


def get_all_weekly_users():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, weekly_time, tz_offset, weekly_send_excel
        FROM user_settings
        WHERE weekly_enabled = 1 AND weekly_time IS NOT NULL
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def get_all_daily_users():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, daily_time, tz_offset, daily_send_excel
        FROM user_settings
        WHERE daily_enabled = 1 AND daily_time IS NOT NULL
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def get_all_reminder_users():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, reminder_interval_hours, reminder_last_sent,
               reminder_silent_from, reminder_silent_to, tz_offset
        FROM user_settings
        WHERE reminder_enabled = 1
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def update_reminder_last_sent(user_id: int, when_str: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE user_settings SET reminder_last_sent = ? WHERE user_id = ?",
                (when_str, user_id))
    conn.commit()
    conn.close()


def get_all_autoexport_users():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, autoexport_weekday, autoexport_time,
               autoexport_period, tz_offset
        FROM user_settings
        WHERE autoexport_enabled = 1 AND autoexport_time IS NOT NULL
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


# ============================================================
#                       ЗАДОЛЖЕННОСТИ
# ============================================================
def init_debts_tables():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS debts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            remaining REAL NOT NULL,
            comment TEXT,
            is_closed INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            closed_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS debt_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            debt_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def add_debt(user_id: int, amount: float, comment: str) -> int:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO debts (user_id, amount, remaining, comment, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, amount, amount, comment,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    debt_id = cur.lastrowid
    conn.commit()
    conn.close()
    return debt_id


def get_open_debts(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, amount, remaining, comment, created_at
        FROM debts
        WHERE user_id = ? AND is_closed = 0
        ORDER BY created_at ASC
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_all_debts(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, amount, remaining, comment, is_closed, created_at, closed_at
        FROM debts
        WHERE user_id = ?
        ORDER BY is_closed ASC, created_at DESC
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_all_debts_for_export(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, amount, remaining, comment, is_closed, created_at, closed_at
        FROM debts
        WHERE user_id = ?
        ORDER BY created_at ASC
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_debt(debt_id: int, user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, amount, remaining, comment, is_closed, created_at
        FROM debts WHERE id = ? AND user_id = ?
    """, (debt_id, user_id))
    row = cur.fetchone()
    conn.close()
    return row


def pay_debt(debt_id: int, user_id: int, amount: float):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT remaining FROM debts WHERE id = ? AND user_id = ?",
                (debt_id, user_id))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    new_remaining = row[0] - amount
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
        INSERT INTO debt_payments (debt_id, user_id, amount, created_at)
        VALUES (?, ?, ?, ?)
    """, (debt_id, user_id, amount, now))
    if new_remaining <= 0:
        cur.execute("""
            UPDATE debts SET remaining = 0, is_closed = 1, closed_at = ?
            WHERE id = ? AND user_id = ?
        """, (now, debt_id, user_id))
        new_remaining = 0
    else:
        cur.execute("UPDATE debts SET remaining = ? WHERE id = ? AND user_id = ?",
                    (new_remaining, debt_id, user_id))
    conn.commit()
    conn.close()
    return new_remaining


def get_total_debt(user_id: int) -> float:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(SUM(remaining), 0)
        FROM debts WHERE user_id = ? AND is_closed = 0
    """, (user_id,))
    total = cur.fetchone()[0] or 0.0
    conn.close()
    return total


def update_debt(debt_id: int, user_id: int,
                new_amount: float | None = None,
                new_comment: str | None = None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT amount, remaining, is_closed FROM debts
        WHERE id = ? AND user_id = ?
    """, (debt_id, user_id))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    old_amount, remaining, _ = row
    if new_amount is not None:
        new_remaining = remaining + (new_amount - old_amount)
        if new_remaining < 0:
            new_remaining = 0
        new_closed = 1 if new_remaining == 0 else 0
        cur.execute("""
            UPDATE debts
            SET amount = ?, remaining = ?, is_closed = ?,
                closed_at = CASE WHEN ? = 1 THEN closed_at ELSE NULL END
            WHERE id = ? AND user_id = ?
        """, (new_amount, new_remaining, new_closed, new_closed,
              debt_id, user_id))
    else:
        new_remaining = remaining
    if new_comment is not None:
        cur.execute("UPDATE debts SET comment = ? WHERE id = ? AND user_id = ?",
                    (new_comment, debt_id, user_id))
    conn.commit()
    conn.close()
    return (new_amount if new_amount is not None else old_amount, new_remaining)


def get_debt_payments(debt_id: int, user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT amount, created_at FROM debt_payments
        WHERE debt_id = ? AND user_id = ?
        ORDER BY created_at ASC
    """, (debt_id, user_id))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_last_payment(debt_id: int, user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, amount, created_at FROM debt_payments
        WHERE debt_id = ? AND user_id = ?
        ORDER BY created_at DESC, id DESC LIMIT 1
    """, (debt_id, user_id))
    row = cur.fetchone()
    conn.close()
    return row


def rollback_last_payment(debt_id: int, user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, amount FROM debt_payments
        WHERE debt_id = ? AND user_id = ?
        ORDER BY created_at DESC, id DESC LIMIT 1
    """, (debt_id, user_id))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    payment_id, removed_amount = row
    cur.execute("SELECT amount, remaining FROM debts WHERE id = ? AND user_id = ?",
                (debt_id, user_id))
    debt_row = cur.fetchone()
    if not debt_row:
        conn.close()
        return None
    amount, remaining = debt_row
    new_remaining = remaining + removed_amount
    if new_remaining > amount:
        new_remaining = amount
    cur.execute("DELETE FROM debt_payments WHERE id = ?", (payment_id,))
    cur.execute("""
        UPDATE debts SET remaining = ?, is_closed = 0, closed_at = NULL
        WHERE id = ? AND user_id = ?
    """, (new_remaining, debt_id, user_id))
    conn.commit()
    conn.close()
    return (removed_amount, new_remaining)


def get_debts_for_month(user_id: int, month: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, amount, remaining, comment, is_closed, created_at, closed_at
        FROM debts
        WHERE user_id = ? AND substr(created_at, 1, 7) = ?
        ORDER BY created_at ASC
    """, (user_id, month))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_debt_payments_for_month(user_id: int, month: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT p.id, p.debt_id, p.amount, p.created_at, d.comment
        FROM debt_payments p
        LEFT JOIN debts d ON d.id = p.debt_id
        WHERE p.user_id = ? AND substr(p.created_at, 1, 7) = ?
        ORDER BY p.created_at ASC
    """, (user_id, month))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_payments_all(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT p.id, p.debt_id, p.amount, p.created_at, d.comment
        FROM debt_payments p
        LEFT JOIN debts d ON d.id = p.debt_id
        WHERE p.user_id = ?
        ORDER BY p.created_at ASC
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


# ============================================================
#                       ИНВЕСТИЦИИ
# ============================================================
def init_invest_tables():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS investments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            comment TEXT,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_value (
            user_id INTEGER PRIMARY KEY,
            current_value REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def add_investment(user_id: int, inv_type: str, amount: float,
                   category: str, comment: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO investments (user_id, type, amount, category, comment, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, inv_type, amount, category, comment,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()


def get_investments(user_id: int, limit: int | None = None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    q = """
        SELECT id, type, amount, category, comment, created_at
        FROM investments WHERE user_id = ?
        ORDER BY created_at DESC, id DESC
    """
    if limit:
        q += f" LIMIT {int(limit)}"
    cur.execute(q, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_investments_all(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, type, amount, category, comment, created_at
        FROM investments WHERE user_id = ?
        ORDER BY created_at ASC
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_investments_for_month(user_id: int, month: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, type, amount, category, comment, created_at
        FROM investments
        WHERE user_id = ? AND substr(created_at, 1, 7) = ?
        ORDER BY created_at ASC
    """, (user_id, month))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_investment_totals(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT type, SUM(amount) FROM investments
        WHERE user_id = ? GROUP BY type
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    totals = {"deposit": 0.0, "withdraw": 0.0}
    for t, s in rows:
        totals[t] = s or 0.0
    return totals["deposit"], totals["withdraw"], totals["deposit"] - totals["withdraw"]


def get_investments_by_category(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT category, SUM(amount) FROM investments
        WHERE user_id = ? AND type = 'deposit'
        GROUP BY category ORDER BY SUM(amount) DESC
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def set_portfolio_value(user_id: int, value: float):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO portfolio_value (user_id, current_value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            current_value = excluded.current_value,
            updated_at = excluded.updated_at
    """, (user_id, value, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()


def get_portfolio_value(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT current_value, updated_at FROM portfolio_value WHERE user_id = ?",
                (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


# ============================================================
#                       ПРИБЫЛИ
# ============================================================
def init_profit_table():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS investment_profits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            source TEXT,
            comment TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def add_profit(user_id: int, amount: float, category: str,
               source: str, comment: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO investment_profits
            (user_id, amount, category, source, comment, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, amount, category, source, comment,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()


def get_total_realized_profit(user_id: int) -> float:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(amount), 0) FROM investment_profits WHERE user_id = ?",
                (user_id,))
    total = cur.fetchone()[0] or 0.0
    conn.close()
    return total


def get_profits(user_id: int, limit: int | None = None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    q = """
        SELECT id, amount, category, source, comment, created_at
        FROM investment_profits WHERE user_id = ?
        ORDER BY created_at DESC, id DESC
    """
    if limit:
        q += f" LIMIT {int(limit)}"
    cur.execute(q, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_profits_all(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, amount, category, source, comment, created_at
        FROM investment_profits WHERE user_id = ?
        ORDER BY created_at ASC
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_profits_for_month(user_id: int, month: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, amount, category, source, comment, created_at
        FROM investment_profits
        WHERE user_id = ? AND substr(created_at, 1, 7) = ?
        ORDER BY created_at ASC
    """, (user_id, month))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_profits_by_category(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT category, SUM(amount) FROM investment_profits
        WHERE user_id = ? GROUP BY category ORDER BY SUM(amount) DESC
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


# ============================================================
#                  ИСТОРИЯ ЭКСПОРТОВ
# ============================================================
def init_export_history_table():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS export_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            filepath TEXT,
            reason TEXT NOT NULL,
            period_start TEXT,
            period_end TEXT,
            size_bytes INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("PRAGMA table_info(export_history)")
    cols = [c[1] for c in cur.fetchall()]
    if "filepath" not in cols:
        cur.execute("ALTER TABLE export_history ADD COLUMN filepath TEXT")
    conn.commit()
    conn.close()


def add_export_history(user_id: int, filename: str, reason: str,
                       period_start: str = None, period_end: str = None,
                       size_bytes: int = 0, filepath: str = None) -> int:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO export_history
            (user_id, filename, filepath, reason, period_start, period_end,
             size_bytes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, filename, filepath, reason, period_start, period_end,
          size_bytes, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def get_export_history_filtered(user_id: int, reason_filter: str | None = None,
                                limit: int = 30):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    if reason_filter:
        cur.execute("""
            SELECT id, filename, reason, period_start, period_end,
                   size_bytes, created_at
            FROM export_history
            WHERE user_id = ? AND reason = ?
            ORDER BY created_at DESC, id DESC LIMIT ?
        """, (user_id, reason_filter, int(limit)))
    else:
        cur.execute("""
            SELECT id, filename, reason, period_start, period_end,
                   size_bytes, created_at
            FROM export_history
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC LIMIT ?
        """, (user_id, int(limit)))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_export_history_by_period(user_id: int, start_date: str, end_date: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, filename, reason, period_start, period_end,
               size_bytes, created_at
        FROM export_history
        WHERE user_id = ? AND substr(created_at, 1, 10) BETWEEN ? AND ?
        ORDER BY created_at ASC
    """, (user_id, start_date, end_date))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_export_by_id(exp_id: int, user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, filename, filepath, reason, period_start, period_end,
               size_bytes, created_at
        FROM export_history WHERE id = ? AND user_id = ?
    """, (exp_id, user_id))
    row = cur.fetchone()
    conn.close()
    return row


def delete_export(exp_id: int, user_id: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM export_history WHERE id = ? AND user_id = ?",
                (exp_id, user_id))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


# ============================================================
#                       АККАУНТЫ
# ============================================================
def init_accounts_table():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            login TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            tg_user_id INTEGER UNIQUE,
            role TEXT NOT NULL DEFAULT 'user',
            is_blocked INTEGER NOT NULL DEFAULT 0,
            display_name TEXT,
            created_at TEXT NOT NULL,
            last_login_at TEXT
        )
    """)
    cur.execute("PRAGMA table_info(accounts)")
    cols = [c[1] for c in cur.fetchall()]
    if "role" not in cols:
        cur.execute("ALTER TABLE accounts ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
        if "is_admin" in cols:
            cur.execute("UPDATE accounts SET role = 'admin' WHERE is_admin = 1")
    conn.commit()
    conn.close()


def register_account(login: str, password: str,
                     display_name: str | None = None):
    login = login.strip().lower()
    if len(login) < 3:
        return False, "Логин должен быть не короче 3 символов.", None
    if len(password) < 6:
        return False, "Пароль должен быть не короче 6 символов.", None

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id FROM accounts WHERE login = ?", (login,))
    if cur.fetchone():
        conn.close()
        return False, "Такой логин уже занят.", None

    cur.execute("SELECT COUNT(*) FROM accounts")
    is_first = cur.fetchone()[0] == 0
    role = "admin" if is_first else "user"

    salt = secrets.token_hex(16)
    pwd_hash = _hash_password(password, salt)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        INSERT INTO accounts (login, password_hash, salt, display_name,
                              role, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (login, pwd_hash, salt, display_name or login, role, now))
    account_id = cur.lastrowid
    conn.commit()
    conn.close()
    return True, "Аккаунт создан.", account_id


def authenticate(login: str, password: str):
    login = login.strip().lower()
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, password_hash, salt, is_blocked
        FROM accounts WHERE login = ?
    """, (login,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False, "Неверный логин или пароль.", None
    account_id, pwd_hash, salt, is_blocked = row
    if is_blocked:
        conn.close()
        return False, "Аккаунт заблокирован.", None
    if _hash_password(password, salt) != pwd_hash:
        conn.close()
        return False, "Неверный логин или пароль.", None
    cur.execute("UPDATE accounts SET last_login_at = ? WHERE id = ?",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), account_id))
    conn.commit()
    conn.close()
    return True, "OK", account_id


def get_account_by_id(account_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, login, tg_user_id, role, is_blocked,
               display_name, created_at, last_login_at
        FROM accounts WHERE id = ?
    """, (account_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_account_by_tg(tg_user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, login, tg_user_id, role, is_blocked,
               display_name, created_at, last_login_at
        FROM accounts WHERE tg_user_id = ?
    """, (tg_user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def link_tg_to_account(account_id: int, tg_user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE accounts SET tg_user_id = NULL WHERE tg_user_id = ?",
                (tg_user_id,))
    cur.execute("UPDATE accounts SET tg_user_id = ? WHERE id = ?",
                (tg_user_id, account_id))
    conn.commit()
    conn.close()


def unlink_tg(tg_user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE accounts SET tg_user_id = NULL WHERE tg_user_id = ?",
                (tg_user_id,))
    conn.commit()
    conn.close()


def change_password(account_id: int, old_password: str, new_password: str):
    if len(new_password) < 6:
        return False, "Новый пароль должен быть не короче 6 символов."
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT password_hash, salt FROM accounts WHERE id = ?",
                (account_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False, "Аккаунт не найден."
    pwd_hash, salt = row
    if _hash_password(old_password, salt) != pwd_hash:
        conn.close()
        return False, "Старый пароль неверный."
    new_salt = secrets.token_hex(16)
    new_hash = _hash_password(new_password, new_salt)
    cur.execute("UPDATE accounts SET password_hash = ?, salt = ? WHERE id = ?",
                (new_hash, new_salt, account_id))
    conn.commit()
    conn.close()
    return True, "Пароль обновлён."


def list_accounts():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, login, tg_user_id, role, is_blocked,
               display_name, created_at, last_login_at
        FROM accounts ORDER BY id ASC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def set_blocked(account_id: int, blocked: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE accounts SET is_blocked = ? WHERE id = ?",
                (blocked, account_id))
    conn.commit()
    conn.close()


def reset_password(account_id: int) -> str:
    new_password = secrets.token_urlsafe(10)
    salt = secrets.token_hex(16)
    pwd_hash = _hash_password(new_password, salt)
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE accounts SET password_hash = ?, salt = ? WHERE id = ?",
                (pwd_hash, salt, account_id))
    conn.commit()
    conn.close()
    return new_password


def set_role(account_id: int, role: str):
    if role not in ("user", "moderator", "admin"):
        return
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE accounts SET role = ? WHERE id = ?", (role, account_id))
    conn.commit()
    conn.close()


def get_account_role(account_id: int) -> str:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT role FROM accounts WHERE id = ?", (account_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else "user"


def migrate_existing_users():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    user_ids = set()
    for table in ("operations", "debts", "investments",
                  "investment_profits", "user_settings", "export_history"):
        try:
            cur.execute(f"SELECT DISTINCT user_id FROM {table}")
            for (uid,) in cur.fetchall():
                if uid:
                    user_ids.add(uid)
        except sqlite3.OperationalError:
            pass
    for uid in user_ids:
        login = f"tg_{uid}"
        cur.execute("SELECT id FROM accounts WHERE login = ?", (login,))
        if cur.fetchone():
            continue
        salt = secrets.token_hex(16)
        password = secrets.token_urlsafe(16)
        pwd_hash = _hash_password(password, salt)
        cur.execute("""
            INSERT INTO accounts (login, password_hash, salt, tg_user_id,
                                  role, created_at)
            VALUES (?, ?, ?, ?, 'user', ?)
        """, (login, pwd_hash, salt, uid,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    cur.execute("SELECT COUNT(*) FROM accounts WHERE role = 'admin'")
    if cur.fetchone()[0] == 0:
        cur.execute("SELECT id FROM accounts ORDER BY id ASC LIMIT 1")
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE accounts SET role = 'admin' WHERE id = ?", (row[0],))
    conn.commit()
    conn.close()


# ============================================================
#                    ЛОГ ПРОСМОТРОВ
# ============================================================
def init_view_log_table():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS view_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            viewer_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            section TEXT NOT NULL,
            detail TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def log_view(viewer_id: int, target_id: int, section: str, detail: str = None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO view_log (viewer_id, target_id, section, detail, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (viewer_id, target_id, section, detail,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()


def get_views_of_user(target_id: int, limit: int = 30):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT v.id, v.viewer_id, a.login, v.section, v.detail, v.created_at
        FROM view_log v
        LEFT JOIN accounts a ON a.id = v.viewer_id
        WHERE v.target_id = ?
        ORDER BY v.created_at DESC LIMIT ?
    """, (target_id, int(limit)))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_views_by_admin(viewer_id: int, limit: int = 30):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT v.id, v.target_id, a.login, v.section, v.detail, v.created_at
        FROM view_log v
        LEFT JOIN accounts a ON a.id = v.target_id
        WHERE v.viewer_id = ?
        ORDER BY v.created_at DESC LIMIT ?
    """, (viewer_id, int(limit)))
    rows = cur.fetchall()
    conn.close()
    return rows


# ============================================================
#                  ЗАПРОСЫ НА ПРОСМОТР
# ============================================================
def init_access_requests_table():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS access_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            viewer_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            section TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            expires_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def create_access_request(viewer_id: int, target_id: int, section: str) -> int:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        UPDATE access_requests SET status = 'expired', resolved_at = ?
        WHERE viewer_id = ? AND target_id = ? AND status = 'pending'
    """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), viewer_id, target_id))
    cur.execute("""
        INSERT INTO access_requests (viewer_id, target_id, section, status, created_at)
        VALUES (?, ?, ?, 'pending', ?)
    """, (viewer_id, target_id, section,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    req_id = cur.lastrowid
    conn.commit()
    conn.close()
    return req_id


def get_access_request(req_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, viewer_id, target_id, section, status,
               created_at, resolved_at, expires_at
        FROM access_requests WHERE id = ?
    """, (req_id,))
    row = cur.fetchone()
    conn.close()
    return row


def resolve_access_request(req_id: int, approve: bool, minutes: int = 30):
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    if approve:
        expires = (now + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
        status = "approved"
    else:
        expires = None
        status = "denied"
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        UPDATE access_requests SET status = ?, resolved_at = ?, expires_at = ?
        WHERE id = ?
    """, (status, now_str, expires, req_id))
    conn.commit()
    conn.close()


def has_active_access(viewer_id: int, target_id: int) -> bool:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM access_requests
        WHERE viewer_id = ? AND target_id = ?
          AND status = 'approved' AND expires_at > ?
    """, (viewer_id, target_id, now_str))
    cnt = cur.fetchone()[0]
    conn.close()
    return cnt > 0


def get_pending_requests_for_user(target_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT r.id, r.viewer_id, a.login, r.section, r.created_at
        FROM access_requests r
        LEFT JOIN accounts a ON a.id = r.viewer_id
        WHERE r.target_id = ? AND r.status = 'pending'
        ORDER BY r.created_at DESC
    """, (target_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_all_requests_for_user(target_id: int, limit: int = 30):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT r.id, r.viewer_id, a.login, r.section, r.status,
               r.created_at, r.resolved_at, r.expires_at
        FROM access_requests r
        LEFT JOIN accounts a ON a.id = r.viewer_id
        WHERE r.target_id = ?
        ORDER BY r.created_at DESC LIMIT ?
    """, (target_id, int(limit)))
    rows = cur.fetchall()
    conn.close()
    return rows


# ============================================================
#               ПОЛЬЗОВАТЕЛЬСКИЕ КАТЕГОРИИ
# ============================================================
DEFAULT_CATEGORIES = {
    "expense": ["Личные траты"],
    "income": ["Заработная плата", "Сторонние"],
    "invest": ["Акции", "Облигации", "Крипта", "ETF", "Недвижимость", "Другое"],
    "profit_source": ["Дивиденды", "Купоны", "Продажа", "Проценты", "Другое"],
}


def init_categories_table():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            position INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, kind, name)
        )
    """)
    conn.commit()
    conn.close()


def ensure_default_categories(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for kind, names in DEFAULT_CATEGORIES.items():
        cur.execute("""
            SELECT COUNT(*) FROM categories WHERE user_id = ? AND kind = ?
        """, (user_id, kind))
        if cur.fetchone()[0] == 0:
            for i, name in enumerate(names):
                cur.execute("""
                    INSERT OR IGNORE INTO categories
                        (user_id, kind, name, position, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (user_id, kind, name, i, now))
    conn.commit()
    conn.close()


def get_categories(user_id: int, kind: str):
    ensure_default_categories(user_id)
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT name FROM categories
        WHERE user_id = ? AND kind = ?
        ORDER BY position ASC, id ASC
    """, (user_id, kind))
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def add_category(user_id: int, kind: str, name: str):
    name = name.strip()
    if not name:
        return False, "Название не может быть пустым."
    if len(name) > 40:
        return False, "Название не длиннее 40 символов."
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM categories WHERE user_id = ? AND kind = ?
    """, (user_id, kind))
    cnt = cur.fetchone()[0]
    if cnt >= 30:
        conn.close()
        return False, "Максимум 30 категорий на раздел."
    cur.execute("""
        SELECT id FROM categories WHERE user_id = ? AND kind = ? AND name = ?
    """, (user_id, kind, name))
    if cur.fetchone():
        conn.close()
        return False, "Такая категория уже есть."
    cur.execute("""
        INSERT INTO categories (user_id, kind, name, position, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, kind, name, cnt,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    return True, "Категория добавлена."


def delete_category(user_id: int, kind: str, name: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM categories WHERE user_id = ? AND kind = ?
    """, (user_id, kind))
    if cur.fetchone()[0] <= 1:
        conn.close()
        return False, "Нельзя удалить последнюю категорию."
    cur.execute("""
        DELETE FROM categories WHERE user_id = ? AND kind = ? AND name = ?
    """, (user_id, kind, name))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    if not deleted:
        return False, "Категория не найдена."
    return True, "Категория удалена."


def rename_category(user_id: int, kind: str, old_name: str, new_name: str):
    new_name = new_name.strip()
    if not new_name:
        return False, "Название не может быть пустым."
    if len(new_name) > 40:
        return False, "Название не длиннее 40 символов."
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id FROM categories WHERE user_id = ? AND kind = ? AND name = ?
    """, (user_id, kind, new_name))
    if cur.fetchone():
        conn.close()
        return False, "Такая категория уже есть."
    cur.execute("""
        UPDATE categories SET name = ?
        WHERE user_id = ? AND kind = ? AND name = ?
    """, (new_name, user_id, kind, old_name))
    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    if not updated:
        return False, "Категория не найдена."
    return True, "Переименовано."
