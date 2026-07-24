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
    bank_login: str
    bank_password: str = ""
    bank_terminal_id: str
    bank_owner_type: str = "MultiMerchant"
    bank_env: str = "test"
    tilda_secret: str = ""
    tilda_notify_url: str
    tilda_success_url: str = ""
    tilda_fail_url: str = ""
    inn: str = ""


def _tenant_summary(tenant: db.Tenant) -> dict:
    return {
        "shop_id": tenant.shop_id,
        "bank_env": tenant.bank_env,
        "bank_owner_type": tenant.bank_owner_type,
        "bank_login": tenant.bank_login,
        "bank_password_set": bool(tenant.bank_password),
        "bank_terminal_id": tenant.bank_terminal_id,
        "tilda_login": tenant.tilda_login,
        "tilda_secret_set": bool(tenant.tilda_order_secret),
        "tilda_notify_url": tenant.tilda_notify_url,
        "tilda_success_url": tenant.tilda_success_url,
        "tilda_fail_url": tenant.tilda_fail_url,
        "inn": tenant.inn,
        "checkout_url": f"{settings.public_base_url}/tilda/{tenant.shop_id}/checkout",
    }


@router.get("/admin/api/tenants", dependencies=[Depends(require_admin)])
async def list_tenants_api():
    return [_tenant_summary(db.get_tenant(shop_id)) for shop_id in db.list_tenants()]


