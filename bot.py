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


@dp.callback_query(F.data == "shift:menu")
async def shifts_menu_cb(call: CallbackQuery, state: FSMContext):
    await state.clear()
    s = get_shift_settings(uid(call))
    await call.message.edit_text("🕐 <b>Смены</b>", parse_mode="HTML",
                                 reply_markup=shifts_menu_kb(s["auto_report_enabled"]))
    await call.answer()


@dp.callback_query(F.data == "shift:auto_report")
async def auto_report_toggle(call: CallbackQuery, state: FSMContext):
    s = get_shift_settings(uid(call))
    new_val = 0 if s["auto_report_enabled"] else 1
    save_shift_settings(uid(call), auto_report_enabled=new_val)
    await call.answer("Автоотчёт " + ("включён" if new_val else "выключен"))
    await shifts_menu_cb(call, state)


@dp.callback_query(F.data == "shift:add")
async def shift_add_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(ShiftFlow.role)
    s = get_shift_settings(uid(call))
    await call.message.edit_text("Выберите должность:",
                                 reply_markup=shift_role_kb(s))
    await call.answer()


@dp.callback_query(ShiftFlow.role, F.data.startswith("shift:role:"))
async def shift_role_chosen(call: CallbackQuery, state: FSMContext):
    role_key = call.data.split(":")[2]
    info = get_role_info(uid(call), role_key)
    if not info:
        await call.answer("Неизвестная должность.", show_alert=True)
        return
    await state.update_data(role_key=role_key)
    await state.set_state(ShiftFlow.hours)
    await call.message.edit_text(
        f"Должность: <b>{info['title']}</b>\n"
        f"Ставка: <b>{info['rate']:g} ₽/час</b>\n\n"
        f"Сколько часов отработано?",
        parse_mode="HTML")
    await call.answer()


@dp.message(ShiftFlow.hours)
async def shift_hours_input(message: Message, state: FSMContext):
    try:
        hours = float(message.text.replace(",", ".").strip())
        if hours <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❗ Введите положительное число часов.")
        return
    data = await state.get_data()
    role_key = data.get("role_key")
    info = get_role_info(uid(message), role_key)
    salary = hours * info["rate"]
    await state.update_data(hours=hours, salary=salary)
    await state.set_state(ShiftFlow.bonus)

    if info["default_bonus"] is not None:
        await message.answer(
            f"Оклад: <b>{hours:g} ч × {info['rate']:g} ₽ = "
            f"{salary:g} ₽</b>\n\n"
            f"Премия по умолчанию: <b>{info['default_bonus']:g} ₽</b>\n\n"
            f"Введите премию числом (или <code>-</code>, чтобы оставить "
            f"{info['default_bonus']:g} ₽).",
            parse_mode="HTML")
    else:
        await message.answer(
            f"Оклад: <b>{hours:g} ч × {info['rate']:g} ₽ = "
            f"{salary:g} ₽</b>\n\nВведите сумму премии:",
            parse_mode="HTML")


@dp.message(ShiftFlow.bonus)
async def shift_bonus_input(message: Message, state: FSMContext):
    raw = message.text.strip().replace(",", ".")
    data = await state.get_data()
    role_key = data.get("role_key")
    user_id = uid(message)
    info = get_role_info(user_id, role_key)

    if raw == "-":
        if info["default_bonus"] is None:
            await message.answer("❗ Введите премию числом.")
            return
        bonus = float(info["default_bonus"])
    else:
        try:
            bonus = float(raw)
            if bonus < 0:
                raise ValueError
        except ValueError:
            await message.answer("❗ Введите неотрицательное число.")
            return

    hours = data["hours"]
    salary = data["salary"]
    shift_id, number, sal, bon, total = add_shift(
        user_id, role_key, hours, bonus)
    distribute_shift_to_goals(user_id, total, sign=1)
    await state.clear()

    saved_now = get_system_goal_current(user_id, SAVED_BUDGET_NAME)
    future_now = get_system_goal_current(user_id, FUTURE_BUDGET_NAME)

    await message.answer(
        f"✅ <b>{number}</b>\n"
        f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"Должность: <b>{info['title']}</b>\n"
        f"Часов: {hours:g} × {info['rate']:g} ₽ = {salary:g} ₽\n"
        f"Премия: {bonus:g} ₽\n"
        f"<b>Сумма: {total:g} ₽</b>\n\n"
        f"📊 Распределение:\n"
        f"  • 75% → «{SAVED_BUDGET_NAME}»: <b>+{total * 0.75:g} ₽</b> "
        f"(итого: {saved_now:g} ₽)\n"
        f"  • 25% → «{FUTURE_BUDGET_NAME}»: <b>+{total * 0.25:g} ₽</b> "
        f"(итого: {future_now:g} ₽)",
        parse_mode="HTML", reply_markup=main_menu_kb())


