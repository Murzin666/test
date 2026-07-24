import asyncio
import json
import logging

import httpx
from fastapi import Depends, FastAPI, Form, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from . import admin, bank_client, db
from .bank_client import BankApiError
from .config import get_settings
from .ffd_mapping import PAYMENT_METHOD_TO_MODE, PAYMENT_OBJECT_TO_TYPE, TAXATION_TO_TAX_SYSTEM_CODE, TAX_TO_TAX_RATE_BY_OFD
from .tilda_signature import compute_signature, verify_signature

logger = logging.getLogger("bank_proxy")

settings = get_settings()

app = FastAPI(title="Эквайринг Центр-инвест — сервер-посредник для Tilda (мультитенантный)")

app.include_router(admin.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Admin-Key"],
)


@app.on_event("startup")
async def on_startup():
    db.init_db()
    asyncio.create_task(poll_pending_payments())


def require_admin(x_admin_key: str = Header(default="")) -> None:
    """Простая защита для операций возврата/отмены — не открывайте их публично на Tilda."""
    if not settings.admin_api_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий X-Admin-Key")


def _get_tenant_or_404(url_tilda: str) -> db.Tenant:
    tenant = db.get_tenant(url_tilda)
    if tenant is None:
        raise HTTPException(status_code=404, detail=f"Неизвестная торговая точка: {url_tilda}")
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

