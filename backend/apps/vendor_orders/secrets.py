"""叫貨金鑰的加密與比對。資料庫只放加密過的;原文只在要打廠商的那一刻拿出來,不寫進紀錄、錯誤訊息、任何回應。"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

from .models import VendorSecret

HINT_CHARS = 12


def _wrapper() -> Fernet:
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"mppos-vendor-key-wrap-v1",
    ).derive(settings.SECRET_KEY.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def fingerprint(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def store(link, raw: str, user=None, sandbox=None) -> VendorSecret:
    secret, _ = VendorSecret.objects.update_or_create(
        link=link,
        defaults={
            "tenant": link.tenant,
            "wrapped": _wrapper().encrypt(raw.encode("utf-8")).decode("ascii"),
            "hint": raw[:HINT_CHARS],
            "fingerprint": fingerprint(raw),
            "sandbox": sandbox,
            "set_by": user,
        },
    )
    return secret


def reveal(link) -> str | None:
    """這家門市的金鑰原文;沒設、或系統金鑰換過讀不出來 → None(一律當成沒設,請管理員重新貼)。"""
    secret = VendorSecret.objects.filter(link=link).first()
    if secret is None:
        return None
    try:
        return _wrapper().decrypt(secret.wrapped.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