@dp.callback_query(F.data == "shift:list")
async def shift_list_months(call: CallbackQuery, state: FSMContext):
    months = get_months(uid(call))
    if not months:
        await call.message.edit_text("Нет данных о сменах.",
                                     reply_markup=shifts_menu_kb(
                                         get_shift_settings(uid(call))["auto_report_enabled"]))
        await call.answer()
        return
    buttons = [[InlineKeyboardButton(
        text=f"{m.split('-')[1]}.{m.split('-')[0]}",
        callback_data=f"shift:list_month:{m}")]
        for m in months]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад",
                                         callback_data="shift:menu")])
    await call.message.edit_text("Выберите месяц:",
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()


@dp.callback_query(F.data.startswith("shift:list_month:"))
async def shift_list_month(call: CallbackQuery, state: FSMContext):
    month = call.data.split(":", 2)[2]
    user_id = uid(call)
    shifts = get_shifts_for_month(user_id, month)
    fines = get_fines_for_month(user_id, month)

    if not shifts and not fines:
        await call.message.edit_text(
            f"За {month} смен нет.",
            reply_markup=shifts_menu_kb(
                get_shift_settings(user_id)["auto_report_enabled"]))
        await call.answer()
        return

    total_sal = sum(s[6] for s in shifts)
    total_bonus = sum(s[7] for s in shifts)
    total_all = sum(s[8] for s in shifts)
    total_fines = sum(f[1] for f in fines)

    lines = [f"📋 <b>Смены за {month}</b>\n"]
    lines.append(f"Количество смен: <b>{len(shifts)}</b>")
    lines.append(f"Оклады: <b>{total_sal:g}</b> ₽")
    lines.append(f"Премии: <b>{total_bonus:g}</b> ₽")
    lines.append(f"Итого: <b>{total_all:g}</b> ₽")
    if total_fines:
        lines.append(f"Штрафы: <b>-{total_fines:g}</b> ₽")
        lines.append(f"К выплате: <b>{total_all - total_fines:g}</b> ₽")
    lines.append("")

    for (sid, number, rkey, rtitle, hours, rate,
         salary, bonus, total, created) in shifts:
        lines.append(
            f"<b>{number}</b>\n"
            f"  📅 {created[:16]}\n"
            f"  👔 {rtitle}\n"
            f"  💰 Оклад: {salary:g} ₽ | Премия: {bonus:g} ₽ | "
            f"<b>Итого {total:g} ₽</b>")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n…"

    await call.message.edit_text(text, parse_mode="HTML",
                                 reply_markup=shifts_list_kb(shifts))
    await call.answer()


@dp.callback_query(F.data.startswith("shift:view:"))
async def shift_view(call: CallbackQuery, state: FSMContext):
    sid = int(call.data.split(":")[2])
    s = get_shift(sid, uid(call))
    if not s:
        await call.answer("Смена не найдена.", show_alert=True)
        return
    (_, number, rkey, rtitle, hours, rate,
     salary, bonus, total, created) = s
    await call.message.edit_text(
        f"<b>{number}</b>\n"
        f"📅 {created[:16]}\n"
        f"👔 {rtitle}\n"
        f"⏱ {hours:g} ч × {rate:g} ₽ = {salary:g} ₽\n"
        f"🎁 Премия: {bonus:g} ₽\n"
        f"<b>Сумма: {total:g} ₽</b>\n\n"
        f"Распределение: 75% / 25%",
        parse_mode="HTML",
        reply_markup=shift_edit_kb(sid))
    await call.answer()


@dp.callback_query(F.data.startswith("shift:edit_salary:"))
async def shift_edit_salary(call: CallbackQuery, state: FSMContext):
    sid = int(call.data.split(":")[2])
    await state.set_state(ShiftEditFlow.salary)
    await state.update_data(shift_id=sid)
    await call.message.edit_text("Введите новый оклад (₽):")
    await call.answer()


@dp.message(ShiftEditFlow.salary)
async def shift_edit_salary_input(message: Message, state: FSMContext):
    try:
        v = float(message.text.replace(",", ".").strip())
        if v < 0:
            raise ValueError
    except ValueError:
        await message.answer("❗ Введите неотрицательное число.")
        return
    data = await state.get_data()
    sid = data["shift_id"]
    user_id = uid(message)
    old = get_shift(sid, user_id)
    if not old:
        await message.answer("Смена не найдена.", reply_markup=main_menu_kb())
        await state.clear()
        return
    old_total = old[8]
    result = update_shift(sid, user_id, new_salary=v)
    new_total = result[2]
    distribute_shift_to_goals(user_id, old_total, sign=-1)
    distribute_shift_to_goals(user_id, new_total, sign=1)
    await state.clear()
    await message.answer(
        f"✅ Оклад обновлён: {v:g} ₽\n"
        f"Новая сумма смены: <b>{new_total:g} ₽</b>\n"
        f"Распределение пересчитано.",
        parse_mode="HTML", reply_markup=main_menu_kb())


@dp.callback_query(F.data.startswith("shift:edit_bonus:"))
async def shift_edit_bonus(call: CallbackQuery, state: FSMContext):
    sid = int(call.data.split(":")[2])
    await state.set_state(ShiftEditFlow.bonus)
    await state.update_data(shift_id=sid)
    await call.message.edit_text("Введите новую премию (₽):")
    await call.answer()


@dp.message(ShiftEditFlow.bonus)
async def shift_edit_bonus_input(message: Message, state: FSMContext):
    try:
        v = float(message.text.replace(",", ".").strip())
        if v < 0:
            raise ValueError
    except ValueError:
        await message.answer("❗ Введите неотрицательное число.")
        return
    data = await state.get_data()
    sid = data["shift_id"]
    user_id = uid(message)
    old = get_shift(sid, user_id)
    if not old:
        await message.answer("Смена не найдена.", reply_markup=main_menu_kb())
        await state.clear()
        return
    old_total = old[8]
    result = update_shift(sid, user_id, new_bonus=v)
    new_total = result[2]
    distribute_shift_to_goals(user_id, old_total, sign=-1)
    distribute_shift_to_goals(user_id, new_total, sign=1)
    await state.clear()
    await message.answer(
        f"✅ Премия обновлена: {v:g} ₽\n"
        f"Новая сумма смены: <b>{new_total:g} ₽</b>\n"
        f"Распределение пересчитано.",
        parse_mode="HTML", reply_markup=main_menu_kb())


@dp.callback_query(F.data.startswith("shift:del:"))
async def shift_del(call: CallbackQuery, state: FSMContext):
    sid = int(call.data.split(":")[2])
    user_id = uid(call)
    s = get_shift(sid, user_id)
    if not s:
        await call.answer("Смена не найдена.", show_alert=True)
        return
    total = s[8]
    distribute_shift_to_goals(user_id, total, sign=-1)
    delete_shift(sid, user_id)
    await call.message.edit_text(
        "🗑 Смена удалена, распределение откатилось.",
        reply_markup=shifts_menu_kb(
            get_shift_settings(user_id)["auto_report_enabled"]))
    await call.answer()


# ---------- ШТРАФЫ ----------
@dp.callback_query(F.data == "shift:fine")
async def fine_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(FineFlow.amount)
    await call.message.edit_text(
        f"💸 Введите сумму штрафа (спишется с бюджета "
        f"«{FUTURE_BUDGET_NAME}»):")
    await call.answer()


@dp.message(FineFlow.amount)
async def fine_amount(message: Message, state: FSMContext):
    try:
        v = float(message.text.replace(",", ".").strip())
        if v <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❗ Введите положительное число.")
        return
    await state.update_data(amount=v)
    await state.set_state(FineFlow.reason)
    await message.answer("Укажите причину штрафа:")


@dp.message(FineFlow.reason)
async def fine_reason(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = uid(message)
    add_fine(user_id, data["amount"], message.text.strip())
    add_fine_to_future_goal(user_id, data["amount"], message.text.strip())
    await state.clear()
    future_now = get_system_goal_current(user_id, FUTURE_BUDGET_NAME)
    await message.answer(
        f"✅ Штраф <b>{data['amount']:g}</b> ₽ учтён.\n"
        f"Причина: {message.text.strip()}\n\n"
        f"Остаток в бюджете «{FUTURE_BUDGET_NAME}»: "
        f"<b>{future_now:g}</b> ₽",
        parse_mode="HTML", reply_markup=main_menu_kb())


# ---------- ЭКСПОРТ CSV ----------
@dp.callback_query(F.data == "shift:csv")
async def shift_csv_menu(call: CallbackQuery, state: FSMContext):
    months = get_months(uid(call))
    if not months:
        await call.answer("Нет данных.", show_alert=True)
        return
    buttons = [[InlineKeyboardButton(
        text=f"{m.split('-')[1]}.{m.split('-')[0]}",
        callback_data=f"shift:csv_month:{m}")]
        for m in months]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад",
                                         callback_data="shift:menu")])
    await call.message.edit_text("Выберите месяц для экспорта:",
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()


@dp.callback_query(F.data.startswith("shift:csv_month:"))
async def shift_csv_export(call: CallbackQuery, state: FSMContext):
    month = call.data.split(":", 2)[2]
    shifts = get_shifts_for_month(uid(call), month)
    fines = get_fines_for_month(uid(call), month)

    lines = ["Номер;Дата;Должность;Часы;Ставка;Оклад;Премия;Итого"]
    total_sal = 0
    total_bonus = 0
    total_all = 0
    for (sid, number, rkey, rtitle, hours, rate,
         salary, bonus, total, created) in shifts:
        total_sal += salary
        total_bonus += bonus
        total_all += total
        lines.append(
            f"{number};{created[:16]};{rtitle};{hours:g};{rate:g};"
            f"{salary:g};{bonus:g};{total:g}")
    lines.append("")
    lines.append(f";;;;ИТОГО ОКЛАДОВ;;;{total_sal:g}")
    lines.append(f";;;;ИТОГО ПРЕМИЙ;;;{total_bonus:g}")
    lines.append(f";;;;ИТОГО;;;{total_all:g}")

    if fines:
        lines.append("")
        lines.append("Штрафы:")
        lines.append("Дата;Сумма;Причина")
        for fid, amount, reason, created in fines:
            lines.append(f"{created[:16]};{amount:g};{reason}")
        total_fines = sum(f[1] for f in fines)
        lines.append(f";ИТОГО ШТРАФОВ;{total_fines:g}")
        lines.append(f";К ВЫПЛАТЕ;{total_all - total_fines:g}")

    csv_data = "\n".join(lines).encode("utf-8-sig")
    file = BufferedInputFile(csv_data, filename=f"shifts_{month}.csv")
    await call.message.answer_document(file,
                                       caption=f"📤 Экспорт смен за {month}")
    await call.answer()


# ---------- СТАВКИ ----------
def rates_menu_kb(s):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"Специалист ОПП: ставка {s['opp_rate']:g} ₽/ч",
            callback_data="rates:opp_rate")],
        [InlineKeyboardButton(
            text=f"Специалист ОПП: премия {s['opp_bonus']:g} ₽",
            callback_data="rates:opp_bonus")],
        [InlineKeyboardButton(
            text=f"Кассир-продавец: {s['cashier_rate']:g} ₽/ч",
            callback_data="rates:cashier_rate")],
        [InlineKeyboardButton(
            text=f"И.О. Администратора: {s['admin_rate']:g} ₽/ч",
            callback_data="rates:admin_rate")],
        [InlineKeyboardButton(text="⬅️ Назад",
                              callback_data="shift:menu")],
    ])


