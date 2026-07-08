"""
Тонкая обёртка над API банка "Центр-инвест".
Все функции принимают tenant (app.db.Tenant) — настройки конкретной
торговой точки (какой банковский аккаунт и терминал использовать).
"""
import httpx

from .db import Tenant


class BankApiError(Exception):
    """Прокидывается наверх с тем же смыслом кода, что вернул банк."""

    def __init__(self, status_code: int, message: str, payload: dict | None = None):
        self.status_code = status_code
        self.message = message
        self.payload = payload or {}
        super().__init__(message)


def _headers(tenant: Tenant, session_id: str | None = None) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Authorization": tenant.basic_auth_header,
    }
    if session_id:
        headers["TXPG-User-Session-ID"] = session_id
    return headers


async def _request(tenant: Tenant, method: str, path: str, **kwargs) -> dict:
    url = f"{tenant.api_host}{path}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.request(method, url, **kwargs)
        except httpx.RequestError as exc:
            raise BankApiError(502, f"Банк недоступен: {exc}") from exc

    if resp.status_code >= 400:
        try:
            payload = resp.json()
        except ValueError:
            payload = {"raw": resp.text}
        raise BankApiError(resp.status_code, "Ошибка банка", payload)

    return resp.json()


async def create_user_session(tenant: Tenant, browser_info: dict) -> dict:
    """POST /psp/create-user-session — возвращает sessionId."""
    return await _request(
        tenant,
        "POST",
        "/psp/create-user-session",
        headers=_headers(tenant),
        json={"browserInfo": browser_info},
    )


async def create_order(tenant: Tenant, session_id: str, order_payload: dict) -> dict:
    """POST /order?terminalId=... — создаёт заказ, возвращает id/password/hppUrl."""
    return await _request(
        tenant,
        "POST",
        f"/order?terminalId={tenant.bank_terminal_id}",
        headers=_headers(tenant, session_id),
        json={"order": order_payload},
    )


async def get_order_status(tenant: Tenant, order_id: int, password: str, with_ofd: bool = False) -> dict:
    """GET /order/{id}?password=... — статус заказа."""
    path = f"/order/{order_id}?password={password}"
    if with_ofd:
        path += "&tranDetailLevel=2"
    return await _request(tenant, "GET", path, headers=_headers(tenant))


async def exec_tran(tenant: Tenant, session_id: str, order_id: int, password: str, tran_payload: dict) -> dict:
    """POST /order/{id}/exec-tran — реверс (void) уже прошедшей оплаты в тот же день."""
    return await _request(
        tenant,
        "POST",
        f"/order/{order_id}/exec-tran?password={password}",
        headers=_headers(tenant, session_id),
        json={"tran": tran_payload},
    )