@router.get("/admin/api/tenants/{shop_id}", dependencies=[Depends(require_admin)])
async def get_tenant_api(shop_id: str):
    tenant = db.get_tenant(shop_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Точка не найдена")
    return _tenant_summary(tenant)


@router.put("/admin/api/tenants/{shop_id}", dependencies=[Depends(require_admin)])
async def upsert_tenant_api(shop_id: str, body: TenantIn):
    existing = db.get_tenant(shop_id)

    bank_password = body.bank_password.strip()
    if not bank_password:
        if existing is None:
            raise HTTPException(status_code=400, detail="Пароль банка обязателен для новой точки")
        bank_password = existing.bank_password

    tilda_secret = body.tilda_secret.strip()
    if not tilda_secret:
        if existing is None:
            raise HTTPException(status_code=400, detail="Секрет Tilda обязателен для новой точки")
        tilda_secret = existing.tilda_order_secret

    db.add_tenant(
        shop_id=shop_id,
        bank_login=body.bank_login.strip(),
        bank_password=bank_password,
        bank_terminal_id=body.bank_terminal_id.strip(),
        tilda_login=body.bank_terminal_id.strip(),
        tilda_order_secret=tilda_secret,
        tilda_notify_url=body.tilda_notify_url.strip(),
        bank_env=body.bank_env,
        bank_owner_type=body.bank_owner_type,
        tilda_success_url=body.tilda_success_url.strip(),
        tilda_fail_url=body.tilda_fail_url.strip(),
        inn=body.inn.strip(),
    )
    return _tenant_summary(db.get_tenant(shop_id))


@router.delete("/admin/api/tenants/{shop_id}", dependencies=[Depends(require_admin)])
async def delete_tenant_api(shop_id: str):
    if db.get_tenant(shop_id) is None:
        raise HTTPException(status_code=404, detail="Точка не найдена")
    db.delete_tenant(shop_id)
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
<style>
  :root{
    --bg:#F3F6EE; --surface:#FFFFFF; --ink:#17261B; --ink-dim:#4B5A47; --ink-faint:#8B9686;
    --line:#DCE4D1; --brand:#6FAE23; --brand-dark:#4C8016; --coral:#D2454E; --coral-dim:#FBE8E7;
  }
  *{box-sizing:border-box;}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,Segoe UI,Arial,sans-serif;}
  .wrap{max-width:880px;margin:0 auto;padding:32px 20px 80px;}
  h1{font-size:22px;margin:0 0 4px;}
  .sub{color:var(--ink-dim);font-size:13.5px;margin-bottom:24px;}
  #loginBox{max-width:380px;margin:80px auto;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:24px;}
  #loginBox h2{font-size:16px;margin-top:0;}
  input, select{width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:7px;font-size:13.5px;background:#fff;color:var(--ink);}
  label{display:block;font-size:12.5px;color:var(--ink-dim);margin:10px 0 4px;}
  button{cursor:pointer;border:none;border-radius:7px;padding:9px 16px;font-size:13.5px;font-weight:600;}
  .btn-primary{background:var(--brand);color:#fff;}
  .btn-primary:hover{background:var(--brand-dark);}
  .btn-ghost{background:transparent;color:var(--ink-dim);border:1px solid var(--line);}
  .btn-danger{background:var(--coral-dim);color:var(--coral);}
  table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--line);border-radius:10px;overflow:hidden;}
  th,td{text-align:left;padding:10px 12px;font-size:13px;border-bottom:1px solid var(--line);}
  th{color:var(--ink-faint);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em;}
  tr:last-child td{border-bottom:none;}
  .row-actions{display:flex;gap:6px;}
  .toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;}
  .modal-bg{position:fixed;inset:0;background:rgba(23,38,27,.35);display:flex;align-items:flex-start;justify-content:center;padding:40px 16px;overflow:auto;}
  .modal{background:var(--surface);border-radius:12px;padding:24px;max-width:520px;width:100%;}
  .modal h2{margin-top:0;font-size:17px;}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:0 12px;}
  .hint{font-size:11.5px;color:var(--ink-faint);margin-top:3px;}
  .modal-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:20px;}
  .checkout-url{font-family:monospace;font-size:11.5px;background:#F3F6EE;border:1px dashed var(--line);padding:8px 10px;border-radius:6px;word-break:break-all;margin-top:6px;}
  .hidden{display:none !important;}
  .error{color:var(--coral);font-size:12.5px;margin-top:8px;}
  .empty{padding:30px;text-align:center;color:var(--ink-faint);font-size:13.5px;}
</style>
</head>
<body>

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
    <button class="btn-ghost" onclick="logout()">Выйти</button>
    <button class="btn-primary" onclick="openForm(null)">+ Добавить точку</button>
  </div>
  <div id="tableWrap"></div>
</div>

<div class="modal-bg hidden" id="modalBg">
  <div class="modal">
    <h2 id="modalTitle">Новая точка</h2>
    <label>shop_id</label>
    <input id="f_shop_id" placeholder="shop2">
    <div class="hint">Короткий идентификатор — часть API URL, после создания не меняется.</div>

    <div class="grid2">
      <div><label>Логин банка</label><input id="f_bank_login" placeholder="+79000000001"></div>
      <div><label>Терминал ID</label><input id="f_bank_terminal_id" placeholder="279"></div>
    </div>
    <label>Пароль банка</label>
    <input id="f_bank_password" type="password" placeholder="(оставьте пустым, чтобы не менять)">

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
    <label>ИНН</label>
    <input id="f_inn" placeholder="7727401209">

    <div class="error" id="formError"></div>
    <div class="modal-actions">
      <button class="btn-ghost" onclick="closeForm()">Отмена</button>
      <button class="btn-primary" onclick="saveTenant()">Сохранить</button>
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

async function boot() {
  try {
    const tenants = await api('/admin/api/tenants');
    document.getElementById('loginBox').classList.add('hidden');
    document.getElementById('mainBox').classList.remove('hidden');
    renderTable(tenants);
  } catch (e) {
    if (e.message !== 'unauthorized') {
      document.getElementById('loginError').textContent = 'Ошибка: ' + e.message;
    }
  }
}

function renderTable(tenants) {
  const wrap = document.getElementById('tableWrap');
  if (!tenants.length) {
    wrap.innerHTML = '<div class="empty">Точек пока нет — нажмите «Добавить точку».</div>';
    return;
  }
  const rows = tenants.map(t => `
    <tr>
      <td><b>${t.shop_id}</b><div class="checkout-url">${t.checkout_url}</div></td>
      <td>${t.bank_env}</td>
      <td>${t.bank_login}<br><span style="color:var(--ink-faint)">терминал ${t.bank_terminal_id}</span></td>
      <td>${t.inn || '<span style="color:var(--coral)">нет ИНН</span>'}</td>
      <td class="row-actions">
        <button class="btn-ghost" onclick="openForm('${t.shop_id}')">Изменить</button>
        <button class="btn-danger" onclick="removeTenant('${t.shop_id}')">Удалить</button>
      </td>
    </tr>
  `).join('');
  wrap.innerHTML = `<table>
    <tr><th>Точка</th><th>Среда</th><th>Банк</th><th>ИНН</th><th></th></tr>
    ${rows}
  </table>`;
}

async function openForm(shopId) {
  editingShopId = shopId;
  document.getElementById('formError').textContent = '';
  document.getElementById('modalTitle').textContent = shopId ? `Изменить: ${shopId}` : 'Новая точка';
  const ids = ['bank_login','bank_password','bank_terminal_id','bank_owner_type','bank_env',
               'tilda_secret','tilda_notify_url','tilda_success_url','tilda_fail_url','inn'];
  ids.forEach(id => document.getElementById('f_' + id).value = '');
  document.getElementById('f_shop_id').value = '';
  document.getElementById('f_shop_id').disabled = false;

  if (shopId) {
    const t = await api('/admin/api/tenants/' + encodeURIComponent(shopId));
    document.getElementById('f_shop_id').value = t.shop_id;
    document.getElementById('f_shop_id').disabled = true;
    document.getElementById('f_bank_login').value = t.bank_login;
    document.getElementById('f_bank_terminal_id').value = t.bank_terminal_id;
    document.getElementById('f_bank_owner_type').value = t.bank_owner_type;
    document.getElementById('f_bank_env').value = t.bank_env;
    document.getElementById('f_tilda_notify_url').value = t.tilda_notify_url;
    document.getElementById('f_tilda_success_url').value = t.tilda_success_url;
    document.getElementById('f_tilda_fail_url').value = t.tilda_fail_url;
    document.getElementById('f_inn').value = t.inn;
    document.getElementById('f_bank_password').placeholder = t.bank_password_set
      ? '•••••• (задан — оставьте пустым, чтобы не менять)' : 'обязательно';
    document.getElementById('f_tilda_secret').placeholder = t.tilda_secret_set
      ? '•••••• (задан — оставьте пустым, чтобы не менять)' : 'обязательно';
  }
  document.getElementById('modalBg').classList.remove('hidden');
}

function closeForm() {
  document.getElementById('modalBg').classList.add('hidden');
}

async function saveTenant() {
  const shopId = document.getElementById('f_shop_id').value.trim();
  if (!shopId) {
    document.getElementById('formError').textContent = 'Укажите shop_id.';
    return;
  }
  const body = {
    bank_login: document.getElementById('f_bank_login').value.trim(),
    bank_password: document.getElementById('f_bank_password').value,
    bank_terminal_id: document.getElementById('f_bank_terminal_id').value.trim(),
    bank_owner_type: document.getElementById('f_bank_owner_type').value,
    bank_env: document.getElementById('f_bank_env').value,
    tilda_secret: document.getElementById('f_tilda_secret').value,
    tilda_notify_url: document.getElementById('f_tilda_notify_url').value.trim(),
    tilda_success_url: document.getElementById('f_tilda_success_url').value.trim(),
    tilda_fail_url: document.getElementById('f_tilda_fail_url').value.trim(),
    inn: document.getElementById('f_inn').value.trim(),
  };
  try {
    await api('/admin/api/tenants/' + encodeURIComponent(shopId), { method: 'PUT', body: JSON.stringify(body) });
    closeForm();
    boot();
  } catch (e) {
    document.getElementById('formError').textContent = 'Ошибка: ' + e.message;
  }
}

async function removeTenant(shopId) {
  if (!confirm(`Удалить точку "${shopId}"? Действие необратимо.`)) return;
  try {
    await api('/admin/api/tenants/' + encodeURIComponent(shopId), { method: 'DELETE' });
    boot();
  } catch (e) {
    alert('Ошибка: ' + e.message);
  }
}

if (adminKey) { boot(); }
</script>
</body>
</html>
"""