@dp.callback_query(F.data == "shift:rates")
async def rates_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    s = get_shift_settings(uid(call))
    await call.message.edit_text("⚙️ <b>Настройка ставок</b>",
                                 parse_mode="HTML",
                                 reply_markup=rates_menu_kb(s))
    await call.answer()


@dp.callback_query(F.data.startswith("rates:"))
async def rates_pick(call: CallbackQuery, state: FSMContext):
    field = call.data.split(":")[1]
    mapping = {
        "opp_rate": (RateFlow.opp_rate,
                     "Введите ставку Специалиста ОПП (₽/ч):"),
        "opp_bonus": (RateFlow.opp_bonus,
                      "Введите премию Специалиста ОПП (₽):"),
        "cashier_rate": (RateFlow.cashier_rate,
                         "Введите ставку Кассира-продавца (₽/ч):"),
        "admin_rate": (RateFlow.admin_rate,
                       "Введите ставку И.О. Администратора (₽/ч):"),
    }
    if field not in mapping:
        await call.answer("Неизвестный параметр.")
        return
    state_obj, question = mapping[field]
    await state.set_state(state_obj)
    await call.message.edit_text(question)
    await call.answer()


@dp.message(RateFlow.opp_rate)
async def rate_opp_rate(message: Message, state: FSMContext):
    await _save_rate(message, state, "opp_rate")


