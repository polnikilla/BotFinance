import sqlite3
import hashlib
import secrets
import os
from datetime import datetime

DB_NAME = os.getenv("DB_PATH", "finance.db")


# ============================================================
#                  ПАРОЛИ
# ============================================================
def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
    ).hex()


# ============================================================
#                 ИНИЦИАЛИЗАЦИЯ
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            login TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            tg_user_id INTEGER UNIQUE,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            number TEXT NOT NULL,
            total REAL NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS op_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            reason TEXT NOT NULL,
            position INTEGER DEFAULT 0,
            FOREIGN KEY(operation_id) REFERENCES operations(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            target REAL NOT NULL,
            current REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            is_closed INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS goal_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(goal_id) REFERENCES goals(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS drafts (
            user_id INTEGER PRIMARY KEY,
            total REAL NOT NULL,
            reason TEXT,
            items_json TEXT NOT NULL,
            used REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
#                 ПОЛЬЗОВАТЕЛИ
# ============================================================
def register_user(login: str, password: str):
    login = login.strip().lower()
    if len(login) < 3:
        return False, "Логин не короче 3 символов.", None
    if len(password) < 6:
        return False, "Пароль не короче 6 символов.", None

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE login = ?", (login,))
    if cur.fetchone():
        conn.close()
        return False, "Такой логин уже занят.", None

    salt = secrets.token_hex(16)
    pwd_hash = _hash_password(password, salt)
    cur.execute("""
        INSERT INTO users (login, password_hash, salt, created_at)
        VALUES (?, ?, ?, ?)
    """, (login, pwd_hash, salt,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    uid = cur.lastrowid
    conn.commit()
    conn.close()
    return True, "Аккаунт создан.", uid


def authenticate(login: str, password: str):
    login = login.strip().lower()
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, password_hash, salt FROM users WHERE login = ?",
                (login,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return False, "Неверный логин или пароль.", None
    uid, pwd_hash, salt = row
    if _hash_password(password, salt) != pwd_hash:
        return False, "Неверный логин или пароль.", None
    return True, "OK", uid


def get_user_by_tg(tg_user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, login FROM users WHERE tg_user_id = ?",
                (tg_user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_user_by_id(uid: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, login FROM users WHERE id = ?", (uid,))
    row = cur.fetchone()
    conn.close()
    return row


def get_tg_by_user_id(uid: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT tg_user_id FROM users WHERE id = ?", (uid,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def link_tg(uid: int, tg_user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE users SET tg_user_id = NULL WHERE tg_user_id = ?",
                (tg_user_id,))
    cur.execute("UPDATE users SET tg_user_id = ? WHERE id = ?",
                (tg_user_id, uid))
    conn.commit()
    conn.close()


def unlink_tg(tg_user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE users SET tg_user_id = NULL WHERE tg_user_id = ?",
                (tg_user_id,))
    conn.commit()
    conn.close()


# ============================================================
#                 ОПЕРАЦИИ
# ============================================================
def _next_number(cur, user_id: int, kind: str) -> str:
    prefix = "Т" if kind == "expense" else "З"
    cur.execute("""
        SELECT number FROM operations
        WHERE user_id = ? AND kind = ?
        ORDER BY id DESC LIMIT 1
    """, (user_id, kind))
    row = cur.fetchone()
    if not row:
        n = 1
    else:
        try:
            n = int(row[0].split(":")[1]) + 1
        except (IndexError, ValueError):
            n = 1
    return f"{prefix}:{n:05d}"


def add_operation(user_id: int, kind: str, total: float,
                  reason: str, items=None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    number = _next_number(cur, user_id, kind)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        INSERT INTO operations (user_id, kind, number, total, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, kind, number, total, reason, now))
    op_id = cur.lastrowid

    if items:
        for i, (amt, rsn) in enumerate(items):
            cur.execute("""
                INSERT INTO op_items (operation_id, amount, reason, position)
                VALUES (?, ?, ?, ?)
            """, (op_id, amt, rsn, i))

    conn.commit()
    conn.close()
    return op_id, number


def get_operation(operation_id: int, user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, kind, number, total, reason, created_at
        FROM operations WHERE id = ? AND user_id = ?
    """, (operation_id, user_id))
    row = cur.fetchone()
    conn.close()
    return row


def get_operation_by_number(user_id: int, number: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, kind, number, total, reason, created_at
        FROM operations WHERE user_id = ? AND UPPER(number) = UPPER(?)
    """, (user_id, number.strip()))
    row = cur.fetchone()
    conn.close()
    return row


def get_operation_items(operation_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT amount, reason FROM op_items
        WHERE operation_id = ? ORDER BY position ASC
    """, (operation_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_operations_for_month(user_id: int, month: str, kind: str = None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    if kind:
        cur.execute("""
            SELECT id, kind, number, total, reason, created_at
            FROM operations
            WHERE user_id = ? AND substr(created_at, 1, 7) = ? AND kind = ?
            ORDER BY created_at ASC
        """, (user_id, month, kind))
    else:
        cur.execute("""
            SELECT id, kind, number, total, reason, created_at
            FROM operations
            WHERE user_id = ? AND substr(created_at, 1, 7) = ?
            ORDER BY created_at ASC
        """, (user_id, month))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_last_operations(user_id: int, limit: int = 10):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, kind, number, total, reason, created_at
        FROM operations WHERE user_id = ?
        ORDER BY id DESC LIMIT ?
    """, (user_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_months(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT substr(created_at, 1, 7) AS m
        FROM operations WHERE user_id = ? ORDER BY m DESC
    """, (user_id,))
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def delete_operation(operation_id: int, user_id: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM op_items WHERE operation_id = ?", (operation_id,))
    cur.execute("DELETE FROM operations WHERE id = ? AND user_id = ?",
                (operation_id, user_id))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def update_operation_reason(operation_id: int, user_id: int, new_reason: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        UPDATE operations SET reason = ?
        WHERE id = ? AND user_id = ?
    """, (new_reason, operation_id, user_id))
    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def get_month_totals(user_id: int, month: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT kind, SUM(total) FROM operations
        WHERE user_id = ? AND substr(created_at, 1, 7) = ?
        GROUP BY kind
    """, (user_id, month))
    rows = cur.fetchall()
    conn.close()
    res = {"income": 0.0, "expense": 0.0}
    for k, s in rows:
        res[k] = s or 0.0
    return res


def get_top_expense_reasons(user_id: int, month: str, limit: int = 5):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT i.reason, SUM(i.amount) AS s
        FROM op_items i
        JOIN operations o ON o.id = i.operation_id
        WHERE o.user_id = ? AND substr(o.created_at, 1, 7) = ?
        GROUP BY i.reason
        ORDER BY s DESC LIMIT ?
    """, (user_id, month, limit))
    rows = cur.fetchall()
    conn.close()
    return rows


# ============================================================
#                 ЧЕРНОВИКИ ТРАТ
# ============================================================
def save_draft(user_id: int, total: float, reason: str,
               items: list, used: float):
    import json
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO drafts (user_id, total, reason, items_json, used, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            total = excluded.total,
            reason = excluded.reason,
            items_json = excluded.items_json,
            used = excluded.used,
            updated_at = excluded.updated_at
    """, (user_id, total, reason, json.dumps(items), used,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()


def get_draft(user_id: int):
    import json
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT total, reason, items_json, used, updated_at
        FROM drafts WHERE user_id = ?
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    total, reason, items_json, used, updated = row
    try:
        items = json.loads(items_json)
    except Exception:
        items = []
    return {"total": total, "reason": reason,
            "items": items, "used": used, "updated_at": updated}


def delete_draft(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM drafts WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


# ============================================================
#                 БЮДЖЕТЫ (бывшие цели)
# ============================================================
def add_goal(user_id: int, name: str, target: float):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO goals (user_id, name, target, current, created_at)
        VALUES (?, ?, ?, 0, ?)
    """, (user_id, name, target,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    gid = cur.lastrowid
    conn.commit()
    conn.close()
    return gid


def get_goals(user_id: int, include_closed: bool = False):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    if include_closed:
        cur.execute("""
            SELECT id, name, target, current, is_closed, created_at
            FROM goals WHERE user_id = ? ORDER BY id ASC
        """, (user_id,))
    else:
        cur.execute("""
            SELECT id, name, target, current, is_closed, created_at
            FROM goals WHERE user_id = ? AND is_closed = 0 ORDER BY id ASC
        """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_goal(goal_id: int, user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, target, current, is_closed, created_at
        FROM goals WHERE id = ? AND user_id = ?
    """, (goal_id, user_id))
    row = cur.fetchone()
    conn.close()
    return row


def goal_operation(goal_id: int, user_id: int, amount: float, reason: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT current, target FROM goals WHERE id = ? AND user_id = ?",
                (goal_id, user_id))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    current, target = row
    new_current = current + amount
    if new_current < 0:
        new_current = 0
    is_closed = 1 if new_current >= target else 0

    cur.execute("""
        INSERT INTO goal_log (goal_id, user_id, amount, reason, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (goal_id, user_id, amount, reason,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    cur.execute("""
        UPDATE goals SET current = ?, is_closed = ? WHERE id = ? AND user_id = ?
    """, (new_current, is_closed, goal_id, user_id))
    conn.commit()
    conn.close()
    return new_current


def get_goal_log(goal_id: int, user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT amount, reason, created_at FROM goal_log
        WHERE goal_id = ? AND user_id = ?
        ORDER BY created_at ASC
    """, (goal_id, user_id))
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_goal(goal_id: int, user_id: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM goal_log WHERE goal_id = ? AND user_id = ?",
                (goal_id, user_id))
    cur.execute("DELETE FROM goals WHERE id = ? AND user_id = ?",
                (goal_id, user_id))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


# ============================================================
#                    СМЕНЫ
# ============================================================
SAVED_BUDGET_NAME = "Не распределенные средства"
FUTURE_BUDGET_NAME = "Будущий оклад"
SAVED_DEFAULT_TARGET = 900000.0
FUTURE_DEFAULT_TARGET = 15000.0


def init_shift_tables():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            number TEXT NOT NULL,
            role_key TEXT NOT NULL,
            role_title TEXT NOT NULL,
            hours REAL NOT NULL,
            rate REAL NOT NULL,
            salary REAL NOT NULL,
            bonus REAL NOT NULL,
            total REAL NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS shift_fines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS monthly_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            spent REAL NOT NULL,
            earned REAL NOT NULL,
            saved REAL NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, month)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS shift_settings (
            user_id INTEGER PRIMARY KEY,
            opp_rate REAL DEFAULT 170,
            opp_bonus REAL DEFAULT 1960,
            cashier_rate REAL DEFAULT 144,
            admin_rate REAL DEFAULT 144,
            auto_report_enabled INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS auto_report_log (
            user_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            PRIMARY KEY (user_id, month)
        )
    """)
    conn.commit()
    conn.close()


def _next_shift_number(cur, user_id: int) -> str:
    cur.execute("""
        SELECT number FROM shifts WHERE user_id = ?
        ORDER BY id DESC LIMIT 1
    """, (user_id,))
    row = cur.fetchone()
    if not row:
        n = 1
    else:
        try:
            n = int(row[0].split("№")[1]) + 1
        except (IndexError, ValueError):
            n = 1
    return f"Заявка фик. смена №{n:05d}"


# ---------- Настройки ставок ----------
DEFAULT_SHIFT_SETTINGS = {
    "opp_rate": 170.0,
    "opp_bonus": 1960.0,
    "cashier_rate": 144.0,
    "admin_rate": 144.0,
    "auto_report_enabled": 0,
}


def get_shift_settings(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT opp_rate, opp_bonus, cashier_rate, admin_rate,
               auto_report_enabled
        FROM shift_settings WHERE user_id = ?
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return dict(DEFAULT_SHIFT_SETTINGS)
    keys = list(DEFAULT_SHIFT_SETTINGS.keys())
    return {k: row[i] for i, k in enumerate(keys)}


def save_shift_settings(user_id: int, **fields):
    cur_settings = get_shift_settings(user_id)
    cur_settings.update(fields)
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO shift_settings
            (user_id, opp_rate, opp_bonus, cashier_rate, admin_rate,
             auto_report_enabled)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            opp_rate = excluded.opp_rate,
            opp_bonus = excluded.opp_bonus,
            cashier_rate = excluded.cashier_rate,
            admin_rate = excluded.admin_rate,
            auto_report_enabled = excluded.auto_report_enabled
    """, (user_id,
          cur_settings["opp_rate"], cur_settings["opp_bonus"],
          cur_settings["cashier_rate"], cur_settings["admin_rate"],
          cur_settings["auto_report_enabled"]))
    conn.commit()
    conn.close()


def get_role_info(user_id: int, role_key: str):
    s = get_shift_settings(user_id)
    if role_key == "opp":
        return {"title": "Специалист ОПП",
                "rate": s["opp_rate"],
                "default_bonus": s["opp_bonus"]}
    if role_key == "cashier":
        return {"title": "Кассир-продавец",
                "rate": s["cashier_rate"],
                "default_bonus": None}
    if role_key == "admin_io":
        return {"title": "И.О. Администратора",
                "rate": s["admin_rate"],
                "default_bonus": None}
    return None


def add_shift(user_id: int, role_key: str, hours: float, bonus: float):
    info = get_role_info(user_id, role_key)
    if not info:
        raise ValueError("Unknown role_key")
    salary = hours * info["rate"]
    total = salary + bonus

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    number = _next_shift_number(cur, user_id)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
        INSERT INTO shifts (user_id, number, role_key, role_title, hours,
                            rate, salary, bonus, total, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, number, role_key, info["title"], hours,
          info["rate"], salary, bonus, total, now))
    shift_id = cur.lastrowid
    conn.commit()
    conn.close()
    return shift_id, number, salary, bonus, total


def get_shifts_for_month(user_id: int, month: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, number, role_key, role_title, hours, rate,
               salary, bonus, total, created_at
        FROM shifts
        WHERE user_id = ? AND substr(created_at, 1, 7) = ?
        ORDER BY created_at ASC
    """, (user_id, month))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_shift(shift_id: int, user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, number, role_key, role_title, hours, rate,
               salary, bonus, total, created_at
        FROM shifts WHERE id = ? AND user_id = ?
    """, (shift_id, user_id))
    row = cur.fetchone()
    conn.close()
    return row


def update_shift(shift_id: int, user_id: int,
                 new_salary: float = None, new_bonus: float = None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT salary, bonus FROM shifts WHERE id = ? AND user_id = ?
    """, (shift_id, user_id))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    salary, bonus = row
    if new_salary is not None:
        salary = new_salary
    if new_bonus is not None:
        bonus = new_bonus
    total = salary + bonus
    cur.execute("""
        UPDATE shifts SET salary = ?, bonus = ?, total = ?
        WHERE id = ? AND user_id = ?
    """, (salary, bonus, total, shift_id, user_id))
    conn.commit()
    conn.close()
    return salary, bonus, total


def delete_shift(shift_id: int, user_id: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM shifts WHERE id = ? AND user_id = ?",
                (shift_id, user_id))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


# ---------- Штрафы ----------
def add_fine(user_id: int, amount: float, reason: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO shift_fines (user_id, amount, reason, created_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, amount, reason,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    fid = cur.lastrowid
    conn.commit()
    conn.close()
    return fid


def get_fines_for_month(user_id: int, month: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, amount, reason, created_at
        FROM shift_fines
        WHERE user_id = ? AND substr(created_at, 1, 7) = ?
        ORDER BY created_at ASC
    """, (user_id, month))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_fines_total(user_id: int, month: str) -> float:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM shift_fines
        WHERE user_id = ? AND substr(created_at, 1, 7) = ?
    """, (user_id, month))
    s = cur.fetchone()[0] or 0.0
    conn.close()
    return s


def delete_fine(fine_id: int, user_id: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM shift_fines WHERE id = ? AND user_id = ?",
                (fine_id, user_id))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


# ---------- Системные бюджеты ----------
def get_or_create_budget(user_id: int, name: str, default_target: float):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, target, current FROM goals
        WHERE user_id = ? AND name = ?
    """, (user_id, name))
    row = cur.fetchone()
    if row:
        conn.close()
        return row
    cur.execute("""
        INSERT INTO goals (user_id, name, target, current, created_at)
        VALUES (?, ?, ?, 0, ?)
    """, (user_id, name, default_target,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    gid = cur.lastrowid
    conn.commit()
    conn.close()
    return (gid, name, default_target, 0.0)


def get_system_goal_current(user_id: int, name: str) -> float:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT current FROM goals WHERE user_id = ? AND name = ?
    """, (user_id, name))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0.0


def distribute_shift_to_goals(user_id: int, total: float,
                              old_pct=0.75, new_pct=0.25, sign=1):
    saved_part = total * old_pct
    future_part = total * new_pct
    g1 = get_or_create_budget(user_id, SAVED_BUDGET_NAME, SAVED_DEFAULT_TARGET)
    g2 = get_or_create_budget(user_id, FUTURE_BUDGET_NAME, FUTURE_DEFAULT_TARGET)
    goal_operation(g1[0], user_id, sign * saved_part, "Распределение 75%")
    goal_operation(g2[0], user_id, sign * future_part, "Распределение 25%")


def add_fine_to_future_goal(user_id: int, amount: float, reason: str):
    g = get_or_create_budget(user_id, FUTURE_BUDGET_NAME,
                             FUTURE_DEFAULT_TARGET)
    goal_operation(g[0], user_id, -amount, f"Штраф: {reason}")


def transfer_between_goals(user_id: int, from_id: int, to_id: int,
                           amount: float, reason: str = "Перевод"):
    if amount <= 0:
        return False, "Сумма должна быть положительной."
    src = get_goal(from_id, user_id)
    if not src:
        return False, "Исходный бюджет не найден."
    if src[3] < amount - 1e-9:
        return False, f"Недостаточно средств: {src[3]:g} ₽."
    dst = get_goal(to_id, user_id)
    if not dst:
        return False, "Целевой бюджет не найден."
    goal_operation(from_id, user_id, -amount, f"Перевод: {reason}")
    goal_operation(to_id, user_id, amount, f"Перевод: {reason}")
    return True, "Перевод выполнен."


# ---------- Отчёты за месяц ----------
def save_monthly_report(user_id: int, month: str,
                        spent: float, earned: float, saved: float):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO monthly_reports (user_id, month, spent, earned, saved, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, month) DO UPDATE SET
            spent = excluded.spent,
            earned = excluded.earned,
            saved = excluded.saved,
            created_at = excluded.created_at
    """, (user_id, month, spent, earned, saved,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()


def get_monthly_report(user_id: int, month: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT month, spent, earned, saved, created_at
        FROM monthly_reports WHERE user_id = ? AND month = ?
    """, (user_id, month))
    row = cur.fetchone()
    conn.close()
    return row


def get_all_monthly_reports(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT month, spent, earned, saved, created_at
        FROM monthly_reports WHERE user_id = ?
        ORDER BY month DESC
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


# ---------- Автоотчёт ----------
def get_auto_report_users():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id FROM shift_settings WHERE auto_report_enabled = 1
    """)
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def was_auto_report_sent(user_id: int, month: str) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT 1 FROM auto_report_log WHERE user_id = ? AND month = ?
    """, (user_id, month))
    row = cur.fetchone()
    conn.close()
    return row is not None


def mark_auto_report_sent(user_id: int, month: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO auto_report_log (user_id, month, sent_at)
        VALUES (?, ?, ?)
    """, (user_id, month, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    # ============================================================
#                 ГЛАВНОЕ МЕНЮ
# ============================================================
def main_menu_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💾 Внести операцию")],
            [KeyboardButton(text="🕐 Зафиксировать смену")],
            [KeyboardButton(text="💰 Бюджет")],
            [KeyboardButton(text="📋 Информация о операциях")],
            [KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="📅 Отчёт за месяц")],
            [KeyboardButton(text="🔎 Найти операцию")],
            [KeyboardButton(text="🕓 Последние операции")],
            [KeyboardButton(text="🚪 Выйти")],
        ],
        resize_keyboard=True
    )


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    u = current_user(message.from_user.id)
    if not u:
        await message.answer(
            "👋 Привет!\n\nЭто бот для учёта операций и бюджета.\n"
            "Войдите или зарегистрируйтесь:",
            reply_markup=auth_kb())
        return

    draft = get_draft(u[0])
    if draft:
        items = draft["items"]
        used = draft["used"]
        total = draft["total"]
        lines = [
            "⚠️ У вас есть <b>незавершённая трата</b>.",
            "",
            f"Общая сумма: <b>{total:g}</b> ₽",
            f"Распределено: <b>{used:g}</b> ₽",
            f"Остаток: <b>{total - used:g}</b> ₽",
            "",
            "Позиции:",
        ]
        for amt, rsn in items:
            lines.append(f"  • {amt:g} ₽ — {rsn}")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Продолжить",
                                  callback_data="draft:continue")],
            [InlineKeyboardButton(text="✅ Сохранить как есть",
                                  callback_data="draft:save")],
            [InlineKeyboardButton(text="🗑 Удалить черновик",
                                  callback_data="draft:delete")],
        ])
        await message.answer("\n".join(lines), parse_mode="HTML",
                             reply_markup=kb)
        return

    await message.answer(
        f"👋 С возвращением, <b>{u[1]}</b>!\n\nВыберите действие:",
        parse_mode="HTML", reply_markup=main_menu_kb())


@dp.message(F.text == "🚪 Выйти")
async def logout(message: Message, state: FSMContext):
    await state.clear()
    unlink_tg(message.from_user.id)
    await message.answer("🚪 Вы вышли. Нажмите /start для входа.")


# ============================================================
#               ВХОД / РЕГИСТРАЦИЯ
# ============================================================
@dp.callback_query(F.data == "auth:login")
async def auth_login_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(AuthFlow.login)
    await call.message.edit_text("Введите <b>логин</b>:", parse_mode="HTML")
    await call.answer()


@dp.message(AuthFlow.login)
async def auth_login_input(message: Message, state: FSMContext):
    await state.update_data(login=message.text.strip())
    await state.set_state(AuthFlow.password)
    await message.answer("Введите <b>пароль</b>:", parse_mode="HTML")


@dp.message(AuthFlow.password)
async def auth_password_input(message: Message, state: FSMContext):
    data = await state.get_data()
    ok, msg, uid_val = authenticate(data.get("login", ""), message.text.strip())
    await state.clear()
    if not ok:
        await message.answer(f"❌ {msg}", reply_markup=auth_kb())
        return
    link_tg(uid_val, message.from_user.id)
    await message.answer("✅ Вход выполнен. Добро пожаловать!",
                         reply_markup=main_menu_kb())


@dp.callback_query(F.data == "auth:register")
async def auth_reg_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(AuthFlow.reg_login)
    await call.message.edit_text(
        "📝 <b>Регистрация</b>\n\nПридумайте логин (мин. 3 символа):",
        parse_mode="HTML")
    await call.answer()


@dp.message(AuthFlow.reg_login)
async def auth_reg_login(message: Message, state: FSMContext):
    login = message.text.strip()
    if len(login) < 3:
        await message.answer("❗ Логин не короче 3 символов.")
        return
    await state.update_data(reg_login=login)
    await state.set_state(AuthFlow.reg_password)
    await message.answer("Придумайте пароль (мин. 6 символов):")


@dp.message(AuthFlow.reg_password)
async def auth_reg_password(message: Message, state: FSMContext):
    password = message.text.strip()
    if len(password) < 6:
        await message.answer("❗ Пароль не короче 6 символов.")
        return
    data = await state.get_data()
    ok, msg, uid_val = register_user(data.get("reg_login"), password)
    await state.clear()
    if not ok:
        await message.answer(f"❌ {msg}", reply_markup=auth_kb())
        return
    link_tg(uid_val, message.from_user.id)
    await message.answer("✅ Аккаунт создан. Добро пожаловать!",
                         reply_markup=main_menu_kb())


# ============================================================
#               ЧЕРНОВИКИ
# ============================================================
@dp.callback_query(F.data == "draft:continue")
async def draft_continue(call: CallbackQuery, state: FSMContext):
    draft = get_draft(uid(call))
    if not draft:
        await call.answer("Черновик не найден.")
        return
    await state.set_state(ExpenseFlow.items)
    await state.update_data(total=draft["total"], reason=draft["reason"],
                            items=draft["items"], used=draft["used"])
    await call.message.edit_text(
        f"▶️ Продолжаем.\n"
        f"Осталось распределить: <b>{draft['total'] - draft['used']:g}</b> ₽.\n"
        f"Формат: <code>сумма причина</code>",
        parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "draft:save")
async def draft_save(call: CallbackQuery, state: FSMContext):
    draft = get_draft(uid(call))
    if not draft:
        await call.answer("Черновик не найден.")
        return
    op_id, number = add_operation(
        user_id=uid(call), kind="expense",
        total=draft["used"], reason=draft["reason"],
        items=draft["items"])
    delete_draft(uid(call))
    await call.message.edit_text(
        f"✅ Трата сохранена из черновика.\n"
        f"Номер операции: <b>{number}</b>\n"
        f"Сумма: <b>{draft['used']:g}</b> ₽",
        parse_mode="HTML")
    await call.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await call.answer()


@dp.callback_query(F.data == "draft:delete")
async def draft_delete(call: CallbackQuery, state: FSMContext):
    delete_draft(uid(call))
    await call.message.edit_text("🗑 Черновик удалён.")
    await call.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await call.answer()


# ============================================================
#               ВНЕСТИ ОПЕРАЦИЮ
# ============================================================
def operation_type_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Зачисление", callback_data="op:income")],
        [InlineKeyboardButton(text="💸 Трата", callback_data="op:expense")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="op:cancel")],
    ])


@dp.message(F.text == "💾 Внести операцию")
async def op_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Выберите тип операции:",
                         reply_markup=operation_type_kb())


@dp.callback_query(F.data == "op:cancel")
async def op_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Отменено.")
    await call.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await call.answer()


# ============================================================
#               ЗАЧИСЛЕНИЕ
# ============================================================
@dp.callback_query(F.data == "op:income")
async def income_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(IncomeFlow.total)
    await call.message.edit_text(
        "💰 <b>Зачисление</b>\n\nВведите сумму:", parse_mode="HTML")
    await call.answer()


@dp.message(IncomeFlow.total)
async def income_total(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", ".").strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❗ Введите положительное число.")
        return
    await state.update_data(total=amount)
    await state.set_state(IncomeFlow.reason)
    await message.answer("Укажите основание/причину:")


@dp.message(IncomeFlow.reason)
async def income_reason(message: Message, state: FSMContext):
    data = await state.get_data()
    op_id, number = add_operation(uid(message), "income",
                                  data["total"], message.text.strip())
    await state.clear()
    await message.answer(
        f"✅ Зачисление сохранено.\n"
        f"Номер операции: <b>{number}</b>\n"
        f"Сумма: <b>{data['total']:g}</b> ₽\n"
        f"Основание: {message.text.strip()}",
        parse_mode="HTML", reply_markup=main_menu_kb())


# ============================================================
#               ТРАТА
# ============================================================
def continue_correct_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Продолжить", callback_data="exp:continue")],
        [InlineKeyboardButton(text="✏️ Скорректировать",
                              callback_data="exp:correct")],
    ])


@dp.callback_query(F.data == "op:expense")
async def expense_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(ExpenseFlow.total)
    await call.message.edit_text(
        "💸 <b>Трата</b>\n\nВведите общую сумму:", parse_mode="HTML")
    await call.answer()


@dp.message(ExpenseFlow.total)
async def expense_total(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", ".").strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❗ Введите положительное число.")
        return
    await state.update_data(total=amount, items=[], used=0.0)
    await state.set_state(ExpenseFlow.reason)
    await message.answer("Укажите общее назначение (кратко):")


@dp.message(ExpenseFlow.reason)
async def expense_reason(message: Message, state: FSMContext):
    await state.update_data(reason=message.text.strip())
    await state.set_state(ExpenseFlow.items)
    await message.answer(
        "Вводите по одной покупке в формате:\n"
        "<code>сумма причина</code>\n\nПример: <code>350 кофе</code>",
        parse_mode="HTML")


@dp.message(ExpenseFlow.items)
async def expense_item(message: Message, state: FSMContext):
    text = message.text.strip()
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❗ Формат: <code>сумма причина</code>",
                             parse_mode="HTML")
        return
    try:
        amt = float(parts[0].replace(",", "."))
        if amt <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❗ Сумма должна быть числом > 0.")
        return
    reason = parts[1].strip()

    data = await state.get_data()
    items = data.get("items", [])
    used = data.get("used", 0.0)
    total = data.get("total", 0.0)

    if used + amt > total + 1e-9:
        await message.answer(
            f"⚠️ Сумма превысит общую ({total:g} ₽).\n"
            f"Уже введено: {used:g} ₽.\n"
            f"Можно ввести не больше {total - used:g} ₽.")
        return

    items.append([amt, reason])
    used += amt
    await state.update_data(items=items, used=used)
    save_draft(uid(message), total, data.get("reason", "—"), items, used)

    if abs(used - total) < 1e-6:
        await _save_expense(message, state)
        return

    await message.answer(
        f"✅ Добавлено: <b>{amt:g}</b> ₽ — {reason}\n\n"
        f"Сейчас: <b>{used:g}</b> / {total:g} ₽\n"
        f"Осталось: <b>{total - used:g}</b> ₽",
        parse_mode="HTML", reply_markup=continue_correct_kb())


@dp.callback_query(ExpenseFlow.items, F.data == "exp:continue")
async def expense_continue(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    used = data.get("used", 0.0)
    total = data.get("total", 0.0)
    await call.message.edit_text(
        f"Продолжайте. Осталось: <b>{total - used:g}</b> ₽.\n"
        f"Формат: <code>сумма причина</code>",
        parse_mode="HTML")
    await call.answer()


@dp.callback_query(ExpenseFlow.items, F.data == "exp:correct")
async def expense_correct(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    used = data.get("used", 0.0)
    await state.update_data(total=used)
    await _save_expense(call, state, from_callback=True)


async def _save_expense(event, state: FSMContext, from_callback=False):
    data = await state.get_data()
    total = data.get("total", 0.0)
    reason = data.get("reason", "—")
    items = data.get("items", [])
    items_tuples = [(float(a), r) for a, r in items]

    op_id, number = add_operation(uid(event), "expense", total, reason,
                                  items_tuples)
    delete_draft(uid(event))
    await state.clear()

    lines = [
        "✅ Трата сохранена.",
        f"Номер операции: <b>{number}</b>",
        f"Сумма: <b>{total:g}</b> ₽",
        f"Назначение: {reason}",
        "",
        "Позиции:",
    ]
    for amt, rsn in items_tuples:
        lines.append(f"  • {amt:g} ₽ — {rsn}")
    text = "\n".join(lines)

    if from_callback:
        await event.message.edit_text(text, parse_mode="HTML")
        await event.message.answer("Главное меню:", reply_markup=main_menu_kb())
        await event.answer()
    else:
        await event.answer(text, parse_mode="HTML",
                           reply_markup=main_menu_kb())


# ============================================================
#               БЮДЖЕТ
# ============================================================
def _progress_bar(pct: int, length: int = 10) -> str:
    filled = int(pct / 100 * length)
    return "█" * filled + "░" * (length - filled)


def budget_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать бюджет",
                              callback_data="budget:create")],
        [InlineKeyboardButton(text="📋 Список бюджетов",
                              callback_data="budget:list")],
        [InlineKeyboardButton(text="🔄 Перевод между бюджетами",
                              callback_data="budget:transfer")],
    ])


def budget_list_kb(budgets):
    buttons = []
    for gid, name, target, current, is_closed, created in budgets:
        pct = int(current / target * 100) if target else 0
        icon = "✅" if is_closed else "💰"
        label = f"{icon} {name} — {current:g}/{target:g} ({pct}%)"
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"budget:view:{gid}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад",
                                         callback_data="budget:menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def budget_view_kb(goal_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Пополнить",
                              callback_data=f"budget:add:{goal_id}")],
        [InlineKeyboardButton(text="➖ Снять",
                              callback_data=f"budget:sub:{goal_id}")],
        [InlineKeyboardButton(text="🎯 Изменить целевую сумму",
                              callback_data=f"budget:target:{goal_id}")],
        [InlineKeyboardButton(text="📜 История",
                              callback_data=f"budget:log:{goal_id}")],
        [InlineKeyboardButton(text="🗑 Удалить",
                              callback_data=f"budget:del:{goal_id}")],
        [InlineKeyboardButton(text="⬅️ К списку",
                              callback_data="budget:list")],
    ])


def budget_pick_source_kb(budgets):
    buttons = []
    for gid, name, target, current, is_closed, created in budgets:
        if current > 0:
            buttons.append([InlineKeyboardButton(
                text=f"{name} ({current:g} ₽)",
                callback_data=f"budget:src:{gid}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад",
                                         callback_data="budget:menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def budget_pick_dest_kb(budgets):
    buttons = []
    for gid, name, target, current, is_closed, created in budgets:
        buttons.append([InlineKeyboardButton(
            text=name, callback_data=f"budget:dst:{gid}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад",
                                         callback_data="budget:menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(F.text == "💰 Бюджет")
async def budget_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("💰 <b>Бюджет</b>", parse_mode="HTML",
                         reply_markup=budget_menu_kb())


@dp.callback_query(F.data == "budget:menu")
async def budget_menu_cb(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("💰 <b>Бюджет</b>", parse_mode="HTML",
                                 reply_markup=budget_menu_kb())
    await call.answer()


@dp.callback_query(F.data == "budget:create")
async def budget_create(call: CallbackQuery, state: FSMContext):
    await state.set_state(BudgetCreate.name)
    await call.message.edit_text("Введите название бюджета:")
    await call.answer()


@dp.message(BudgetCreate.name)
async def budget_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(BudgetCreate.target)
    await message.answer("Введите целевую сумму:")


@dp.message(BudgetCreate.target)
async def budget_target(message: Message, state: FSMContext):
    try:
        target = float(message.text.replace(",", ".").strip())
        if target <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❗ Введите положительное число.")
        return
    data = await state.get_data()
    add_goal(uid(message), data["name"], target)
    await state.clear()
    await message.answer(
        f"✅ Бюджет «{data['name']}» создан.\n"
        f"Целевая сумма: <b>{target:g}</b> ₽",
        parse_mode="HTML", reply_markup=main_menu_kb())


@dp.callback_query(F.data == "budget:list")
async def budget_list(call: CallbackQuery, state: FSMContext):
    budgets = get_goals(uid(call))
    if not budgets:
        await call.message.edit_text(
            "Пока нет ни одного бюджета.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Создать бюджет",
                                      callback_data="budget:create")],
                [InlineKeyboardButton(text="⬅️ Назад",
                                      callback_data="budget:menu")]]))
        await call.answer()
        return
    await call.message.edit_text("Выберите бюджет:",
                                 reply_markup=budget_list_kb(budgets))
    await call.answer()


@dp.callback_query(F.data.startswith("budget:view:"))
async def budget_view(call: CallbackQuery, state: FSMContext):
    gid = int(call.data.split(":")[2])
    g = get_goal(gid, uid(call))
    if not g:
        await call.answer("Бюджет не найден.", show_alert=True)
        return
    _, name, target, current, is_closed, created = g
    pct = int(current / target * 100) if target else 0
    bar = _progress_bar(pct)
    status = "✅ достигнут" if is_closed else f"{bar} {pct}%"
    await call.message.edit_text(
        f"💰 <b>{name}</b>\n\n"
        f"Накоплено: <b>{current:g}</b> / {target:g} ₽\n"
        f"{status}\n"
        f"Создан: {created[:10]}",
        parse_mode="HTML", reply_markup=budget_view_kb(gid))
    await call.answer()


@dp.callback_query(F.data.startswith("budget:add:"))
async def budget_add(call: CallbackQuery, state: FSMContext):
    gid = int(call.data.split(":")[2])
    await state.set_state(BudgetOp.amount)
    await state.update_data(goal_id=gid, sign=1)
    await call.message.edit_text("💰 Введите сумму пополнения:")
    await call.answer()


@dp.callback_query(F.data.startswith("budget:sub:"))
async def budget_sub(call: CallbackQuery, state: FSMContext):
    gid = int(call.data.split(":")[2])
    await state.set_state(BudgetOp.amount)
    await state.update_data(goal_id=gid, sign=-1)
    await call.message.edit_text("➖ Введите сумму снятия:")
    await call.answer()


@dp.message(BudgetOp.amount)
async def budget_op_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", ".").strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❗ Введите положительное число.")
        return
    data = await state.get_data()
    await state.update_data(amount=amount * data.get("sign", 1))
    await state.set_state(BudgetOp.reason)
    await message.answer("Укажите причину/примечание:")


@dp.message(BudgetOp.reason)
async def budget_op_reason(message: Message, state: FSMContext):
    data = await state.get_data()
    new_current = goal_operation(data["goal_id"], uid(message),
                                 data["amount"], message.text.strip())
    await state.clear()
    if new_current is None:
        await message.answer("Бюджет не найден.",
                             reply_markup=main_menu_kb())
        return
    sign = "+" if data["amount"] > 0 else ""
    await message.answer(
        f"✅ Операция сохранена.\n"
        f"Изменение: <b>{sign}{data['amount']:g}</b> ₽\n"
        f"Текущий итог: <b>{new_current:g}</b> ₽",
        parse_mode="HTML", reply_markup=main_menu_kb())


@dp.callback_query(F.data.startswith("budget:target:"))
async def budget_target_start(call: CallbackQuery, state: FSMContext):
    gid = int(call.data.split(":")[2])
    await state.set_state(BudgetTarget.value)
    await state.update_data(goal_id=gid)
    g = get_goal(gid, uid(call))
    if g:
        await call.message.edit_text(
            f"Текущая цель: <b>{g[2]:g}</b> ₽\n\nВведите новую целевую сумму:",
            parse_mode="HTML")
    else:
        await call.message.edit_text("Введите новую целевую сумму:")
    await call.answer()


@dp.message(BudgetTarget.value)
async def budget_target_input(message: Message, state: FSMContext):
    try:
        v = float(message.text.replace(",", ".").strip())
        if v <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❗ Введите положительное число.")
        return
    data = await state.get_data()
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE goals SET target = ? WHERE id = ? AND user_id = ?",
                (v, data["goal_id"], uid(message)))
    conn.commit()
    conn.close()
    await state.clear()
    await message.answer(
        f"✅ Целевая сумма обновлена: <b>{v:g}</b> ₽",
        parse_mode="HTML", reply_markup=main_menu_kb())


@dp.callback_query(F.data.startswith("budget:log:"))
async def budget_log(call: CallbackQuery, state: FSMContext):
    gid = int(call.data.split(":")[2])
    g = get_goal(gid, uid(call))
    if not g:
        await call.answer("Бюджет не найден.", show_alert=True)
        return
    rows = get_goal_log(gid, uid(call))
    lines = [f"📜 <b>История бюджета «{g[1]}»</b>\n"]
    if not rows:
        lines.append("Пока нет операций.")
    else:
        for amount, reason, created in rows:
            sign = "+" if amount > 0 else ""
            lines.append(f"• {created[:16]} | {sign}{amount:g} ₽ | {reason}")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n…"
    await call.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ К бюджету",
                                  callback_data=f"budget:view:{gid}")]]))
    await call.answer()


@dp.callback_query(F.data.startswith("budget:del:"))
async def budget_del(call: CallbackQuery, state: FSMContext):
    gid = int(call.data.split(":")[2])
    delete_goal(gid, uid(call))
    await call.message.edit_text(
        "🗑 Бюджет удалён.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ К списку",
                                  callback_data="budget:list")]]))
    await call.answer()


# ---------- ПЕРЕВОД МЕЖДУ БЮДЖЕТАМИ ----------
@dp.callback_query(F.data == "budget:transfer")
async def budget_transfer(call: CallbackQuery, state: FSMContext):
    budgets = get_goals(uid(call), include_closed=True)
    if len(budgets) < 2:
        await call.answer("Нужно минимум 2 бюджета.", show_alert=True)
        return
    await state.set_state(BudgetTransfer.amount)
    await call.message.edit_text(
        "Выберите <b>откуда</b> переводить:",
        parse_mode="HTML",
        reply_markup=budget_pick_source_kb(budgets))
    await call.answer()


@dp.callback_query(BudgetTransfer.amount, F.data.startswith("budget:src:"))
async def budget_transfer_src(call: CallbackQuery, state: FSMContext):
    src_id = int(call.data.split(":")[2])
    await state.update_data(src_id=src_id)
    await state.set_state(BudgetTransfer.reason)
    budgets = get_goals(uid(call), include_closed=True)
    await call.message.edit_text(
        "Выберите <b>куда</b> переводить:",
        reply_markup=budget_pick_dest_kb(budgets))
    await call.answer()


@dp.callback_query(BudgetTransfer.reason, F.data.startswith("budget:dst:"))
async def budget_transfer_dst(call: CallbackQuery, state: FSMContext):
    dst_id = int(call.data.split(":")[2])
    data = await state.get_data()
    if dst_id == data.get("src_id"):
        await call.answer("Нельзя перевести в тот же бюджет.",
                          show_alert=True)
        return
    await state.update_data(dst_id=dst_id)
    await state.set_state(BudgetTransfer.amount)
    await call.message.edit_text("Введите сумму перевода:")
    await call.answer()


@dp.message(BudgetTransfer.amount)
async def budget_transfer_amount(message: Message, state: FSMContext):
    try:
        v = float(message.text.replace(",", ".").strip())
        if v <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❗ Введите положительное число.")
        return
    await state.update_data(amount=v)
    await state.set_state(BudgetTransfer.reason)
    await message.answer("Комментарий к переводу:")


@dp.message(BudgetTransfer.reason)
async def budget_transfer_reason(message: Message, state: FSMContext):
    data = await state.get_data()
    ok, msg = transfer_between_goals(
        uid(message), data["src_id"], data["dst_id"],
        data["amount"], message.text.strip())
    await state.clear()
    await message.answer(("✅ " if ok else "❌ ") + msg,
                         reply_markup=main_menu_kb())


# ============================================================
#               СМЕНЫ
# ============================================================
def shifts_menu_kb(status_auto: int):
    status = "✅" if status_auto else "❌"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕐 Зафиксировать смену",
                              callback_data="shift:add")],
        [InlineKeyboardButton(text="📋 Смены за месяц",
                              callback_data="shift:list")],
        [InlineKeyboardButton(text="💸 Внести штраф",
                              callback_data="shift:fine")],
        [InlineKeyboardButton(text="📤 Экспорт смен в CSV",
                              callback_data="shift:csv")],
        [InlineKeyboardButton(text="⚙️ Настройка ставок",
                              callback_data="shift:rates")],
        [InlineKeyboardButton(text="📅 Сформировать отчёт за месяц",
                              callback_data="shift:report")],
        [InlineKeyboardButton(
            text=f"🤖 Автоотчёт 30-го числа: {status}",
            callback_data="shift:auto_report")],
    ])


def shift_role_kb(s):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🎯 Специалист ОПП ({s['opp_rate']:g} ₽/ч, "
                 f"премия {s['opp_bonus']:g} ₽)",
            callback_data="shift:role:opp")],
        [InlineKeyboardButton(
            text=f"🛒 Кассир-продавец ({s['cashier_rate']:g} ₽/ч)",
            callback_data="shift:role:cashier")],
        [InlineKeyboardButton(
            text=f"👔 И.О. Администратора ({s['admin_rate']:g} ₽/ч)",
            callback_data="shift:role:admin_io")],
        [InlineKeyboardButton(text="⬅️ Назад",
                              callback_data="shift:menu")],
    ])


def shift_edit_kb(shift_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить оклад",
                              callback_data=f"shift:edit_salary:{shift_id}")],
        [InlineKeyboardButton(text="✏️ Изменить премию",
                              callback_data=f"shift:edit_bonus:{shift_id}")],
        [InlineKeyboardButton(text="🗑 Удалить",
                              callback_data=f"shift:del:{shift_id}")],
        [InlineKeyboardButton(text="⬅️ К списку",
                              callback_data="shift:list")],
    ])


def shifts_list_kb(shifts):
    buttons = []
    for (sid, number, rkey, rtitle, hours, rate,
         salary, bonus, total, created) in shifts:
        label = f"{number} | {rtitle} | {total:g} ₽"
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"shift:view:{sid}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад",
                                         callback_data="shift:menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(F.text == "🕐 Зафиксировать смену")
async def shifts_menu(message: Message, state: FSMContext):
    await state.clear()
    s = get_shift_settings(uid(message))
    await message.answer("🕐 <b>Смены</b>", parse_mode="HTML",
                         reply_markup=shifts_menu_kb(s["auto_report_enabled"]))


@dp
