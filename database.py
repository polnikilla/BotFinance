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