@dp.message(RateFlow.opp_bonus)
async def rate_opp_bonus(message: Message, state: FSMContext):
    await _save_rate(message, state, "opp_bonus")


@dp.message(RateFlow.cashier_rate)
async def rate_cashier(message: Message, state: FSMContext):
    await _save_rate(message, state, "cashier_rate")


@dp.message(RateFlow.admin_rate)
async def rate_admin(message: Message, state: FSMContext):
    await _save_rate(message, state, "admin_rate")


async def _save_rate(message: Message, state: FSMContext, field: str):
    try:
        v = float(message.text.replace(",", ".").strip())
        if v <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❗ Введите положительное число.")
        return
    save_shift_settings(uid(message), **{field: v})
    await state.clear()
    s = get_shift_settings(uid(message))
    await message.answer("✅ Ставка обновлена.",
                         reply_markup=rates_menu_kb(s))


# ---------- ОТЧЁТ ЗА МЕСЯЦ ----------
def month_names_ru():
    return {
        "01": "Январь", "02": "Февраль", "03": "Март", "04": "Апрель",
        "05": "Май", "06": "Июнь", "07": "Июль", "08": "Август",
        "09": "Сентябрь", "10": "Октябрь", "11": "Ноябрь", "12": "Декабрь",
    }


@dp.callback_query(F.data == "shift:report")
async def month_report_menu(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        "📅 <b>Отчёт за месяц</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🆕 Сформировать за месяц",
                                  callback_data="mreport:create")],
            [InlineKeyboardButton(text="📜 История отчётов",
                                  callback_data="mreport:history")],
            [InlineKeyboardButton(text="⬅️ Назад",
                                  callback_data="shift:menu")],
        ]))
    await call.answer()


