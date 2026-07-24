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
    url_tilda: str
    bank_env: str
    bank_owner_type: str
    tsp_login: str
    tsp_password: str
    bank_terminal_id: str
    tilda_login: str
    tilda_order_secret: str
    tilda_notify_url: str
    tilda_success_url: str = ""
    tilda_fail_url: str = ""
    # Нужен банку в каждом запросе с чеком (не имеет дефолта от банка).
    inn: str = ""
    # Тип заказа (typeRid) — определяет способ оплаты/тип операции в банке.
    # Раньше был захардкожен как "56" на все точки — клиент (Tilda) его не
    # передаёт вообще, поэтому это настройка конкретной точки, выданная банком.
    type_rid: str = "56"
    # Какой ОФД подключён к терминалу точки — влияет на формат кода ставки
    # НДС (taxRate): Orange Data — числа, БИФИТ Онлайн — строковые теги.
    # См. app/ffd_mapping.py:TAX_TO_TAX_RATE_BY_OFD.
    ofd_provider: str = "orange_data"
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

        raw = f"{self.bank_owner_type}/{self.tsp_login}:{self.tsp_password}"
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
                url_tilda TEXT PRIMARY KEY,
                bank_env TEXT NOT NULL DEFAULT 'test',
                bank_owner_type TEXT NOT NULL DEFAULT 'MultiMerchant',
                tsp_login TEXT NOT NULL,
                tsp_password_enc TEXT NOT NULL,
                bank_terminal_id TEXT NOT NULL,
                tilda_login TEXT NOT NULL,
                tilda_order_secret_enc TEXT NOT NULL,
                tilda_notify_url TEXT NOT NULL,
                tilda_success_url TEXT NOT NULL DEFAULT '',
                tilda_fail_url TEXT NOT NULL DEFAULT '',
                inn TEXT NOT NULL DEFAULT '',
                merchant_name TEXT NOT NULL DEFAULT '',
                terminal_number TEXT NOT NULL DEFAULT '',
                type_rid TEXT NOT NULL DEFAULT '56',
                ofd_provider TEXT NOT NULL DEFAULT 'orange_data',
                created_at TEXT NOT NULL
            )
            """
        )
        # Переименование старых колонок в БД, созданной более ранней версией
        # кода (bank_login/bank_password_enc -> tsp_login/tsp_password_enc).
        # На новой, только что созданной БД эти колонки уже называются
        # правильно, и попытка переименования просто ничего не найдёт —
        # ошибка перехватывается и игнорируется.
        for old_col, new_col in (
            ("bank_login", "tsp_login"),
            ("bank_password_enc", "tsp_password_enc"),
            ("shop_id", "url_tilda"),
        ):
            try:
                conn.execute(f"ALTER TABLE tenants RENAME COLUMN {old_col} TO {new_col}")
            except sqlite3.OperationalError:
                pass  # колонка уже переименована или изначально называлась иначе

        # На случай, если БД была создана более ранней версией без этих колонок.
        # (tax_system_code, default_tax_rate, default_item_type, default_calc_mode
        # сюда сознательно не входят — эти поля больше не используются в коде;
        # в старых БД колонки могут остаться, это безвредно, просто больше не
        # читаются и не пишутся.)
        for col, default in (
            ("inn", ""),
            ("merchant_name", ""),
            ("terminal_number", ""),
            ("type_rid", "56"),
            ("ofd_provider", "orange_data"),
        ):
            try:
                conn.execute(f"ALTER TABLE tenants ADD COLUMN {col} TEXT NOT NULL DEFAULT '{default}'")
            except sqlite3.OperationalError:
                pass  # колонка уже существует

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                bank_order_id INTEGER PRIMARY KEY,
                url_tilda TEXT NOT NULL,
                password TEXT NOT NULL,
                amount REAL NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        try:
            conn.execute("ALTER TABLE orders RENAME COLUMN shop_id TO url_tilda")
        except sqlite3.OperationalError:
            pass  # колонка уже переименована или изначально называлась иначе

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tilda_links (
                tilda_order_id TEXT PRIMARY KEY,
                url_tilda TEXT NOT NULL,
                bank_order_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                notified INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        try:
            conn.execute("ALTER TABLE tilda_links RENAME COLUMN shop_id TO url_tilda")
        except sqlite3.OperationalError:
            pass  # колонка уже переименована или изначально называлась иначе
        try:
            conn.execute("ALTER TABLE tilda_links ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # колонка уже существует


# ---------- Торговые точки ----------

def add_tenant(
    url_tilda: str,
    tsp_login: str,
    tsp_password: str,
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
    type_rid: str = "56",
    ofd_provider: str = "orange_data",
) -> None:
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO tenants (
                url_tilda, bank_env, bank_owner_type, tsp_login, tsp_password_enc,
                bank_terminal_id, tilda_login, tilda_order_secret_enc, tilda_notify_url,
                tilda_success_url, tilda_fail_url, inn, merchant_name, terminal_number,
                type_rid, ofd_provider, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url_tilda) DO UPDATE SET
                bank_env=excluded.bank_env,
                bank_owner_type=excluded.bank_owner_type,
                tsp_login=excluded.tsp_login,
                tsp_password_enc=excluded.tsp_password_enc,
                bank_terminal_id=excluded.bank_terminal_id,
                tilda_login=excluded.tilda_login,
                tilda_order_secret_enc=excluded.tilda_order_secret_enc,
                tilda_notify_url=excluded.tilda_notify_url,
                tilda_success_url=excluded.tilda_success_url,
                tilda_fail_url=excluded.tilda_fail_url,
                inn=excluded.inn,
                merchant_name=excluded.merchant_name,
                terminal_number=excluded.terminal_number,
                type_rid=excluded.type_rid,
                ofd_provider=excluded.ofd_provider
            """,
            (
                url_tilda,
                bank_env,
                bank_owner_type,
                tsp_login,
                encrypt(tsp_password),
                bank_terminal_id,
                tilda_login,
                encrypt(tilda_order_secret),
                tilda_notify_url,
                tilda_success_url,
                tilda_fail_url,
                inn,
                merchant_name,
                terminal_number,
                type_rid,
                ofd_provider,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def get_tenant(url_tilda: str) -> Tenant | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM tenants WHERE url_tilda = ?", (url_tilda,)).fetchone()
    if row is None:
        return None
    return Tenant(
        url_tilda=row["url_tilda"],
        bank_env=row["bank_env"],
        bank_owner_type=row["bank_owner_type"],
        tsp_login=row["tsp_login"],
        tsp_password=decrypt(row["tsp_password_enc"]),
        bank_terminal_id=row["bank_terminal_id"],
        tilda_login=row["tilda_login"],
        tilda_order_secret=decrypt(row["tilda_order_secret_enc"]),
        tilda_notify_url=row["tilda_notify_url"],
        tilda_success_url=row["tilda_success_url"] or "",
        tilda_fail_url=row["tilda_fail_url"] or "",
        inn=row["inn"] or "",
        merchant_name=row["merchant_name"] or "",
        terminal_number=row["terminal_number"] or "",
        type_rid=row["type_rid"] or "56",
        ofd_provider=row["ofd_provider"] or "orange_data",
    )


def list_tenants() -> list[str]:
    with _conn() as conn:
        rows = conn.execute("SELECT url_tilda FROM tenants ORDER BY url_tilda").fetchall()
    return [r["url_tilda"] for r in rows]


def delete_tenant(url_tilda: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM tenants WHERE url_tilda = ?", (url_tilda,))


# ---------- Заказы ----------

def save_order(url_tilda: str, bank_order_id: int, password: str, amount: float) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO orders (bank_order_id, url_tilda, password, amount, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (bank_order_id, url_tilda, password, amount, datetime.now(timezone.utc).isoformat()),
        )


def get_order(bank_order_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM orders WHERE bank_order_id = ?", (bank_order_id,)).fetchone()
    return dict(row) if row else None


def save_tilda_link(tilda_order_id: str, url_tilda: str, bank_order_id: int, amount: float) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO tilda_links (tilda_order_id, url_tilda, bank_order_id, amount, notified, created_at) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (tilda_order_id, url_tilda, bank_order_id, amount, datetime.now(timezone.utc).isoformat()),
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
