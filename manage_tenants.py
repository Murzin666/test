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
        default_tax_rate=args.default_tax_rate,
        default_item_type=args.default_item_type,
        default_calc_mode=args.default_calc_mode,
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
    print(f"tax_system_code:     {tenant.tax_system_code}")
    print(f"default_tax_rate:    {tenant.default_tax_rate}")
    print(f"default_item_type:   {tenant.default_item_type}")
    print(f"default_calc_mode:   {tenant.default_calc_mode}")
    products = db.list_products(args.shop_id)
    print(f"products ({len(products)}):")
    for p in products:
        print(f"  {p['name']!r}: taxRate={p['tax_rate']} type={p['item_type']} mode={p['calc_mode']}")


def cmd_remove(args: argparse.Namespace) -> None:
    db.init_db()
    db.delete_tenant(args.shop_id)
    print(f"Точка '{args.shop_id}' удалена.")


def cmd_product_add(args: argparse.Namespace) -> None:
    db.init_db()
    if db.get_tenant(args.shop_id) is None:
        print(f"Точка '{args.shop_id}' не найдена — сначала добавьте её командой add.", file=sys.stderr)
        sys.exit(1)
    db.add_product(args.shop_id, args.name, args.tax_rate, args.item_type, args.calc_mode)
    print(f"Товар {args.name!r} для точки '{args.shop_id}' сохранён: "
          f"taxRate={args.tax_rate}, type={args.item_type}, mode={args.calc_mode}")


def cmd_product_list(args: argparse.Namespace) -> None:
    db.init_db()
    products = db.list_products(args.shop_id)
    if not products:
        print(f"У точки '{args.shop_id}' пока нет товаров в каталоге.")
        return
    for p in products:
        print(f"{p['name']!r}: taxRate={p['tax_rate']} type={p['item_type']} mode={p['calc_mode']}")


def cmd_product_remove(args: argparse.Namespace) -> None:
    db.init_db()
    db.delete_product(args.shop_id, args.name)
    print(f"Товар {args.name!r} удалён из каталога точки '{args.shop_id}'.")


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
    p_add.add_argument("--default-tax-rate", dest="default_tax_rate", default="6",
                        help="Ставка НДС по умолчанию для товаров без записи в каталоге (см. tilda-integration/fiscal-receipt.md)")
    p_add.add_argument("--default-item-type", dest="default_item_type", default="1",
                        help="Признак предмета расчёта по умолчанию (1=Товар, 4=Услуга и т.д.)")
    p_add.add_argument("--default-calc-mode", dest="default_calc_mode", default="4",
                        help="Признак способа расчёта по умолчанию (4=Полный расчёт и т.д.)")
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

    p_product = sub.add_parser("product", help="Управление каталогом товаров точки (налоговые атрибуты чека)")
    product_sub = p_product.add_subparsers(dest="product_command", required=True)

    p_product_add = product_sub.add_parser("add", help="Добавить/обновить товар")
    p_product_add.add_argument("shop_id")
    p_product_add.add_argument("name", help="Название товара — должно совпадать с тем, что передаёт Tilda")
    p_product_add.add_argument("--tax-rate", required=True, dest="tax_rate")
    p_product_add.add_argument("--type", required=True, dest="item_type")
    p_product_add.add_argument("--mode", required=True, dest="calc_mode")
    p_product_add.set_defaults(func=cmd_product_add)

    p_product_list = product_sub.add_parser("list", help="Показать товары точки")
    p_product_list.add_argument("shop_id")
    p_product_list.set_defaults(func=cmd_product_list)

    p_product_remove = product_sub.add_parser("remove", help="Удалить товар из каталога")
    p_product_remove.add_argument("shop_id")
    p_product_remove.add_argument("name")
    p_product_remove.set_defaults(func=cmd_product_remove)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