@dp.callback_query(F.data == "mreport:create")
async def mreport_create(call: CallbackQuery, state: FSMContext):
    months = get_months(uid(call))
    if not months:
        await call.answer("Нет данных.", show_alert=True)
        return
    buttons = [[InlineKeyboardButton(
        text=f"{m.split('-')[1]}.{m.split('-')[0]}",
        callback_data=f"mreport:month:{m}")]
        for m in months]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад",
                                         callback_data="shift:report")])
    await call.message.edit_text("Выберите месяц для формирования отчёта:",
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()


@dp.callback_query(F.data.startswith("mreport:month:"))
async def mreport_show(call: CallbackQuery, state: FSMContext):
    month = call.data.split(":", 2)[2]
    user_id = uid(call)

    totals = get_month_totals(user_id, month)
    spent = totals["expense"]
    saved = get_system_goal_current(user_id, SAVED_BUDGET_NAME)
    earned = get_system_goal_current(user_id, FUTURE_BUDGET_NAME)
    save_monthly_report(user_id, month, spent, earned, saved)

    y, m = month.split("-")
    title = f"{month_names_ru().get(m, m)} {y}"
    text = (
        f"📅 <b>Отчёт за {title}</b>\n\n"
        f"💸 Потрачено средств: <b>{spent:g}</b> ₽\n"
        f"💰 Заработано средств: <b>{earned:g}</b> ₽\n"
        f"   <i>(из бюджета «{FUTURE_BUDGET_NAME}»)</i>\n"
        f"🏦 Отложенные средства: <b>{saved:g}</b> ₽\n"
        f"   <i>(из бюджета «{SAVED_BUDGET_NAME}»)</i>"
    )
    await call.message.edit_text(text, parse_mode="HTML",
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                     [InlineKeyboardButton(text="⬅️ Назад",
                                                           callback_data="shift:report")]]))
    await call.answer()


@dp.callback_query(F.data == "mreport:history")
async def mreport_history(call: CallbackQuery, state: FSMContext):
    rows = get_all_monthly_reports(uid(call))
    if not rows:
        await call.message.edit_text(
            "Пока нет сохранённых отчётов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад",
                                      callback_data="shift:report")]]))
        await call.answer()
        return
    lines = ["📜 <b>История отчётов</b>\n"]
    for month, spent, earned, saved, created in rows:
        lines.append(
            f"<b>{month}</b>\n"
            f"  💸 Потрачено: {spent:g} ₽\n"
            f"  💰 Заработано: {earned:g} ₽\n"
            f"  🏦 Отложено: {saved:g} ₽\n"
            f"  <i>Сформирован: {created[:16]}</i>\n")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n…"
    await call.message.edit_text(text, parse_mode="HTML",
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                     [InlineKeyboardButton(text="⬅️ Назад",
                                                           callback_data="shift:report")]]))
    await call.answer()


# ============================================================
#               ИНФОРМАЦИЯ ОБ ОПЕРАЦИЯХ
# ============================================================
def view_kind_kb(month: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Зачисления",
                              callback_data=f"view:income:{month}")],
        [InlineKeyboardButton(text="💸 Траты",
                              callback_data=f"view:expense:{month}")],
        [InlineKeyboardButton(text="📊 Все",
                              callback_data=f"view:all:{month}")],
        [InlineKeyboardButton(text="📤 Вывести данные за месяц (CSV)",
                              callback_data=f"view:csv:{month}")],
        [InlineKeyboardButton(text="⬅️ Назад",
                              callback_data="view:menu")],
    ])


def back_to_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="view:menu")]
    ])


