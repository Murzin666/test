"""
Глобальные настройки сервиса (не зависят от конкретной торговой точки).
Настройки самих торговых точек — в app/db.py (хранятся в БД, чувствительные
поля зашифрованы).
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

HOSTS = {
    "test": {
        "api": "https://devpg.centrinvest.ru:8043",
        "flex": "https://devpg.centrinvest.ru:8143/flex",
    },
    "prod": {
        "api": "https://apipg.centrinvest.ru",
        "flex": "https://pg.centrinvest.ru/flex",
    },
}


class GlobalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    public_base_url: str = "http://localhost:8000"
    admin_api_key: str = ""
    allowed_origins: str = "http://localhost:8000"

    # Путь к файлу базы данных SQLite. На Railway должен указывать на
    # смонтированный Volume (например, /data/tenants.db), иначе данные
    # исчезнут при следующем деплое — контейнер эфемерный.
    db_path: str = "./tenants.db"

    # Ключ шифрования чувствительных полей (пароль банка, секрет Tilda).
    # Сгенерировать: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str = ""

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> GlobalSettings:
    return GlobalSettings()
