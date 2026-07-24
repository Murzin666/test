"""
Веб-панель для управления торговыми точками — то же самое, что делает
manage_tenants.py, но через браузер. Защищена тем же ADMIN_API_KEY, что и
операции возврата/отмены (заголовок X-Admin-Key).

Секреты (пароль банка, секрет подписи Tilda) никогда не возвращаются в
API — только флаг "задан/не задан". Чтобы сменить секрет, нужно ввести
новое значение; чтобы оставить прежний — оставить поле пустым при
редактировании (при создании новой точки оба секрета обязательны).
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import db
from .config import get_settings

router = APIRouter()
settings = get_settings()


def require_admin(x_admin_key: str = Header(default="")) -> None:
    if not settings.admin_api_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий X-Admin-Key")


class TenantIn(BaseModel):
    tsp_login: str
    tsp_password: str = ""
    bank_terminal_id: str
    bank_owner_type: str = "MultiMerchant"
    bank_env: str = "test"
    tilda_secret: str = ""
    tilda_notify_url: str
    tilda_success_url: str
    tilda_fail_url: str
    inn: str = ""
    merchant_name: str
    terminal_number: str
    type_rid: str = "56"
    ofd_provider: str = "orange_data"


def _tenant_summary(tenant: db.Tenant) -> dict:
    return {
        "url_tilda": tenant.url_tilda,
        "bank_env": tenant.bank_env,
        "bank_owner_type": tenant.bank_owner_type,
        "tsp_login": tenant.tsp_login,
        "tsp_password_set": bool(tenant.tsp_password),
        "bank_terminal_id": tenant.bank_terminal_id,
        "tilda_login": tenant.tilda_login,
        "tilda_secret_set": bool(tenant.tilda_order_secret),
        "tilda_notify_url": tenant.tilda_notify_url,
        "tilda_success_url": tenant.tilda_success_url,
        "tilda_fail_url": tenant.tilda_fail_url,
        "inn": tenant.inn,
        "merchant_name": tenant.merchant_name,
        "terminal_number": tenant.terminal_number,
        "type_rid": tenant.type_rid,
        "ofd_provider": tenant.ofd_provider,
        "checkout_url": f"{settings.public_base_url}/tilda/{tenant.url_tilda}/checkout",
    }


@router.get("/admin/api/tenants", dependencies=[Depends(require_admin)])
async def list_tenants_api():
    return [_tenant_summary(db.get_tenant(url_tilda)) for url_tilda in db.list_tenants()]


@router.get("/admin/api/tenants/{url_tilda}", dependencies=[Depends(require_admin)])
async def get_tenant_api(url_tilda: str):
    tenant = db.get_tenant(url_tilda)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Точка не найдена")
    return _tenant_summary(tenant)


@router.put("/admin/api/tenants/{url_tilda}", dependencies=[Depends(require_admin)])
async def upsert_tenant_api(url_tilda: str, body: TenantIn):
    existing = db.get_tenant(url_tilda)

    tsp_password = body.tsp_password.strip()
    if not tsp_password:
        if existing is None:
            raise HTTPException(status_code=400, detail="Пароль ТСП обязателен для новой точки")
        tsp_password = existing.tsp_password

    tilda_secret = body.tilda_secret.strip()
    if not tilda_secret:
        if existing is None:
            raise HTTPException(status_code=400, detail="Секрет Tilda обязателен для новой точки")
        tilda_secret = existing.tilda_order_secret

    db.add_tenant(
        url_tilda=url_tilda,
        tsp_login=body.tsp_login.strip(),
        tsp_password=tsp_password,
        bank_terminal_id=body.bank_terminal_id.strip(),
        tilda_login=body.bank_terminal_id.strip(),
        tilda_order_secret=tilda_secret,
        tilda_notify_url=body.tilda_notify_url.strip(),
        bank_env=body.bank_env,
        bank_owner_type=body.bank_owner_type,
        tilda_success_url=body.tilda_success_url.strip(),
        tilda_fail_url=body.tilda_fail_url.strip(),
        inn=body.inn.strip(),
        merchant_name=body.merchant_name.strip(),
        terminal_number=body.terminal_number.strip(),
        type_rid=body.type_rid.strip() or "56",
        ofd_provider=body.ofd_provider,
    )
    return _tenant_summary(db.get_tenant(url_tilda))


@router.delete("/admin/api/tenants/{url_tilda}", dependencies=[Depends(require_admin)])
async def delete_tenant_api(url_tilda: str):
    if db.get_tenant(url_tilda) is None:
        raise HTTPException(status_code=404, detail="Точка не найдена")
    db.delete_tenant(url_tilda)
    return {"ok": True}


@router.get("/admin", response_class=HTMLResponse)
async def admin_page():
    return ADMIN_HTML


ADMIN_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Торговые точки — админ-панель</title>
<link rel="icon" href="data:image/vnd.microsoft.icon;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAB9ElEQVQ4jX3TQWiVRxQF4O8+wuMhIsGK0BCysRSRIuhCpSAKVvsHUvhBRFHoQhAUlO6EKOLSRZFsIghtQRS7auGlxfoHRTGgUG0VRYKI1CxKkCAiQYK8hbeL96fEED2bGeacOXPm3pkoq6IlPRDu4x52ZmZrbHB8R1kV+zOdijCHS9iDA+2imlKjgYbwCL9Kn+JsRMzW/Mrgc1zHye6Y+yxAI9M7mT/oCofxDc78rwgXM5X4GQeJ5nsGEd4Kq/FHe7B6R/6NuZq/g74Ij7EJ/RahewUxh5X1kSvQKasC9mIVOtiyeDP0oFUb7SmroplpTYQZbMS3mfljRPThPPYvlQBG8LvMZoQ/8RnOYSQibmNa5mtyt9RZnAAGcEVEBxewC6dxPRkKfhLxBseEy0slmJ/fwFpMkKN4EnzSLqqpdlG9zMwmnn7IYBIzdU1m28U4LIeyKnq6RY3G/Npig1f4DV/hrm7focA16TSOR7idDC00iLIqWhgmjxKjOIFpfJesj7RZ+L7WH8K/eIhf2kXViTpiIfUIXycDwT/JreAF1nkfkzgitYS9813oF0bIZZHREASHcV/mhIibuIvX7aJSVsWU8BytKK8WPbgiDGMKvfgCW7Ed69HEWzzCXzXfiw3hI6ifcy++xDbd/7AKk5l5cmxw/Nl/ununHR8+tzIAAAAASUVORK5CYII=">
<style>
  :root{
    --bg:#FFFFFF; --surface:#FFFFFF; --ink:#141414; --ink-dim:#6B7280; --ink-faint:#ADB5BD;
    --line:#E3E5E8; --brand:#50B848; --brand-dark:#3E9438; --coral:#D2454E; --coral-dim:#FBE8E7;
  }
  *{box-sizing:border-box;}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,Segoe UI,Arial,sans-serif;}
  .wrap{max-width:880px;margin:0 auto;padding:64px 20px 80px;}
  h1{font-size:26px;font-weight:700;margin:0 0 4px;color:var(--ink);}
  .sub{color:var(--ink-dim);font-size:13.5px;margin-bottom:24px;}
  #loginBox{max-width:380px;margin:80px auto;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:24px;}
  #loginBox h2{font-size:20px;font-weight:700;margin-top:0;}
  input, select{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:8px;font-size:13.5px;background:#fff;color:var(--ink);}
  select{
    appearance:none;-webkit-appearance:none;-moz-appearance:none;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%236B7280' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>");
    background-repeat:no-repeat;background-position:right 12px center;padding-right:34px;cursor:pointer;
  }
  select:focus{outline:none;border-color:var(--brand);}
  input::placeholder{color:var(--ink-faint);}
  label{display:block;font-size:13px;font-weight:600;color:var(--brand);margin:10px 0 5px;}
  button{cursor:pointer;border:none;border-radius:8px;padding:11px 16px;font-size:14px;font-weight:700;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;line-height:1.1;}
  .btn-primary{background:var(--brand);color:#fff;}
  .btn-primary:hover{background:var(--brand-dark);}
  .btn-ghost{background:transparent;color:var(--ink-dim);border:1px solid var(--line);}
  .btn-danger{background:var(--coral-dim);color:var(--coral);}
  table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--line);border-radius:10px;overflow:hidden;}
  th,td{text-align:left;padding:10px 12px;font-size:13px;border-bottom:1px solid var(--line);vertical-align:middle;}
  th{color:var(--ink-faint);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em;}
  tr:last-child td{border-bottom:none;}
  .row-actions{display:flex;gap:6px;align-items:center;}
  .toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;}
  .modal-bg{position:fixed;inset:0;background:rgba(20,20,20,.35);display:flex;align-items:flex-start;justify-content:center;padding:40px 16px;overflow:auto;}
  .modal{background:var(--surface);border-radius:12px;padding:24px;max-width:520px;width:100%;box-shadow:0 12px 32px rgba(0,0,0,.12);}
  .modal h2{margin-top:0;font-size:19px;font-weight:700;}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:0 12px;}
  .hint{font-size:11.5px;color:var(--ink-faint);margin-top:3px;}
  .modal-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:20px;}
  .checkout-url{font-family:monospace;font-size:11.5px;background:#F7F8F9;border:1px dashed var(--line);padding:8px 10px;border-radius:6px;word-break:break-all;margin-top:6px;cursor:pointer;transition:background .15s;}
  .checkout-url:hover{background:#EEF0F2;border-color:var(--ink-faint);}
  .checkout-url:active{background:#E3E7EA;}
  .checkout-url.copied{background:#E9F7E6;border-color:var(--brand);color:var(--brand-dark);font-weight:700;}
  .hidden{display:none !important;}
  .spinner{width:34px;height:34px;border:3px solid var(--line);border-top-color:var(--brand);border-radius:50%;animation:spin .7s linear infinite;}
  @keyframes spin{to{transform:rotate(360deg);}}
  #loader{position:fixed;inset:0;background:rgba(255,255,255,.7);display:flex;align-items:center;justify-content:center;z-index:50;}
  .inline-spinner{display:flex;justify-content:center;padding:40px 0;}
  .search-wrap{position:relative;max-width:260px;width:100%;}
  .search-wrap input{padding-right:32px;}
  .search-clear{position:absolute;right:6px;top:50%;transform:translateY(-50%);background:transparent;border:none;color:var(--ink-faint);font-size:16px;line-height:1;padding:4px 6px;cursor:pointer;border-radius:5px;}
  .search-clear:hover{color:var(--ink-dim);background:var(--bg);}
  .modal.modal-sm{max-width:380px;}
  .modal p{font-size:13.5px;color:var(--ink-dim);line-height:1.5;}
  .error{color:var(--coral);font-size:12.5px;margin-top:8px;}
  .input-error{border-color:var(--coral) !important;background:var(--coral-dim);}
  .empty{padding:30px;text-align:center;color:var(--ink-faint);font-size:13.5px;}
  .brand-mark{position:fixed;top:20px;left:24px;width:140px;}
  .brand-mark svg{width:100%;height:auto;display:block;}
  .logout-fixed{position:fixed;top:20px;right:24px;z-index:5;}
  .pagination{display:flex;align-items:center;justify-content:center;gap:14px;margin-top:16px;}
  .pagination.hidden{display:none;}
  #pageInfo{font-size:13px;color:var(--ink-dim);}
  .pagination button:disabled{opacity:.4;cursor:default;}
</style>
</head>

<body>

<div class="brand-mark"><svg width="166" height="35" viewBox="0 0 166 35" fill="none" xmlns="http://www.w3.org/2000/svg"><g clip-path="url(#clip0_147_4951)"><path d="M96.9982 20.3112H91.4972V22.8901H96.9982V20.3112Z" fill="#50B848"></path><path d="M71.8587 16.0811H74.8086V27.0089H77.7215V16.0811H80.6807V13.5208H71.8587V16.0811ZM67.8048 18.5951H62.6007V13.5115H59.6878V26.9996H62.6007V21.1554H67.8048V26.9996H70.7177V13.5208H67.8048V18.6044V18.5951ZM47.35 13.5115H44.4372V24.4486H39.5948V13.5208H36.682V27.0089H46.2183V29.9681H48.9363V24.4486H47.3593V13.5208L47.35 13.5115ZM136.86 26.9996H144.503V24.4393H139.772V21.2111H144.309V18.6507H139.772V16.0719H144.503V13.5115H136.86V26.9996ZM132.898 19.7361C133.075 19.6062 133.27 19.4392 133.455 19.1981C133.798 18.7621 134.095 18.122 134.095 17.2407C134.095 16.0904 133.622 15.0143 132.806 14.3835C131.674 13.5115 130.218 13.5208 129.485 13.5208H126.052V27.0089H130.644C131.804 27.0089 133.065 26.8141 134.095 25.905C135.051 25.0516 135.273 23.9105 135.273 23.1128C135.273 22.3985 135.116 21.3224 134.271 20.5246C133.984 20.2463 133.548 19.9216 132.889 19.7454L132.898 19.7361ZM128.974 15.9513H129.54C130.032 15.9513 130.496 16.0626 130.811 16.2945C131.127 16.5264 131.331 16.8789 131.331 17.4262C131.331 17.8158 131.238 18.0941 131.108 18.3075C130.904 18.6136 130.589 18.7806 130.273 18.8734C129.958 18.9661 129.661 18.9661 129.522 18.9661H128.974V15.9513ZM132.128 23.5951C132.017 23.8363 131.841 24.059 131.563 24.226C131.043 24.5321 130.366 24.5599 129.902 24.5599H128.974V21.2853H129.744C130.301 21.2853 130.923 21.2853 131.423 21.5265C131.795 21.6934 132.008 21.9346 132.128 22.1758C132.249 22.417 132.286 22.6675 132.286 22.8623C132.286 23.0942 132.249 23.354 132.138 23.5951H132.128ZM50.1423 26.9996H57.7861V24.4393H53.0551V21.2111H57.5913V18.6507H53.0551V16.0719H57.7861V13.5115H50.1423V26.9996ZM156.999 13.5115V16.0719H159.958V26.9996H162.871V16.0719H165.83V13.5115H156.999ZM89.4007 14.5598C88.8997 14.1238 88.371 13.8548 87.7865 13.6971C87.2021 13.5486 86.562 13.5022 85.8106 13.5022H81.8124V26.9904H84.7346V22.1294H86.2095C87.7587 22.1294 88.8905 21.6842 89.6604 20.9142C90.7179 19.8474 90.7921 18.3817 90.7921 17.853C90.7921 16.8696 90.5046 15.5431 89.3914 14.5505L89.4007 14.5598ZM87.165 19.1981C86.6641 19.5691 86.0889 19.5784 85.5973 19.5784H84.7346V16.0719H85.4396C86.0425 16.0719 86.6733 16.1182 87.1465 16.4522C87.4804 16.7027 87.7958 17.1387 87.8051 17.8066C87.8051 18.3261 87.5825 18.8641 87.165 19.1981ZM152.75 13.2147C150.849 13.2147 149.16 13.7156 147.806 14.9958C146.656 16.0626 145.644 17.8344 145.644 20.2649C145.644 22.2315 146.257 23.9291 147.806 25.4133C148.928 26.4802 150.394 27.2965 152.741 27.2965C154.188 27.2965 155.264 26.9347 156.071 26.508L156.164 26.4616V22.8716L155.849 23.2426C155.107 24.1054 154.077 24.6156 152.917 24.6156C151.85 24.6156 150.784 24.2352 149.977 23.5117C149.179 22.7788 148.641 21.712 148.641 20.302C148.641 19.1331 149.058 18.0292 149.782 17.2221C150.505 16.4151 151.544 15.8956 152.815 15.8956C153.27 15.8956 154.698 15.9884 155.849 17.3149L156.164 17.6767V14.0959L156.071 14.0496C154.838 13.3817 153.697 13.224 152.76 13.224L152.75 13.2147ZM101.405 21.9996V13.5208H98.4917V27.0089H100.727L107.509 18.4838V27.0089H110.421V13.5208H108.149L101.395 22.0181L101.405 21.9996ZM120.839 18.5858H115.635V13.5022H112.722V26.9904H115.635V21.1461H120.839V26.9904H123.752V13.5208H120.839V18.6044V18.5858Z" fill="#50B848"></path><path d="M43.0179 5.06058C42.1551 4.2999 41.0883 4.17003 40.2906 4.17003H39.0661V2.13846H43.0735V0.032682H36.682V10.812H40.3091C40.7729 10.812 41.3388 10.7749 41.9047 10.5894C42.4705 10.4039 43.0271 10.0699 43.4539 9.46694C43.8342 8.9289 44.0568 8.24244 44.0568 7.50959C44.0568 6.47989 43.6487 5.62645 43.0179 5.06058ZM41.3017 8.2981C41.0698 8.52073 40.6338 8.70627 39.8453 8.70627H39.0568V6.28508H39.8824C40.6245 6.28508 41.0512 6.47061 41.2924 6.70253C41.5336 6.93444 41.6078 7.24057 41.6171 7.52814C41.6171 7.79716 41.5429 8.07546 41.311 8.30737L41.3017 8.2981ZM70.8661 5.03275L75.4487 0.032682H72.3967L68.8253 4.1422V0.032682H66.4319V10.812H68.8253V6.26653L68.8624 6.22942L72.4988 10.812H75.6528L70.8661 5.03275ZM48.6766 0.032682L44.1032 10.812H46.6914L47.619 8.62278H51.5894L52.5078 10.812H55.0774L50.6246 0.032682H48.6766ZM48.3983 6.60976L49.6321 3.52067L50.838 6.60976H48.3983ZM62.2667 4.05871H58.2129V0.032682H55.8195V10.812H58.2129V6.17376H62.2667V10.812H64.6508V0.032682H62.2667V4.06799V4.05871Z" fill="#50B848"></path><path d="M14.9284 0.00485229V7.85282L21.32 0.00485229H14.9284Z" fill="#50B848"></path><path d="M25.8748 1.09021L14.9284 14.5412V17.8901C14.947 17.7973 14.9563 17.7045 14.9748 17.6118L15.114 17.0181C15.3737 16.1461 15.7355 15.3947 16.2828 14.6433L16.6539 14.198C17.0806 13.762 17.498 13.428 18.0361 13.1126C18.3144 12.9642 18.5834 12.8529 18.871 12.7416C19.5111 12.556 20.0677 12.4818 20.7448 12.5004L21.3757 12.5839C21.9044 12.7045 22.3311 12.8714 22.8042 13.1126C23.064 13.2611 23.3052 13.4188 23.5371 13.6043C24.2514 14.2073 24.7523 14.8473 25.179 15.6359L25.4295 16.1739C25.6336 16.6841 25.7727 17.4262 25.8655 17.9179V1.09021H25.8748Z" fill="#50B848"></path><path d="M20.4202 13.7156C18.0268 13.7156 16.0787 16.1646 16.0787 19.1702C16.0787 22.1758 18.0268 24.6341 20.4202 24.6341C22.8135 24.6341 24.7709 22.1851 24.7709 19.1702C24.7709 16.1553 22.8228 13.7156 20.4202 13.7156ZM20.4202 22.8716C18.9823 22.8716 17.8042 21.2111 17.8042 19.1795C17.8042 17.1479 18.973 15.4874 20.4202 15.4874C21.8673 15.4874 23.0454 17.1479 23.0454 19.1795C23.0454 21.2111 21.8673 22.8716 20.4202 22.8716Z" fill="#50B848"></path><path d="M15.1233 21.3317L14.9841 20.738C14.9655 20.6452 14.947 20.5524 14.9377 20.4597V27.0182H25.8841V20.4968C25.7449 21.1925 25.5316 22.046 25.1976 22.7231L24.9007 23.2334C24.4555 23.9013 23.9824 24.43 23.3145 24.931L22.8135 25.2464C22.3404 25.4876 21.9044 25.6545 21.3849 25.7751C21.0602 25.8308 20.7634 25.8586 20.4294 25.8679C19.9934 25.8493 19.6038 25.803 19.1771 25.7009C18.8803 25.6082 18.602 25.5061 18.3144 25.3855C17.665 25.0423 17.1734 24.6712 16.6724 24.161L16.2921 23.7157C15.7448 22.9643 15.383 22.2129 15.1233 21.3409V21.3317Z" fill="#50B848"></path><path d="M0.21582 25.9328L11.1622 12.4818V9.13299C11.1529 9.22575 11.1343 9.31852 11.1158 9.41128L10.9674 10.005C10.7076 10.877 10.3458 11.6284 9.79851 12.3798L9.41817 12.8251C8.99145 13.2611 8.574 13.595 8.04524 13.9104C7.76694 14.0588 7.49792 14.1702 7.21035 14.2815C6.57026 14.467 6.01367 14.5412 5.33648 14.5227L4.70568 14.4392C4.17691 14.3186 3.75019 14.1516 3.27708 13.9104C3.01734 13.762 2.77615 13.6043 2.53496 13.4188C1.82066 12.8158 1.32901 12.185 0.893009 11.3872L0.642542 10.8491C0.457011 10.3575 0.308586 9.61537 0.21582 9.11443V25.9328Z" fill="#50B848"></path><path d="M5.66116 13.3074C8.05451 13.3074 10.0026 10.8584 10.0026 7.85282C10.0026 4.84722 8.06379 2.38893 5.66116 2.38893C3.25853 2.38893 1.31973 4.83794 1.31973 7.85282C1.31973 10.8584 3.26781 13.3074 5.66116 13.3074ZM5.66116 4.15147C7.1083 4.15147 8.27715 5.81198 8.27715 7.85282C8.27715 9.89366 7.09903 11.5449 5.66116 11.5449C4.22329 11.5449 3.04517 9.88439 3.04517 7.85282C3.04517 5.82126 4.22329 4.15147 5.66116 4.15147Z" fill="#50B848"></path><path d="M10.9674 5.69138L11.1158 6.28508C11.1343 6.37785 11.1529 6.47061 11.1622 6.5541V0.00485229H0.21582V6.53555C0.354969 5.83981 0.56833 4.97709 0.902286 4.30918L1.19914 3.79897C1.64441 3.13105 2.11751 2.60229 2.78543 2.10135L3.28636 1.78595C3.75947 1.54476 4.18619 1.37778 4.71495 1.25719C5.03963 1.20153 5.33648 1.1737 5.67044 1.16442C6.11571 1.1737 6.49605 1.22936 6.92277 1.3314C7.21962 1.42417 7.49792 1.52621 7.78549 1.6468C8.43485 1.99004 8.93579 2.3611 9.42744 2.88059L9.80778 3.32586C10.3551 4.07726 10.7076 4.82866 10.9766 5.70066L10.9674 5.69138Z" fill="#50B848"></path><path d="M11.1622 19.1795L4.77061 27.0089H11.1622V19.1795Z" fill="#50B848"></path><path d="M22.7857 0.00485229L0.846626 27.0089H3.26781L25.2533 0.00485229H22.7857Z" fill="#50B848"></path><path d="M13.973 25.1536H12.1176V27.0089H13.973V25.1536Z" fill="#50B848"></path><path d="M26.9694 25.1536V27.0089C28.2496 27.0089 29.1494 28.2241 29.1494 29.495C29.1494 30.7659 28.1012 31.9719 26.821 31.9719C25.8748 31.9719 25.0121 31.7585 23.2217 31.3225C19.743 30.4691 15.4665 29.4208 12.0434 28.5859C5.8838 27.0739 0.24365 28.7807 0.21582 32.7789H2.08969C2.08969 31.2947 4.97469 30.3021 11.1436 31.8142C16.4776 33.1222 18.4814 33.6138 22.4981 34.5971C25.1512 35.2465 27.3219 35.0888 28.8897 34.3467C30.4574 33.5953 31.5242 31.7585 31.5242 29.931C31.5242 27.3614 29.5576 25.1536 26.9601 25.1536H26.9694Z" fill="#50B848"></path></g><defs><clipPath id="clip0_147_4951"><rect width="166" height="35" fill="white"></rect></clipPath></defs></svg></div>

<button class="btn-ghost logout-fixed" onclick="logout()">Выйти</button>

<div id="loginBox">
  <h2>Вход в админ-панель</h2>
  <label for="adminKeyInput">X-Admin-Key</label>
  <input id="adminKeyInput" type="password" placeholder="Ваш ADMIN_API_KEY">
  <div class="error" id="loginError"></div>
  <button class="btn-primary" style="margin-top:14px;width:100%" onclick="login()">Войти</button>
</div>

<div class="wrap hidden" id="mainBox">
  <h1>Торговые точки</h1>
  <div class="sub">Управление точками, подключёнными к серверу-посреднику.</div>
  <div class="toolbar">
    <div class="search-wrap">
      <input id="searchInn" placeholder="Поиск по ИНН или номеру терминала…" oninput="onSearchChange()">
      <button class="search-clear hidden" id="searchClearBtn" onclick="clearSearch()" title="Очистить">✕</button>
    </div>
    <button class="btn-primary" onclick="openForm(null)">+ Добавить точку</button>
  </div>
  <div id="tableWrap"></div>
  <div id="pagination" class="pagination hidden">
    <button class="btn-ghost" id="prevPageBtn" onclick="goToPage(currentPage - 1)">← Назад</button>
    <span id="pageInfo"></span>
    <button class="btn-ghost" id="nextPageBtn" onclick="goToPage(currentPage + 1)">Вперёд →</button>
  </div>
</div>

<div id="loader" class="hidden"><div class="spinner"></div></div>

<div class="modal-bg hidden" id="modalBg">
  <div class="modal">
    <h2 id="modalTitle">Новая точка</h2>
    <label>URL Tilda</label>
    <input id="f_url_tilda" placeholder="shop2">
    <div class="hint">Короткий идентификатор — часть API URL, после создания не меняется.</div>

    <label>Название ТСП</label>
    <input id="f_merchant_name" placeholder="ООО «Ромашка»">

    <div class="grid2">
      <div><label>Логин ТСП</label><input id="f_tsp_login" placeholder="+79000000001"></div>
      <div><label>Терминал ID TXPG</label><input id="f_bank_terminal_id" placeholder="279"></div>
    </div>
    <div class="grid2">
      <div><label>Номер терминала</label><input id="f_terminal_number" placeholder="T-00123"></div>
      <div><label>ИНН</label><input id="f_inn" placeholder="7727401209"></div>
    </div>
    <div class="grid2">
      <div>
        <label>Тип заказа (typeRid)</label>
        <input id="f_type_rid" placeholder="56">
      </div>
      <div>
        <label>ОФД</label>
        <select id="f_ofd_provider">
          <option value="orange_data">Orange Data</option>
          <option value="bifit">БИФИТ Онлайн</option>
        </select>
      </div>
    </div>
    <div class="hint">Тип заказа выдаёт банк — определяет способ оплаты/тип операции, так как Tilda его не передаёт.
      ОФД влияет на формат кода ставки НДС в чеке.</div>
    <label>Пароль ТСП</label>
    <input id="f_tsp_password" type="password" placeholder="(оставьте пустым, чтобы не менять)">

    <div class="grid2">
      <div>
        <label>Тип владельца логина</label>
        <select id="f_bank_owner_type">
          <option value="MultiMerchant">MultiMerchant</option>
          <option value="TerminalSys">TerminalSys</option>
        </select>
      </div>
      <div>
        <label>Среда банка</label>
        <select id="f_bank_env">
          <option value="test">test</option>
          <option value="prod">prod</option>
        </select>
      </div>
    </div>

    <label>Секрет подписи Tilda</label>
    <input id="f_tilda_secret" type="password" placeholder="(оставьте пустым, чтобы не менять)">
    <label>URL для уведомлений Tilda</label>
    <input id="f_tilda_notify_url" placeholder="https://forms.tildaapi.one/payment/custom/psXXXXXXX">
    <div class="grid2">
      <div><label>URL успеха</label><input id="f_tilda_success_url" placeholder="https://.../thanks"></div>
      <div><label>URL отказа</label><input id="f_tilda_fail_url" placeholder="https://.../payment-failed"></div>
    </div>

    <div class="error" id="formError"></div>
    <div class="modal-actions">
      <button class="btn-ghost" onclick="closeForm()">Отмена</button>
      <button class="btn-primary" onclick="saveTenant()">Сохранить</button>
    </div>
  </div>
</div>

<div class="modal-bg hidden" id="deleteModalBg">
  <div class="modal modal-sm">
    <h2>Удалить точку</h2>
    <p>Точка <b id="deleteShopIdLabel"></b> будет удалена без возможности восстановления —
       все её настройки (ключи банка, секрет Tilda) исчезнут из БД.</p>
    <div class="error" id="deleteError"></div>
    <div class="modal-actions">
      <button class="btn-ghost" onclick="closeDeleteModal()">Отмена</button>
      <button class="btn-danger" onclick="confirmDelete()">Удалить</button>
    </div>
  </div>
</div>

<script>
let adminKey = sessionStorage.getItem('adminKey') || '';
let editingShopId = null;

function login() {
  adminKey = document.getElementById('adminKeyInput').value.trim();
  if (!adminKey) return;
  sessionStorage.setItem('adminKey', adminKey);
  boot();
}

function logout() {
  sessionStorage.removeItem('adminKey');
  adminKey = '';
  document.getElementById('mainBox').classList.add('hidden');
  document.getElementById('loginBox').classList.remove('hidden');
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey, ...(options.headers || {}) },
  });
  if (res.status === 401) {
    logout();
    document.getElementById('loginError').textContent = 'Неверный ключ.';
    throw new Error('unauthorized');
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || ('HTTP ' + res.status));
  }
  return res.status === 204 ? null : res.json();
}

const PAGE_SIZE = 10;
let allTenants = [];
let currentPage = 1;

function showLoader() {
  document.getElementById('loader').classList.remove('hidden');
}
function hideLoader() {
  document.getElementById('loader').classList.add('hidden');
}

async function boot() {
  showLoader();
  try {
    allTenants = await api('/admin/api/tenants');
    document.getElementById('loginBox').classList.add('hidden');
    document.getElementById('mainBox').classList.remove('hidden');
    currentPage = 1;
    renderTable();
  } catch (e) {
    if (e.message !== 'unauthorized') {
      document.getElementById('loginError').textContent = 'Ошибка: ' + e.message;
    }
  } finally {
    hideLoader();
  }
}

function onSearchChange() {
  currentPage = 1;
  document.getElementById('searchClearBtn').classList.toggle('hidden', !document.getElementById('searchInn').value);
  renderTable();
}

function clearSearch() {
  document.getElementById('searchInn').value = '';
  onSearchChange();
}

async function copyCheckoutUrl(url, el) {
  try {
    await navigator.clipboard.writeText(url);
  } catch (e) {
    // Резервный вариант, если Clipboard API недоступен (например, http без TLS)
    const ta = document.createElement('textarea');
    ta.value = url;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }
  const original = el.textContent;
  el.textContent = 'Скопировано ✓';
  el.classList.add('copied');
  setTimeout(() => {
    el.textContent = original;
    el.classList.remove('copied');
  }, 1200);
}

function goToPage(page) {
  currentPage = page;
  renderTable();
}

function getFilteredTenants() {
  const query = document.getElementById('searchInn').value.trim();
  if (!query) return allTenants;
  return allTenants.filter(t =>
    (t.inn || '').includes(query) || (t.terminal_number || '').includes(query)
  );
}

function renderTable() {
  const wrap = document.getElementById('tableWrap');
  const paginationEl = document.getElementById('pagination');
  const filtered = getFilteredTenants();

  if (!allTenants.length) {
    wrap.innerHTML = '<div class="empty">Точек пока нет — нажмите «Добавить точку».</div>';
    paginationEl.classList.add('hidden');
    return;
  }
  if (!filtered.length) {
    wrap.innerHTML = '<div class="empty">Ничего не найдено по этому ИНН.</div>';
    paginationEl.classList.add('hidden');
    return;
  }

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  if (currentPage > totalPages) currentPage = totalPages;
  const pageItems = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  const rows = pageItems.map(t => `
    <tr>
      <td><b>${t.terminal_number || '—'}</b></td>
      <td><b>${t.url_tilda}</b><br><span style="color:var(--ink-faint)">${t.merchant_name || ''}</span><div class="checkout-url" title="Нажмите, чтобы скопировать" onclick="copyCheckoutUrl('${t.checkout_url}', this)">${t.checkout_url}</div></td>
      <td>${t.bank_env}</td>
      <td>${t.tsp_login}</td>
      <td>${t.bank_terminal_id}</td>
      <td>${t.inn || '<span style="color:var(--coral)">нет ИНН</span>'}</td>
      <td>
        <div class="row-actions">
          <button class="btn-ghost" onclick="openForm('${t.url_tilda}')">Изменить</button>
          <button class="btn-danger" onclick="removeTenant('${t.url_tilda}')">Удалить</button>
        </div>
      </td>
    </tr>
  `).join('');
  wrap.innerHTML = `<table>
    <tr><th>Номер терминала</th><th>URL Tilda</th><th>Среда</th><th>Логин ТСП</th><th>Терминал ID TXPG</th><th>ИНН</th><th></th></tr>
    ${rows}
  </table>`;

  if (totalPages > 1) {
    paginationEl.classList.remove('hidden');
    document.getElementById('pageInfo').textContent = `Страница ${currentPage} из ${totalPages} (${filtered.length} записей)`;
    document.getElementById('prevPageBtn').disabled = currentPage <= 1;
    document.getElementById('nextPageBtn').disabled = currentPage >= totalPages;
  } else {
    paginationEl.classList.add('hidden');
  }
}

async function openForm(shopId) {
  editingShopId = shopId;
  document.getElementById('formError').textContent = '';
  clearFieldErrors();
  document.getElementById('modalTitle').textContent = shopId ? `Изменить: ${shopId}` : 'Новая точка';
  const ids = ['tsp_login','tsp_password','bank_terminal_id','bank_owner_type','bank_env',
               'tilda_secret','tilda_notify_url','tilda_success_url','tilda_fail_url','inn',
               'merchant_name','terminal_number'];
  ids.forEach(id => document.getElementById('f_' + id).value = '');
  document.getElementById('f_url_tilda').value = '';
  document.getElementById('f_url_tilda').disabled = false;
  document.getElementById('f_type_rid').value = '56';
  document.getElementById('f_ofd_provider').value = 'orange_data';

  // Плейсхолдеры и выпадающие списки — сбрасываем к дефолтам новой точки.
  // Иначе при повторном открытии формы после редактирования другой точки
  // остаются старые подсказки/значения (поля переиспользуются между
  // созданием и редактированием).
  document.getElementById('f_tsp_password').placeholder = 'обязательно';
  document.getElementById('f_tilda_secret').placeholder = 'обязательно';
  document.getElementById('f_bank_owner_type').value = 'MultiMerchant';
  document.getElementById('f_bank_env').value = 'test';

  if (shopId) {
    showLoader();
    let t;
    try {
      t = await api('/admin/api/tenants/' + encodeURIComponent(shopId));
    } finally {
      hideLoader();
    }
    document.getElementById('f_url_tilda').value = t.url_tilda;
    document.getElementById('f_url_tilda').disabled = true;
    document.getElementById('f_tsp_login').value = t.tsp_login;
    document.getElementById('f_bank_terminal_id').value = t.bank_terminal_id;
    document.getElementById('f_bank_owner_type').value = t.bank_owner_type;
    document.getElementById('f_bank_env').value = t.bank_env;
    document.getElementById('f_tilda_notify_url').value = t.tilda_notify_url;
    document.getElementById('f_tilda_success_url').value = t.tilda_success_url;
    document.getElementById('f_tilda_fail_url').value = t.tilda_fail_url;
    document.getElementById('f_inn').value = t.inn;
    document.getElementById('f_merchant_name').value = t.merchant_name;
    document.getElementById('f_terminal_number').value = t.terminal_number;
    document.getElementById('f_type_rid').value = t.type_rid;
    document.getElementById('f_ofd_provider').value = t.ofd_provider;
    document.getElementById('f_tsp_password').placeholder = t.tsp_password_set
      ? '•••••• (задан — оставьте пустым, чтобы не менять)' : 'обязательно';
    document.getElementById('f_tilda_secret').placeholder = t.tilda_secret_set
      ? '•••••• (задан — оставьте пустым, чтобы не менять)' : 'обязательно';
  }
  document.getElementById('modalBg').classList.remove('hidden');
}

function closeForm() {
  document.getElementById('modalBg').classList.add('hidden');
}

const REQUIRED_FIELD_IDS = ['url_tilda', 'tsp_login', 'bank_terminal_id', 'bank_owner_type',
                            'bank_env', 'tilda_notify_url', 'tilda_success_url', 'tilda_fail_url', 'inn',
                            'merchant_name', 'terminal_number'];
// tsp_password и tilda_secret обязательны только при создании новой точки
// (при редактировании пустое значение означает "не менять") — единственное
// оставшееся исключение из общего правила "все поля обязательны".

function clearFieldErrors() {
  [...REQUIRED_FIELD_IDS, 'tsp_password', 'tilda_secret'].forEach(id => {
    document.getElementById('f_' + id).classList.remove('input-error');
  });
}

function validateForm() {
  clearFieldErrors();
  let firstInvalid = null;
  const missing = [];

  REQUIRED_FIELD_IDS.forEach(id => {
    const el = document.getElementById('f_' + id);
    if (!el.value.trim()) {
      el.classList.add('input-error');
      missing.push(id);
      if (!firstInvalid) firstInvalid = el;
    }
  });

  if (!editingShopId) {
    ['tsp_password', 'tilda_secret'].forEach(id => {
      const el = document.getElementById('f_' + id);
      if (!el.value.trim()) {
        el.classList.add('input-error');
        missing.push(id);
        if (!firstInvalid) firstInvalid = el;
      }
    });
  }

  if (missing.length) {
    if (firstInvalid) firstInvalid.focus();
    return 'Заполните обязательные поля: ' + missing.join(', ');
  }
  return null;
}

async function saveTenant() {
  const validationError = validateForm();
  if (validationError) {
    document.getElementById('formError').textContent = validationError;
    return;
  }

  const shopId = document.getElementById('f_url_tilda').value.trim();
  const body = {
    tsp_login: document.getElementById('f_tsp_login').value.trim(),
    tsp_password: document.getElementById('f_tsp_password').value,
    bank_terminal_id: document.getElementById('f_bank_terminal_id').value.trim(),
    bank_owner_type: document.getElementById('f_bank_owner_type').value,
    bank_env: document.getElementById('f_bank_env').value,
    tilda_secret: document.getElementById('f_tilda_secret').value,
    tilda_notify_url: document.getElementById('f_tilda_notify_url').value.trim(),
    tilda_success_url: document.getElementById('f_tilda_success_url').value.trim(),
    tilda_fail_url: document.getElementById('f_tilda_fail_url').value.trim(),
    inn: document.getElementById('f_inn').value.trim(),
    merchant_name: document.getElementById('f_merchant_name').value.trim(),
    terminal_number: document.getElementById('f_terminal_number').value.trim(),
    type_rid: document.getElementById('f_type_rid').value.trim() || '56',
    ofd_provider: document.getElementById('f_ofd_provider').value,
  };
  try {
    showLoader();
    await api('/admin/api/tenants/' + encodeURIComponent(shopId), { method: 'PUT', body: JSON.stringify(body) });
    closeForm();
    await boot();
  } catch (e) {
    document.getElementById('formError').textContent = 'Ошибка: ' + e.message;
  } finally {
    hideLoader();
  }
}

let deletingShopId = null;

function removeTenant(shopId) {
  deletingShopId = shopId;
  document.getElementById('deleteShopIdLabel').textContent = shopId;
  document.getElementById('deleteError').textContent = '';
  document.getElementById('deleteModalBg').classList.remove('hidden');
}

function closeDeleteModal() {
  document.getElementById('deleteModalBg').classList.add('hidden');
  deletingShopId = null;
}

async function confirmDelete() {
  if (!deletingShopId) return;
  try {
    showLoader();
    await api('/admin/api/tenants/' + encodeURIComponent(deletingShopId), { method: 'DELETE' });
    closeDeleteModal();
    await boot();
  } catch (e) {
    document.getElementById('deleteError').textContent = 'Ошибка: ' + e.message;
  } finally {
    hideLoader();
  }
}

document.querySelectorAll('#modalBg input, #modalBg select').forEach(el => {
  el.addEventListener('input', () => el.classList.remove('input-error'));
  el.addEventListener('change', () => el.classList.remove('input-error'));
});

if (adminKey) {
  // Прячем форму входа сразу, не дожидаясь ответа сервера — иначе она
  // на мгновение мелькает, пока идёт запрос /admin/api/tenants.
  document.getElementById('loginBox').classList.add('hidden');
  boot();
}
</script>
</body>
</html>
"""