def op_card_kb(op_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить примечание",
                              callback_data=f"op_edit:{op_id}")],
        [InlineKeyboardButton(text="🗑 Удалить операцию",
                              callback_data=f"op_del:{op_id}")],
        [InlineKeyboardButton(text="⬅️ Назад",
                              callback_data="view:menu")],
    ])


def build_months_kb(user_id: int):
    months = get_months(user_id)
    if not months:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="view:menu")]])
    buttons = [[InlineKeyboardButton(
        text=f"{m.split('-')[1]}.{m.split('-')[0]}",
        callback_data=f"view:pick:{m}")]
        for m in months]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(F.text == "📋 Информация о операциях")
async def view_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("📋 <b>Информация о операциях</b>\n\nВыберите месяц:",
                         parse_mode="HTML",
                         reply_markup=build_months_kb(uid(message)))


@dp.callback_query(F.data == "view:menu")
async def view_menu_cb(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "📋 <b>Информация о операциях</b>\n\nВыберите месяц:",
        parse_mode="HTML",
        reply_markup=build_months_kb(uid(call)))
    await call.answer()


@dp.callback_query(F.data.startswith("view:pick:"))
async def view_pick_month(call: CallbackQuery, state: FSMContext):
    month = call.data.split(":", 2)[2]
    await state.update_data(month=month)
    await call.message.edit_text(
        f"Месяц: <b>{month}</b>\n\nВыберите тип:",
        parse_mode="HTML", reply_markup=view_kind_kb(month))
    await call.answer()


@dp.callback_query(F.data.startswith("view:income:") |
                   F.data.startswith("view:expense:") |
                   F.data.startswith("view:all:"))
async def view_show(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":", 2)
    kind = parts[1]
    month = parts[2]
    kind_map = {"income": "income", "expense": "expense", "all": None}
    ops = get_operations_for_month(uid(call), month, kind_map[kind])
    if not ops:
        await call.message.edit_text(f"За {month} ничего не найдено.",
                                     reply_markup=back_to_menu_kb())
        await call.answer()
        return
    lines = [f"📋 <b>Операции за {month}</b>\n"]
    for op_id, k, number, total, reason, created in ops:
        icon = "💰" if k == "income" else "💸"
        lines.append(
            f"{icon} <b>{number}</b>\n"
            f"   Сумма: <b>{total:g}</b> ₽\n"
            f"   Дата: {created[:16]}\n"
            f"   Причина: {reason}")
        if k == "expense":
            items = get_operation_items(op_id)
            if items:
                lines.append("   Позиции:")
                for amt, rsn in items:
                    lines.append(f"     • {amt:g} ₽ — {rsn}")
        lines.append("")

    totals = get_month_totals(uid(call), month)
    lines.append("━━━━━━━━━━━━━━━")
    lines.append(f"💰 Всего зачислений: <b>{totals['income']:g}</b> ₽")
    lines.append(f"💸 Всего трат: <b>{totals['expense']:g}</b> ₽")
    lines.append(f"📊 Баланс: <b>{totals['income'] - totals['expense']:g}</b> ₽")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n…"
    await call.message.edit_text(text, parse_mode="HTML",
                                 reply_markup=back_to_menu_kb())
    await call.answer()


@dp.callback_query(F.data.startswith("view:csv:"))
async def view_csv(call: CallbackQuery, state: FSMContext):
    month = call.data.split(":", 2)[2]
    ops = get_operations_for_month(uid(call), month, None)
    if not ops:
        await call.answer("Нет данных.", show_alert=True)
        return
    lines = ["Номер;Тип;Сумма;Дата;Причина;Позиции"]
    for op_id, k, number, total, reason, created in ops:
        type_ru = "Зачисление" if k == "income" else "Трата"
        items_str = ""
        if k == "expense":
            items = get_operation_items(op_id)
            items_str = "; ".join(f"{amt:g} — {rsn}" for amt, rsn in items)
        safe_reason = (reason or "").replace(";", ",").replace('"', '""')
        safe_items = items_str.replace(";", ",").replace('"', '""')
        lines.append(f'{number};{type_ru};{total:g};{created};'
                     f'"{safe_reason}";"{safe_items}"')
    csv_data = "\n".join(lines).encode("utf-8-sig")
    file = BufferedInputFile(csv_data, filename=f"operations_{month}.csv")
    await call.message.answer_document(file,
                                       caption=f"📤 Данные за {month}")
    await call.answer()


