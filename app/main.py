import httpx
from fastapi import Depends, FastAPI, Form, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from . import bank_client, db
from .bank_client import BankApiError
from .config import get_settings
from .tilda_signature import compute_signature, verify_signature

settings = get_settings()

app = FastAPI(title="Эквайринг Центр-инвест — сервер-посредник для Tilda (мультитенантный)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Admin-Key"],
)


@app.on_event("startup")
async def on_startup():
    db.init_db()


def require_admin(x_admin_key: str = Header(default="")) -> None:
    """Простая защита для операций возврата/отмены — не открывайте их публично на Tilda."""
    if not settings.admin_api_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий X-Admin-Key")


def _get_tenant_or_404(shop_id: str) -> db.Tenant:
    tenant = db.get_tenant(shop_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail=f"Неизвестная торговая точка: {shop_id}")
    return tenant


@app.exception_handler(BankApiError)
async def bank_error_handler(request, exc: BankApiError):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=exc.status_code if exc.status_code in (400, 401, 404, 409) else 502,
        content={"error": exc.message, "detail": exc.payload},
    )


@app.get("/api/health")
async def health():
    return {"ok": True, "tenants": db.list_tenants()}


# ---------- Универсальная платёжная система Tilda (по одному URL на точку) ----------

@app.post("/tilda/{shop_id}/checkout")
async def tilda_checkout(
    shop_id: str,
    login: str = Form(...),
    order_id: str = Form(...),
    order_amount: str = Form(...),
    signature: str = Form(...),
    client_email: str = Form(""),
):
    """
    Сюда Tilda перенаправляет браузер покупателя (POST) сразу после
    оформления заказа в корзине КОНКРЕТНОЙ торговой точки shop_id —
    именно этот адрес указывается в поле "API URL" при настройке
    Универсальной платёжной системы у данного клиента.
    """
    tenant = _get_tenant_or_404(shop_id)

    if not verify_signature(tenant.tilda_order_secret, login, order_id, order_amount, signature):
        raise HTTPException(status_code=400, detail="Неверная подпись заказа от Tilda")

    try:
        amount = round(float(order_amount), 2)
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректная сумма заказа")

    session = await bank_client.create_user_session(
        tenant, {"browserLanguage": "ru", "browserUserAgent": "tilda-checkout"}
    )
    session_id = session["sessionId"]

    order_payload = {
        "typeRid": "56",
        "amount": f"{amount:.2f}",
        "currency": "RUB",
        "description": f"Заказ Tilda #{order_id}",
        "language": "ru",
        "hppRedirectUrl": f"{settings.public_base_url}/tilda/{shop_id}/return?ref={order_id}",
    }
    if client_email:
        order_payload["srcEmail"] = client_email

    order = await bank_client.create_order(tenant, session_id, order_payload)
    bank_order_id = order["order"]["id"]
    password = order["order"]["password"]

    db.save_order(shop_id, bank_order_id, password, amount)
    db.save_tilda_link(order_id, shop_id, bank_order_id, amount)

    pay_url = f"{tenant.flex_host}?id={bank_order_id}&password={password}"
    return RedirectResponse(pay_url, status_code=302)


@app.get("/tilda/{shop_id}/return")
async def tilda_return(shop_id: str, ref: str):
    """Сюда банк возвращает покупателя после оплаты (hppRedirectUrl)."""
    tenant = _get_tenant_or_404(shop_id)

    link = db.get_tilda_link(ref)
    if link is None or link["shop_id"] != shop_id:
        return PlainTextResponse("Заказ не найден", status_code=404)

    order = db.get_order(link["bank_order_id"])
    if order is None:
        return PlainTextResponse("Заказ не найден", status_code=404)

    result = await bank_client.get_order_status(tenant, link["bank_order_id"], order["password"])
    status = result["order"]["status"]

    if status == "FullyPaid" and not link["notified"]:
        amount_str = f"{link['amount']:.2f}"
        sig = compute_signature(tenant.tilda_order_secret, tenant.tilda_login, ref, amount_str)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    tenant.tilda_notify_url,
                    data={
                        "login": tenant.tilda_login,
                        "order_id": ref,
                        "order_amount": amount_str,
                        "paid": "1",
                        "transaction_id": str(link["bank_order_id"]),
                        "signature": sig,
                    },
                )
            db.mark_tilda_link_notified(ref)
        except httpx.RequestError:
            pass

    if status == "FullyPaid":
        if tenant.tilda_success_url:
            return RedirectResponse(tenant.tilda_success_url, status_code=302)
        return HTMLResponse("<h1>Спасибо за заказ!</h1><p>Оплата прошла успешно.</p>")

    if status in ("Refused", "Rejected", "Cancelled", "Expired"):
        if tenant.tilda_fail_url:
            return RedirectResponse(tenant.tilda_fail_url, status_code=302)
        return HTMLResponse(
            "<h1>Оплата не прошла</h1>"
            "<p>Платёж был отклонён или отменён. Попробуйте оформить заказ ещё раз "
            "или свяжитесь с нами, если деньги списались.</p>"
        )

    return HTMLResponse("<h1>Оплата обрабатывается</h1><p>Обновите эту страницу через минуту.</p>")


# ---------- Служебные операции (для вашей админки, не для Tilda напрямую) ----------

@app.get("/api/{shop_id}/orders/{order_id}/status", dependencies=[Depends(require_admin)])
async def get_status(shop_id: str, order_id: int, with_ofd: bool = False):
    tenant = _get_tenant_or_404(shop_id)
    order = db.get_order(order_id)
    if order is None or order["shop_id"] != shop_id:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    return await bank_client.get_order_status(tenant, order_id, order["password"], with_ofd=with_ofd)


@app.post("/api/{shop_id}/orders/{order_id}/refund", dependencies=[Depends(require_admin)])
async def refund_order(shop_id: str, order_id: int, amount: float):
    tenant = _get_tenant_or_404(shop_id)
    order = db.get_order(order_id)
    if order is None or order["shop_id"] != shop_id:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    session = await bank_client.create_user_session(
        tenant, {"browserLanguage": "ru", "browserUserAgent": "backend-admin"}
    )
    return await bank_client.exec_tran(
        tenant,
        session["sessionId"],
        order_id,
        order["password"],
        {"type": "Refund", "amount": f"{amount:.2f}", "phase": "Single"},
    )


@app.post("/api/{shop_id}/orders/{order_id}/void", dependencies=[Depends(require_admin)])
async def void_paid_order(shop_id: str, order_id: int):
    tenant = _get_tenant_or_404(shop_id)
    order = db.get_order(order_id)
    if order is None or order["shop_id"] != shop_id:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    session = await bank_client.create_user_session(
        tenant, {"browserLanguage": "ru", "browserUserAgent": "backend-admin"}
    )
    return await bank_client.exec_tran(
        tenant,
        session["sessionId"],
        order_id,
        order["password"],
        {
            "type": "Purchase",
            "voidKind": "Full",
            "amount": f"{order['amount']:.2f}",
            "phase": "Single",
        },
    )