def _fiscal_code(value):
    """Коды банка (taxRate/type/mode) для ОФД Orange Data — целые числа;
    для ОФД БИФИТ Онлайн — строки (VAT_20 и т.п.). Приводим к int, если
    значение чисто числовое, иначе оставляем строкой как есть."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _build_receipt(
    tenant: db.Tenant,
    url_tilda: str,
    products_json: str,
    tilda_receipt_json: str,
    amount: float,
) -> dict | None:
    """
    Собирает блок receipt для запроса в банк.

    Источник атрибутов (taxRate/type/mode) на каждый товар — автоматическое
    поле "Receipt", которое Tilda сама добавляет в запрос, если у товара
    заполнена вкладка "НДС, ФФД" в карточке (переводим её словарь в коды
    банка через app.ffd_mapping). Если для конкретного товара или атрибута
    данных нет или их не удалось сопоставить — это поле просто НЕ включается
    в позицию чека: мы не подставляем своё значение вместо того, что
    предполагал продавец, банк применит свой собственный дефолт для
    терминала (как было до появления этой логики).

    Если у точки не указан ИНН — чек вообще не формируется: банк требует
    ИНН в каждом запросе с чеком, дефолта для него нет.
    """
    if not tenant.inn:
        logger.warning("url_tilda=%s: ИНН не задан, чек для банка не формируется", url_tilda)
        return None

    try:
        products = json.loads(products_json or "[]")
    except (TypeError, ValueError):
        logger.warning("url_tilda=%s: не удалось разобрать products от Tilda: %r", url_tilda, products_json)
        products = []

    try:
        tilda_receipt = json.loads(tilda_receipt_json or "{}")
    except (TypeError, ValueError):
        tilda_receipt = {}

    tilda_items_list = tilda_receipt.get("items", []) if isinstance(tilda_receipt, dict) else []

    # taxSystemCode передаём банку только если Tilda прислала taxation и он
    # успешно сопоставился с кодом банка. Если нет — поле вообще не кладём
    # в receipt, банк сам подставит СНО, зарегистрированную на терминале.
    taxation = tilda_receipt.get("taxation") if isinstance(tilda_receipt, dict) else None
    tax_system_code = None
    if taxation:
        tax_system_code = TAXATION_TO_TAX_SYSTEM_CODE.get(taxation)
        if tax_system_code is None:
            logger.warning(
                "url_tilda=%s: система налогообложения %r от Tilda не распознана — taxSystemCode не отправляем, "
                "банк подставит сам",
                url_tilda, taxation,
            )
        else:
            logger.warning(
                "url_tilda=%s: Tilda сообщила систему налогообложения %r — отправляем банку код %s",
                url_tilda, taxation, tax_system_code,
            )

    items = []
    for idx, p in enumerate(products):
        name = str(p.get("name", "")).strip()
        try:
            quantity = float(p.get("quantity", 1) or 1)
        except (TypeError, ValueError):
            quantity = 1.0
        try:
            price = float(p.get("price", 0) or 0)
        except (TypeError, ValueError):
            price = 0.0
        if price == 0 and quantity:
            try:
                price = float(p.get("total_price", 0) or 0) / quantity
            except (TypeError, ValueError, ZeroDivisionError):
                price = 0.0

        tilda_item = tilda_items_list[idx] if idx < len(tilda_items_list) else None
        mapped_tax = mapped_type = mapped_mode = None
        if tilda_item is not None:
            tilda_name = str(tilda_item.get("name", "")).strip()
            if tilda_name and name and not tilda_name.startswith(name):
                # Название в Receipt обычно совпадает с products, но для
                # товаров с вариантами (цвет/размер) Tilda дописывает к
                # нему опции ("Apples, Color=Green apples") — это ожидаемо
                # и не повод считать сопоставление ошибочным. Предупреждаем
                # только если названия разошлись сильнее, чем просто
                # добавленный вариант, — вдруг реально другой порядок.
                logger.warning(
                    "url_tilda=%s: позиция %d — название в Receipt (%r) заметно отличается "
                    "от названия в products (%r), проверьте порядок товаров",
                    url_tilda, idx, tilda_name, name,
                )
            tax_rate_table = TAX_TO_TAX_RATE_BY_OFD.get(tenant.ofd_provider, TAX_TO_TAX_RATE_BY_OFD["orange_data"])
            mapped_tax = tax_rate_table.get(tilda_item.get("tax"))
            mapped_type = PAYMENT_OBJECT_TO_TYPE.get(tilda_item.get("payment_object"))
            mapped_mode = PAYMENT_METHOD_TO_MODE.get(tilda_item.get("payment_method"))

        # Если что-то не удалось определить из данных Tilda — НЕ подставляем
        # своё значение и не отправляем это поле банку вообще. Так честнее:
        # банк применит свой собственный дефолт, зарегистрированный на
        # терминале, а не наше предположение, которое может не совпасть с
        # тем, что реально имел в виду продавец.
        if mapped_tax is None:
            logger.warning(
                "url_tilda=%s: товар %r — ставка НДС не определена из данных Tilda, "
                "поле taxRate не отправляется, банк применит свой дефолт терминала",
                url_tilda, name,
            )
        if mapped_type is None:
            logger.warning(
                "url_tilda=%s: товар %r — предмет расчёта не определён из данных Tilda, "
                "поле type не отправляется, банк применит свой дефолт терминала",
                url_tilda, name,
            )
        if mapped_mode is None:
            logger.warning(
                "url_tilda=%s: товар %r — способ расчёта не определён из данных Tilda, "
                "поле mode не отправляется, банк применит свой дефолт терминала",
                url_tilda, name,
            )

        item = {
            "desc": name or "Товар",
            "quantity": quantity,
            "price": round(price, 2),
        }
        if mapped_tax is not None:
            item["taxRate"] = _fiscal_code(mapped_tax)
        if mapped_type is not None:
            item["type"] = _fiscal_code(mapped_type)
        if mapped_mode is not None:
            item["mode"] = _fiscal_code(mapped_mode)
        items.append(item)

    if not items:
        # Состав корзины не пришёл или не распарсился — не отправляем банку
        # пустой/битый чек, лучше вообще без receipt (сработают дефолты банка).
        logger.warning("url_tilda=%s: нет позиций для чека, receipt не отправляется", url_tilda)
        return None

    receipt = {
        "items": items,
        "payments": [{"type": 1, "amt": round(amount, 2)}],
        "taxRid": tenant.inn,
    }
    if tax_system_code is not None:
        receipt["taxSystemCode"] = _fiscal_code(tax_system_code)
    return receipt


@app.post("/tilda/{url_tilda}/checkout")
async def tilda_checkout(
    url_tilda: str,
    login: str = Form(...),
    order_id: str = Form(...),
    order_amount: str = Form(...),
    signature: str = Form(...),
    client_email: str = Form(""),
    products: str = Form("[]"),
    tilda_receipt: str = Form("{}", alias="Receipt"),
):
    """
    Сюда Tilda перенаправляет браузер покупателя (POST) сразу после
    оформления заказа в корзине КОНКРЕТНОЙ торговой точки url_tilda —
    именно этот адрес указывается в поле "API URL" при настройке
    Универсальной платёжной системы у данного клиента.
    """
    tenant = _get_tenant_or_404(url_tilda)

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
        "typeRid": tenant.type_rid,
        "amount": f"{amount:.2f}",
        "currency": "RUB",
        "description": f"Заказ Tilda #{order_id}",
        "language": "ru",
        "hppRedirectUrl": f"{settings.public_base_url}/tilda/{url_tilda}/return?ref={order_id}",
    }
    if client_email:
        order_payload["srcEmail"] = client_email

    receipt = _build_receipt(tenant, url_tilda, products, tilda_receipt, amount)
    if receipt is not None:
        order_payload["receipt"] = receipt

    order = await bank_client.create_order(tenant, session_id, order_payload)
    bank_order_id = order["order"]["id"]
    password = order["order"]["password"]

    db.save_order(url_tilda, bank_order_id, password, amount)
    db.save_tilda_link(order_id, url_tilda, bank_order_id, amount)

    pay_url = f"{tenant.flex_host}?id={bank_order_id}&password={password}"
    return RedirectResponse(pay_url, status_code=302)


async def _notify_tilda_paid(tenant: db.Tenant, tilda_order_id: str, bank_order_id: int, amount: float) -> bool:
    """
    Отправляет Tilda уведомление об успешной оплате. Используется и из
    /tilda/{url_tilda}/return (когда покупатель вернулся в браузере), и из
    фонового опроса poll_pending_payments (на случай, если не вернулся).
    Возвращает True, если уведомление отправлено и БД обновлена.
    """
    amount_str = f"{amount:.2f}"
    sig = compute_signature(tenant.tilda_order_secret, tenant.tilda_login, tilda_order_id, amount_str)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                tenant.tilda_notify_url,
                data={
                    "login": tenant.tilda_login,
                    "order_id": tilda_order_id,
                    "order_amount": amount_str,
                    "paid": "1",
                    "transaction_id": str(bank_order_id),
                    "signature": sig,
                },
            )
        db.mark_tilda_link_notified(tilda_order_id)
        return True
    except httpx.RequestError as exc:
        logger.warning("url_tilda=%s: не удалось отправить уведомление Tilda по заказу %s: %s",
                        tenant.url_tilda, tilda_order_id, exc)
        return False


POLL_INTERVAL_SECONDS = 120


async def poll_pending_payments():
    """
    Фоновая проверка: раз в POLL_INTERVAL_SECONDS обходит все заказы без
    отправленного уведомления в Tilda и сам спрашивает у банка статус —
    не полагаясь на то, вернётся ли покупатель в браузере после оплаты.
    """
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        try:
            pending = db.list_unnotified_tilda_links()
        except Exception as exc:
            logger.warning("poll_pending_payments: ошибка чтения БД: %s", exc)
            continue

        for link in pending:
            url_tilda = link["url_tilda"]
            try:
                tenant = _get_tenant_or_404(url_tilda)
                order = db.get_order(link["bank_order_id"])
                if order is None:
                    continue
                result = await bank_client.get_order_status(tenant, link["bank_order_id"], order["password"])
                status = result["order"]["status"]
                if status == "FullyPaid":
                    ok = await _notify_tilda_paid(tenant, link["tilda_order_id"], link["bank_order_id"], link["amount"])
                    if ok:
                        logger.warning("poll_pending_payments: заказ %s (url_tilda=%s) оплачен, Tilda уведомлена",
                                        link["tilda_order_id"], url_tilda)
            except Exception as exc:
                logger.warning("poll_pending_payments: ошибка по заказу %s (url_tilda=%s): %s",
                                link["tilda_order_id"], url_tilda, exc)


@app.get("/tilda/{url_tilda}/return")
async def tilda_return(url_tilda: str, ref: str):
    """Сюда банк возвращает покупателя после оплаты (hppRedirectUrl)."""
    tenant = _get_tenant_or_404(url_tilda)

    link = db.get_tilda_link(ref)
    if link is None or link["url_tilda"] != url_tilda:
        return PlainTextResponse("Заказ не найден", status_code=404)

    order = db.get_order(link["bank_order_id"])
    if order is None:
        return PlainTextResponse("Заказ не найден", status_code=404)

    result = await bank_client.get_order_status(tenant, link["bank_order_id"], order["password"])
    status = result["order"]["status"]

    if status == "FullyPaid" and not link["notified"]:
        await _notify_tilda_paid(tenant, ref, link["bank_order_id"], link["amount"])

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

@app.get("/api/{url_tilda}/orders/{order_id}/status", dependencies=[Depends(require_admin)])
async def get_status(url_tilda: str, order_id: int, with_ofd: bool = False):
    tenant = _get_tenant_or_404(url_tilda)
    order = db.get_order(order_id)
    if order is None or order["url_tilda"] != url_tilda:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    return await bank_client.get_order_status(tenant, order_id, order["password"], with_ofd=with_ofd)


@app.post("/api/{url_tilda}/orders/{order_id}/refund", dependencies=[Depends(require_admin)])
async def refund_order(url_tilda: str, order_id: int, amount: float):
    tenant = _get_tenant_or_404(url_tilda)
    order = db.get_order(order_id)
    if order is None or order["url_tilda"] != url_tilda:
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


@app.post("/api/{url_tilda}/orders/{order_id}/void", dependencies=[Depends(require_admin)])
async def void_paid_order(url_tilda: str, order_id: int):
    tenant = _get_tenant_or_404(url_tilda)
    order = db.get_order(order_id)
    if order is None or order["url_tilda"] != url_tilda:
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