# ---------- КАРТОЧКА ОПЕРАЦИИ ----------
@dp.callback_query(F.data.startswith("op_view:"))
async def op_view(call: CallbackQuery, state: FSMContext):
    op_id = int(call.data.split(":")[1])
    op = get_operation(op_id, uid(call))
    if not op:
        await call.answer("Операция не найдена.", show_alert=True)
        return
    _, kind, number, total, reason, created = op
    icon = "💰" if kind == "income" else "💸"
    lines = [
        f"{icon} <b>{number}</b>",
        f"Сумма: <b>{total:g}</b> ₽",
        f"Дата: {created[:16]}",
        f"Причина: {reason}",
    ]
    if kind == "expense":
        items = get_operation_items(op_id)
        if items:
            lines.append("")
            lines.append("Позиции:")
            for amt, rsn in items:
                lines.append(f"  • {amt:g} ₽ — {rsn}")
    await call.message.edit_text("\n".join(lines), parse_mode="HTML",
                                 reply_markup=op_card_kb(op_id))
    await call.answer()


@dp.callback_query(F.data.startswith("op_edit:"))
async def op_edit_start(call: CallbackQuery, state: FSMContext):
    op_id = int(call.data.split(":")[1])
    await state.set_state(EditOpFlow.new_reason)
    await state.update_data(op_id=op_id)
    await call.message.edit_text("Введите новое примечание для операции:")
    await call.answer()


@dp.message(EditOpFlow.new_reason)
async def op_edit_input(message: Message, state: FSMContext):
    data = await state.get_data()
    op_id = data["op_id"]
    ok = update_operation_reason(op_id, uid(message), message.text.strip())
    await state.clear()
    if not ok:
        await message.answer("Операция не найдена.",
                             reply_markup=main_menu_kb())
        return
    await message.answer("✅ Примечание обновлено.",
                         reply_markup=main_menu_kb())


@dp.callback_query(F.data.startswith("op_del:"))
async def op_del(call: CallbackQuery, state: FSMContext):
    op_id = int(call.data.split(":")[1])
    await call.message.edit_text(
        f"🗑 Удалить операцию #{op_id}?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да",
                                  callback_data=f"op_del_yes:{op_id}")],
            [InlineKeyboardButton(text="❌ Нет",
                                  callback_data=f"op_view:{op_id}")]]))
    await call.answer()


@dp.callback_query(F.data.startswith("op_del_yes:"))
async def op_del_yes(call: CallbackQuery, state: FSMContext):
    op_id = int(call.data.split(":")[1])
    delete_operation(op_id, uid(call))
    await call.message.edit_text("✅ Операция удалена.")
    await call.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await call.answer()


# ============================================================
#               ПОИСК ОПЕРАЦИИ
# ============================================================
@dp.message(F.text == "🔎 Найти операцию")
async def find_op_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(FindOpFlow.number)
    await message.answer(
        "Введите номер операции, например <code>Т:00001</code> "
        "или <code>З:00001</code>:",
        parse_mode="HTML")


@dp.message(FindOpFlow.number)
async def find_op_input(message: Message, state: FSMContext):
    raw = message.text.strip().upper()
    if not raw.startswith(("Т:", "З:")):
        await message.answer("❗ Номер должен начинаться с Т: или З:.")
        return
    op = get_operation_by_number(uid(message), raw)
    await state.clear()
    if not op:
        await message.answer(f"Операция {raw} не найдена.",
                             reply_markup=main_menu_kb())
        return
    op_id, kind, number, total, reason, created = op
    icon = "💰" if kind == "income" else "💸"
    lines = [
        f"{icon} <b>{number}</b>",
        f"Сумма: <b>{total:g}</b> ₽",
        f"Дата: {created[:16]}",
        f"Причина: {reason}",
    ]
    if kind == "expense":
        items = get_operation_items(op_id)
        if items:
            lines.append("")
            lines.append("Позиции:")
            for amt, rsn in items:
                lines.append(f"  • {amt:g} ₽ — {rsn}")
    await message.answer("\n".join(lines), parse_mode="HTML",
                         reply_markup=op_card_kb(op_id))


# ============================================================
#               ПОСЛЕДНИЕ ОПЕРАЦИИ
# ============================================================
@dp.message(F.text == "🕓 Последние операции")
async def last_ops(message: Message, state: FSMContext):
    await state.clear()
    rows = get_last_operations(uid(message), 10)
    if not rows:
        await message.answer("Пока нет операций.",
                             reply_markup=main_menu_kb())
        return
    lines = ["🕓 <b>Последние 10 операций</b>\n"]
    for op_id, kind, number, total, reason, created in rows:
        icon = "💰" if kind == "income" else "💸"
        lines.append(f"{icon} <b>{number}</b> | {total:g} ₽ | {created[:16]}")
        lines.append(f"   {reason}")
    await message.answer("\n".join(lines), parse_mode="HTML",
                         reply_markup=main_menu_kb())


