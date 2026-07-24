#!/usr/bin/env python3
"""
Управление торговыми точками (tenants) вручную из командной строки.

Локально:
    python3 manage_tenants.py add shop1 --bank-login "+79000000001" \
        --bank-password "секрет_банка" --terminal-id 279 \
        --tilda-secret "секрет_из_формы_tilda" \
        --notify-url "https://forms.tildaapi.one/payment/custom/psXXXXXXX"

    python3 manage_tenants.py list
    python3 manage_tenants.py show shop1
    python3 manage_tenants.py remove shop1

На Railway (без захода по SSH) — через Railway CLI, которое выполняет
команду уже в окружении с доступом к вашей БД и ENCRYPTION_KEY:
    railway run python manage_tenants.py add shop1 --bank-login ...
"""
import argparse
import sys

from app import db


def cmd_add(args: argparse.Namespace) -> None:
    db.init_db()
    db.add_tenant(
        shop_id=args.shop_id,
        bank_login=args.bank_login,
        bank_password=args.bank_password,
        bank_terminal_id=args.terminal_id,
        tilda_login=args.terminal_id,
        tilda_order_secret=args.tilda_secret,
        tilda_notify_url=args.notify_url,
        bank_env=args.bank_env,
        bank_owner_type=args.owner_type,
        tilda_success_url=args.success_url or "",
        tilda_fail_url=args.fail_url or "",
        inn=args.inn or "",
        merchant_name=args.merchant_name or "",
        terminal_number=args.terminal_number or "",
    )
    print(f"Точка '{args.shop_id}' сохранена.")
    print(f"API URL для формы Tilda: {args.public_base_url}/tilda/{args.shop_id}/checkout")
    if not args.inn:
        print(
            "ВНИМАНИЕ: ИНН (--inn) не указан — чек для банка формироваться не будет, "
            "банк применит свои настройки терминала по умолчанию."
        )


def cmd_list(_: argparse.Namespace) -> None:
    db.init_db()
    tenants = db.list_tenants()
    if not tenants:
        print("Торговых точек пока нет.")
        return
    for shop_id in tenants:
        print(shop_id)


def cmd_show(args: argparse.Namespace) -> None:
    db.init_db()
    tenant = db.get_tenant(args.shop_id)
    if tenant is None:
        print(f"Точка '{args.shop_id}' не найдена.", file=sys.stderr)
        sys.exit(1)
    print(f"shop_id:            {tenant.shop_id}")
    print(f"bank_env:            {tenant.bank_env}")
    print(f"bank_owner_type:     {tenant.bank_owner_type}")
    print(f"bank_login:          {tenant.bank_login}")
    print(f"bank_password:       {'*' * len(tenant.bank_password)}")
    print(f"bank_terminal_id:    {tenant.bank_terminal_id}")
    print(f"tilda_login:         {tenant.tilda_login}")
    print(f"tilda_order_secret:  {'*' * len(tenant.tilda_order_secret)}")
    print(f"tilda_notify_url:    {tenant.tilda_notify_url}")
    print(f"tilda_success_url:   {tenant.tilda_success_url}")
    print(f"tilda_fail_url:      {tenant.tilda_fail_url}")
    print(f"inn:                 {tenant.inn or '(не задан — чек не формируется)'}")
    print(f"merchant_name:       {tenant.merchant_name or '(не задано)'}")
    print(f"terminal_number:     {tenant.terminal_number or '(не задан)'}")


def cmd_remove(args: argparse.Namespace) -> None:
    db.init_db()
    db.delete_tenant(args.shop_id)
    print(f"Точка '{args.shop_id}' удалена.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Управление торговыми точками")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Добавить или обновить точку")
    p_add.add_argument("shop_id", help="Короткий идентификатор точки, например shop1")
    p_add.add_argument("--bank-login", required=True)
    p_add.add_argument("--bank-password", required=True)
    p_add.add_argument("--terminal-id", required=True, dest="terminal_id",
                        help="ID терминала банка — используется и как логин для формы Tilda (tilda_login)")
    p_add.add_argument("--owner-type", default="MultiMerchant")
    p_add.add_argument("--bank-env", default="test", choices=["test", "prod"])
    p_add.add_argument("--tilda-secret", required=True)
    p_add.add_argument("--notify-url", required=True, dest="notify_url")
    p_add.add_argument("--success-url", dest="success_url", default="")
    p_add.add_argument("--fail-url", dest="fail_url", default="")
    p_add.add_argument(
        "--inn",
        dest="inn",
        default="",
        help="ИНН точки — обязателен, если хотите, чтобы сервер формировал чек (иначе банк применит свои дефолты терминала)",
    )
    p_add.add_argument(
        "--merchant-name",
        dest="merchant_name",
        default="",
        help="Название ТСП (торгово-сервисного предприятия) — для удобства идентификации точки",
    )
    p_add.add_argument(
        "--terminal-number",
        dest="terminal_number",
        default="",
        help="Номер терминала (не путать с Терминал ID для банка) — для удобства идентификации точки",
    )
    p_add.add_argument(
        "--public-base-url",
        dest="public_base_url",
        default="https://ваш-проект.up.railway.app",
        help="Только для вывода подсказки с готовым API URL",
    )
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="Показать все shop_id")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Показать настройки точки (секреты замаскированы)")
    p_show.add_argument("shop_id")
    p_show.set_defaults(func=cmd_show)

    p_remove = sub.add_parser("remove", help="Удалить точку")
    p_remove.add_argument("shop_id")
    p_remove.set_defaults(func=cmd_remove)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
