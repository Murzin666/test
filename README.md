# Сервер-посредник Tilda ↔ API банка «Центр-инвест» (мультитенантный)

FastAPI-приложение, которое прячет ключи терминала от браузера, проверяет
подпись заказов от Tilda и общается с банком от имени сразу нескольких
торговых точек. Подключение к сайтам на Tilda — через официальную
Универсальную платёжную систему, подробности в `tilda-integration/`.

## 1. Установка

```bash
cd bank-proxy
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Настройка глобальных переменных

```bash
cp .env.example .env
```

Заполните `.env`:
- `PUBLIC_BASE_URL` — адрес сервера (для локального теста можно оставить
  `http://localhost:8000`, для прода — ваш Railway-домен)
- `ADMIN_API_KEY` — длинная случайная строка для служебных операций
- `DB_PATH` — путь к файлу SQLite (локально можно оставить `./tenants.db`;
  на Railway — обязательно путь на смонтированный Volume, см.
  `tilda-integration/multi-tenant.md`)
- `ENCRYPTION_KEY` — сгенерировать: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

Логины/пароли банка и секреты Tilda сюда **не входят** — это настройки
конкретной точки, добавляются отдельно (шаг 4).

## 3. Запуск сервера

```bash
uvicorn app.main:app --reload --port 8000
```

```bash
curl http://localhost:8000/api/health
# {"ok":true,"tenants":[]}
```

Автосгенерированная документация: http://localhost:8000/docs

## 4. Добавление торговой точки

```bash
python3 manage_tenants.py add shop1 \
  --bank-login "+79040001313" \
  --bank-password "секрет_банка" \
  --terminal-id 279 \
  --tilda-login 279 \
  --tilda-secret "секрет_из_формы_tilda" \
  --notify-url "https://forms.tildaapi.one/payment/custom/psXXXXXXX"
```

Команда выведет готовый **API URL** — его нужно вставить в форму
Универсальной платёжной системы на Tilda (подробности —
`tilda-integration/universal-payment-system.md`).

Другие команды: `manage_tenants.py list`, `show <shop_id>`, `remove <shop_id>`.

## 5. Подключение к Tilda

Полная пошаговая инструкция — в папке `tilda-integration/`:
- `universal-payment-system.md` — настройка формы на Tilda
- `multi-tenant.md` — Railway Volume, ключ шифрования, несколько точек

## 6. Служебные операции (возврат / реверс / статус)

Требуют заголовок `X-Admin-Key` — не вызывайте их с публичного фронтенда:

```bash
# Статус заказа
curl -H "X-Admin-Key: <ADMIN_API_KEY>" \
  "http://localhost:8000/api/shop1/orders/<order_id>/status"

# Возврат оплаченного заказа
curl -X POST -H "X-Admin-Key: <ADMIN_API_KEY>" \
  "http://localhost:8000/api/shop1/orders/<order_id>/refund?amount=100.00"

# Реверс (void) оплаты в тот же день
curl -X POST -H "X-Admin-Key: <ADMIN_API_KEY>" \
  "http://localhost:8000/api/shop1/orders/<order_id>/void"
```

`refund` может вернуть отказ банка (`PmoDecline`), если на терминале не
включена операция «Merchandise Return» — это настройка на стороне банка,
не баг сервера.

## 7. Деплой на Railway

```bash
git init && git add . && git commit -m "bank proxy"
git branch -M main
git remote add origin <ссылка на ваш пустой репозиторий на GitHub>
git push -u origin main
```

На [railway.app](https://railway.app): New Project → Deploy from GitHub repo.
Обязательно подключите **Volume** (Settings → Volumes, Mount Path `/data`) и
укажите `DB_PATH=/data/tenants.db` — иначе все точки и заказы пропадут при
следующем деплое. Остальные переменные — как в `.env.example`.

Добавление точек на уже задеплоенный сервер — через Railway CLI:
```bash
railway run python manage_tenants.py add shop2 --bank-login ... 
```

## Что доделать перед серьёзной нагрузкой

1. **Идемпотентность** — если Tilda или покупатель повторно дёрнут
   `/tilda/<shop_id>/checkout` для одного и того же `order_id`, сейчас
   создастся второй заказ в банке. Стоит проверять `db.get_tilda_link` перед
   созданием нового заказа в банке.
2. **Логирование** — добавить логи обращений к банку и к Tilda notify-url
   (без самих логинов/паролей) для разбора спорных ситуаций.
3. **Резервное копирование БД** — файл на Volume не бэкапится Railway
   автоматически, стоит настроить периодический экспорт.
