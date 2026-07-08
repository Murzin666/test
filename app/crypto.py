"""
Шифрование чувствительных полей торговых точек (пароль банка, секрет Tilda)
перед сохранением в БД. Используется симметричное шифрование Fernet
(AES-128 в CBC + HMAC) из библиотеки cryptography.

Ключ шифрования (ENCRYPTION_KEY) хранится ОТДЕЛЬНО от БД — как переменная
окружения. Тот, кто получит доступ только к файлу БД (например, к бэкапу),
без ключа не сможет расшифровать пароли.
"""
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().encryption_key
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY не задан. Сгенерируйте его: "
            "python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" "
            "и добавьте как переменную окружения ENCRYPTION_KEY."
        )
    return Fernet(key.encode("utf-8") if isinstance(key, str) else key)


def encrypt(plain_text: str) -> str:
    return _fernet().encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt(encrypted_text: str) -> str:
    try:
        return _fernet().decrypt(encrypted_text.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError(
            "Не удалось расшифровать данные — неверный ENCRYPTION_KEY "
            "(отличается от того, которым данные были зашифрованы)."
        ) from exc
