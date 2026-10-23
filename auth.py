"""
Простая авторизация для учебного проекта.
Пароли хранятся как sha256-хеш (не для продакшена!).
"""
import hashlib
from typing import Optional

def _h(pwd: str) -> str:
    return hashlib.sha256(pwd.encode("utf-8")).hexdigest()

# username -> (password_hash, role)
USERS = {
    "admin":  (_h("admin123"), "admin"),
    "client": (_h("client123"), "client"),
}

def authenticate(username: str, password: str) -> Optional[str]:
    """Возвращает роль при успехе, иначе None."""
    rec = USERS.get(username.strip().lower())
    if rec and rec[0] == _h(password):
        return rec[1]
    return None