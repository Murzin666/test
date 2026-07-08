"""
Подпись запросов по протоколу Универсальной платёжной системы Tilda.

Правило подписи настроено в личном кабинете Tilda как:
  Особые правила: {{login}}{{order_id}}{{order_amount}}
  Алгоритм: SHA-256, секрет используется как HMAC-ключ

Один и тот же алгоритм используется и для проверки входящего запроса
("API URL"), и для подписи исходящего уведомления об оплате.
"""
import hmac
import hashlib


def compute_signature(secret: str, login: str, order_id: str, order_amount: str) -> str:
    message = f"{login}{order_id}{order_amount}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_signature(secret: str, login: str, order_id: str, order_amount: str, signature: str) -> bool:
    expected = compute_signature(secret, login, order_id, order_amount)
    return hmac.compare_digest(expected, signature.strip().lower())
