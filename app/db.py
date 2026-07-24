"""
БД на SQLite: торговые точки (tenants) и связанные с ними заказы.

Почему БД, а не переменные окружения:
- Несколько торговых точек, добавляемых вручную — не хотим раздувать Variables.
- Чувствительные поля (пароль банка, секрет Tilda) хранятся зашифрованными
  (см. app/crypto.py) — ключ шифрования лежит отдельно, в ENCRYPTION_KEY.
- Заказы (order_id/password/сумма) переживают перезапуск контейнера — раньше
  они жили только в памяти процесса и терялись при каждом деплое.

ВАЖНО про Railway: контейнер эфемерный, файл БД должен лежать на
подключённом Volume (Settings → Volumes), иначе данные пропадут при
следующем деплое. См. tilda-integration/multi-tenant.md.
"""
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import HOSTS, get_settings
from .crypto import decrypt, encrypt


@dataclass
class Tenant:
    shop_id: str
    bank_env: str
    bank_owner_type: str
    bank_login: str
    bank_password: str
    bank_terminal_id: str
    tilda_login: str
    tilda_order_secret: str
    tilda_notify_url: str
    tilda_success_url: str = ""
    tilda_fail_url: str = ""
    # Нужен банку в каждом запросе с чеком (не имеет дефолта от банка).
    inn: str = ""
    # Информационные поля — не участвуют в запросах к банку, только для
    # удобства идентификации точки в админ-панели и CLI.
    merchant_name: str = ""
    terminal_number: str = ""

    @property
    def api_host(self) -> str:
        return HOSTS[self.bank_env]["api"]

    @property
    def flex_host(self) -> str:
        return HOSTS[self.bank_env]["flex"]

    @property
    def basic_auth_header(self) -> str:
        import base64

        raw = f"{self.bank_owner_type}/{self.bank_login}:{self.bank_password}"
        token = base64.b64encode(raw.encode("utf-8")).decode("ascii")
        return f"Basic {token}"