# ============================================================
#               СТАТИСТИКА
# ============================================================
@dp.message(F.text == "📊 Статистика")
async def stats_menu(message: Message, state: FSMContext):
    await state.clear()
    months = get_months(uid(message))
    if not months:
        await message.answer("Пока нет данных.",
                             reply_markup=main_menu_kb())
        return
    buttons = [[InlineKeyboardButton(
        text=f"{m.split('-')[1]}.{m.split('-')[0]}",
        callback_data=f"stats:{m}")] for m in months]
    await message.answer("Выберите месяц:",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.callback_query(F.data.startswith("stats:"))
async def stats_show(call: CallbackQuery, state: FSMContext):
    month = call.data.split(":", 1)[1]
    user_id = uid(call)
    totals = get_month_totals(user_id, month)

    y, m = map(int, month.split("-"))
    if m == 1:
        prev_month = f"{y-1}-12"
    else:
        prev_month = f"{y}-{m-1:02d}"
    prev_totals = get_month_totals(user_id, prev_month)

    def diff_str(cur, prev):
        if prev == 0:
            if cur == 0:
                return "—"
            return f"{cur:g} ₽ (в прошлом периоде не было)"
        d = cur - prev
        pct = d / prev * 100
        arrow = "🔺" if d > 0 else ("🔻" if d < 0 else "➖")
        return f"{arrow} {pct:+.1f}% (было {prev:g} ₽)"

    top = get_top_expense_reasons(user_id, month, 5)

    lines = [f"📊 <b>Статистика за {month}</b>\n"]
    lines.append(f"💰 Зачисления: <b>{totals['income']:g}</b> ₽")
    lines.append(f"   {diff_str(totals['income'], prev_totals['income'])}")
    lines.append(f"💸 Траты: <b>{totals['expense']:g}</b> ₽")
    lines.append(f"   {diff_str(totals['expense'], prev_totals['expense'])}")
    balance = totals["income"] - totals["expense"]
    lines.append(f"📊 Баланс: <b>{balance:g}</b> ₽")

    if top:
        lines.append("")
        lines.append("🏆 <b>Топ-5 причин трат:</b>")
        for rsn, s in top:
            lines.append(f"  • {rsn}: <b>{s:g}</b> ₽")

    await call.message.edit_text("\n".join(lines), parse_mode="HTML",
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                     [InlineKeyboardButton(text="⬅️ В меню",
                                                           callback_data="view:menu")]]))
    await call.answer()


# ============================================================
#               ОТЧЁТ ЗА МЕСЯЦ (общий)
# ============================================================
@dp.message(F.text == "📅 Отчёт за месяц")
async def month_report_main(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "📅 <b>Отчёт за месяц</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🆕 Сформировать за месяц",
                                  callback_data="mreport:create")],
            [InlineKeyboardButton(text="📜 История отчётов",
                                  callback_data="mreport:history")],
        ]))


# ============================================================
#               АВТООТЧЁТ 30-го ЧИСЛА
# ============================================================
async def auto_month_reports():
    from datetime import timezone
    now = datetime.now(timezone.utc) + timedelta(hours=3)
    if now.day != 30:
        return
    month = now.strftime("%Y-%m")
    for user_id in get_auto_report_users():
        if was_auto_report_sent(user_id, month):
            continue
        try:
            totals = get_month_totals(user_id, month)
            spent = totals["expense"]
            saved = get_system_goal_current(user_id, SAVED_BUDGET_NAME)
            earned = get_system_goal_current(user_id, FUTURE_BUDGET_NAME)
            save_monthly_report(user_id, month, spent, earned, saved)

            tg_id = get_tg_by_user_id(user_id)
            if tg_id:
                text = (
                    f"📅 <b>Автоотчёт за {month}</b>\n\n"
                    f"💸 Потрачено: <b>{spent:g}</b> ₽\n"
                    f"💰 Заработано: <b>{earned:g}</b> ₽\n"
                    f"🏦 Отложено: <b>{saved:g}</b> ₽"
                )
                try:
                    await bot.send_message(tg_id, text, parse_mode="HTML")
                except Exception as e:
                    logging.warning(f"Не отправить автоотчёт {user_id}: {e}")
            mark_auto_report_sent(user_id, month)
        except Exception as e:
            logging.warning(f"Ошибка автоотчёта {user_id}: {e}")


# ============================================================
#                     ЗАПУСК
# ============================================================
async def main():
    init_db()
    init_shift_tables()

    scheduler.add_job(auto_month_reports, "cron", minute="0")
    scheduler.start()

    print("Бот запущен...")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