@contextmanager
def _conn():
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                shop_id TEXT PRIMARY KEY,
                bank_env TEXT NOT NULL DEFAULT 'test',
                bank_owner_type TEXT NOT NULL DEFAULT 'MultiMerchant',
                bank_login TEXT NOT NULL,
                bank_password_enc TEXT NOT NULL,
                bank_terminal_id TEXT NOT NULL,
                tilda_login TEXT NOT NULL,
                tilda_order_secret_enc TEXT NOT NULL,
                tilda_notify_url TEXT NOT NULL,
                tilda_success_url TEXT NOT NULL DEFAULT '',
                tilda_fail_url TEXT NOT NULL DEFAULT '',
                inn TEXT NOT NULL DEFAULT '',
                merchant_name TEXT NOT NULL DEFAULT '',
                terminal_number TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        # На случай, если БД была создана более ранней версией без этих колонок.
        # (tax_system_code, default_tax_rate, default_item_type, default_calc_mode
        # сюда сознательно не входят — эти поля больше не используются в коде;
        # в старых БД колонки могут остаться, это безвредно, просто больше не
        # читаются и не пишутся.)
        for col, default in (
            ("inn", ""),
            ("merchant_name", ""),
            ("terminal_number", ""),
        ):
            try:
                conn.execute(f"ALTER TABLE tenants ADD COLUMN {col} TEXT NOT NULL DEFAULT '{default}'")
            except sqlite3.OperationalError:
                pass  # колонка уже существует

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                bank_order_id INTEGER PRIMARY KEY,
                shop_id TEXT NOT NULL,
                password TEXT NOT NULL,
                amount REAL NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tilda_links (
                tilda_order_id TEXT PRIMARY KEY,
                shop_id TEXT NOT NULL,
                bank_order_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                notified INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        try:
            conn.execute("ALTER TABLE tilda_links ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # колонка уже существует


# ---------- Торговые точки ----------

def add_tenant(
    shop_id: str,
    bank_login: str,
    bank_password: str,
    bank_terminal_id: str,
    tilda_login: str,
    tilda_order_secret: str,
    tilda_notify_url: str,
    bank_env: str = "test",
    bank_owner_type: str = "MultiMerchant",
    tilda_success_url: str = "",
    tilda_fail_url: str = "",
    inn: str = "",
    merchant_name: str = "",
    terminal_number: str = "",
) -> None:
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO tenants (
                shop_id, bank_env, bank_owner_type, bank_login, bank_password_enc,
                bank_terminal_id, tilda_login, tilda_order_secret_enc, tilda_notify_url,
                tilda_success_url, tilda_fail_url, inn, merchant_name, terminal_number,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(shop_id) DO UPDATE SET
                bank_env=excluded.bank_env,
                bank_owner_type=excluded.bank_owner_type,
                bank_login=excluded.bank_login,
                bank_password_enc=excluded.bank_password_enc,
                bank_terminal_id=excluded.bank_terminal_id,
                tilda_login=excluded.tilda_login,
                tilda_order_secret_enc=excluded.tilda_order_secret_enc,
                tilda_notify_url=excluded.tilda_notify_url,
                tilda_success_url=excluded.tilda_success_url,
                tilda_fail_url=excluded.tilda_fail_url,
                inn=excluded.inn,
                merchant_name=excluded.merchant_name,
                terminal_number=excluded.terminal_number
            """,
            (
                shop_id,
                bank_env,
                bank_owner_type,
                bank_login,
                encrypt(bank_password),
                bank_terminal_id,
                tilda_login,
                encrypt(tilda_order_secret),
                tilda_notify_url,
                tilda_success_url,
                tilda_fail_url,
                inn,
                merchant_name,
                terminal_number,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def get_tenant(shop_id: str) -> Tenant | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM tenants WHERE shop_id = ?", (shop_id,)).fetchone()
    if row is None:
        return None
    return Tenant(
        shop_id=row["shop_id"],
        bank_env=row["bank_env"],
        bank_owner_type=row["bank_owner_type"],
        bank_login=row["bank_login"],
        bank_password=decrypt(row["bank_password_enc"]),
        bank_terminal_id=row["bank_terminal_id"],
        tilda_login=row["tilda_login"],
        tilda_order_secret=decrypt(row["tilda_order_secret_enc"]),
        tilda_notify_url=row["tilda_notify_url"],
        tilda_success_url=row["tilda_success_url"] or "",
        tilda_fail_url=row["tilda_fail_url"] or "",
        inn=row["inn"] or "",
        merchant_name=row["merchant_name"] or "",
        terminal_number=row["terminal_number"] or "",
    )


def list_tenants() -> list[str]:
    with _conn() as conn:
        rows = conn.execute("SELECT shop_id FROM tenants ORDER BY shop_id").fetchall()
    return [r["shop_id"] for r in rows]


def delete_tenant(shop_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM tenants WHERE shop_id = ?", (shop_id,))


# ---------- Заказы ----------

def save_order(shop_id: str, bank_order_id: int, password: str, amount: float) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO orders (bank_order_id, shop_id, password, amount, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (bank_order_id, shop_id, password, amount, datetime.now(timezone.utc).isoformat()),
        )


def get_order(bank_order_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM orders WHERE bank_order_id = ?", (bank_order_id,)).fetchone()
    return dict(row) if row else None


def save_tilda_link(tilda_order_id: str, shop_id: str, bank_order_id: int, amount: float) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO tilda_links (tilda_order_id, shop_id, bank_order_id, amount, notified, created_at) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (tilda_order_id, shop_id, bank_order_id, amount, datetime.now(timezone.utc).isoformat()),
        )


def get_tilda_link(tilda_order_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM tilda_links WHERE tilda_order_id = ?", (tilda_order_id,)
        ).fetchone()
    return dict(row) if row else None


def mark_tilda_link_notified(tilda_order_id: str) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE tilda_links SET notified = 1 WHERE tilda_order_id = ?", (tilda_order_id,)
        )


def list_unnotified_tilda_links(max_age_hours: float = 0.5) -> list[dict]:
    """
    Заказы, по которым ещё не отправлено уведомление об оплате в Tilda —
    используется фоновой проверкой (см. app.main:poll_pending_payments),
    чтобы не зависеть от того, вернётся ли покупатель в браузере после оплаты.
    Старше max_age_hours (по умолчанию 30 минут) не возвращаются — такие
    заказы уже почти наверняка просрочены на стороне банка, нет смысла
    бесконечно их опрашивать.
    """
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tilda_links WHERE notified = 0 AND created_at != '' ORDER BY created_at"
        ).fetchall()
    cutoff = datetime.now(timezone.utc).timestamp() - max_age_hours * 3600
    result = []
    for r in rows:
        try:
            created_ts = datetime.fromisoformat(r["created_at"]).timestamp()
        except ValueError:
            created_ts = 0
        if created_ts >= cutoff:
            result.append(dict(r))
    return result
