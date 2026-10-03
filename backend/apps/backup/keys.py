"""復原憑證:產生、顯示、保管。

憑證是伺服器產生的 160 bits 亂數,給人看的寫法是 `MP-XXXX-XXXX-…`(8 組 4 碼,
只用不會看錯的字元)。伺服器存的是用系統金鑰包過的密文,這樣平常備份不用每次
請管理員輸入;而管理員手上抄的那一份,是原伺服器壞掉時唯一能解開備份的東西。

憑證不寫進日誌、不放進備份檔、不放進操作紀錄。
"""
import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

from .models import BackupKey

# Crockford base32:沒有 I L O U,抄寫時不會跟 1 0 V 搞混
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_SECRET_BYTES = 20
PREFIX = "MP"


class KeyError_(Exception):
    """憑證格式不對或讀不出來。"""


def _wrapper() -> Fernet:
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None,
        info=b"mppos-backup-key-wrap-v1",
    ).derive(settings.SECRET_KEY.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def format_secret(secret: bytes) -> str:
    n = int.from_bytes(secret, "big")
    chars = []
    for _ in range(_SECRET_BYTES * 8 // 5):
        chars.append(_ALPHABET[n & 31])
        n >>= 5
    text = "".join(reversed(chars))
    return PREFIX + "-" + "-".join(text[i:i + 4] for i in range(0, len(text), 4))


def parse_secret(text: str) -> bytes:
    """把人輸入的憑證轉回位元組。大小寫、空白、連字號、容易看錯的字都容忍。"""
    s = (text or "").upper().strip()
    if s.startswith(PREFIX + "-") or s.startswith(PREFIX + " "):
        s = s[len(PREFIX):]
    s = "".join(ch for ch in s if ch.isalnum())
    s = s.replace("O", "0").replace("I", "1").replace("L", "1")
    if len(s) != _SECRET_BYTES * 8 // 5 or any(ch not in _ALPHABET for ch in s):
        raise KeyError_("復原憑證格式不對,請確認有沒有抄漏")
    n = 0
    for ch in s:
        n = (n << 5) | _ALPHABET.index(ch)
    return n.to_bytes(_SECRET_BYTES, "big")


def fingerprint(secret: bytes) -> str:
    """給人對照用的 8 碼短碼。**不能**拿來判斷是不是同一組憑證(太短)。"""
    return hashlib.sha256(b"mppos-backup-fp:" + secret).hexdigest()[:8].upper()


def identity(secret: bytes) -> str:
    """這組憑證的完整雜湊。憑證本身是 160 bits 亂數,從雜湊推不回去。"""
    return hashlib.sha256(b"mppos-backup-id:" + secret).hexdigest()


def is_same(key, secret: bytes) -> bool:
    """`secret` 是不是這家公司登記的那一組。"""
    if key.secret_hash:
        return hmac.compare_digest(key.secret_hash, identity(secret))
    # 加上完整雜湊之前建立的紀錄:伺服器那份讀得出來就直接比內容
    try:
        stored = _wrapper().decrypt(key.wrapped.encode())
    except InvalidToken:
        return False        # 沒有完整雜湊、又讀不出來:無從證明是同一組,一律不收
    return hmac.compare_digest(stored, secret)


def get_secret(tenant) -> bytes | None:
    """這家公司存在伺服器上的憑證;沒有或讀不出來回 None。"""
    key = BackupKey.objects.filter(tenant=tenant).first()
    if key is None:
        return None
    try:
        return _wrapper().decrypt(key.wrapped.encode())
    except InvalidToken:
        # 系統金鑰(SECRET_KEY)換過:伺服器這份讀不出來,要請管理員重新輸入憑證
        return None


def create_key(tenant, user=None):
    """產生新憑證(已經有就丟錯,不會悄悄換掉 —— 換掉會讓舊備份解不開)。
    回傳 (BackupKey, 給人看的憑證字串)。字串只在這裡回一次。"""
    if BackupKey.objects.filter(tenant=tenant).exists():
        raise KeyError_("這家公司已經有復原憑證了")
    secret = secrets.token_bytes(_SECRET_BYTES)
    key = BackupKey.objects.create(
        tenant=tenant,
        wrapped=_wrapper().encrypt(secret).decode(),
        fingerprint=fingerprint(secret),
        secret_hash=identity(secret),
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    return key, format_secret(secret)


def register_key(tenant, text: str, user=None):
    """把管理員手上的憑證登記到這台伺服器(新環境復原、或系統金鑰換過之後)。"""
    secret = parse_secret(text)
    existing = BackupKey.objects.filter(tenant=tenant).first()
    if existing is not None and not is_same(existing, secret):
        # 不管伺服器那份現在讀不讀得出來,都不能被另一組換掉:之後的備份會改用
        # 新的那組加密,管理員手上抄的舊憑證就打不開了。
        raise KeyError_("這跟這家公司原本的復原憑證不是同一組")
    key, _ = BackupKey.objects.update_or_create(
        tenant=tenant,
        defaults={
            "wrapped": _wrapper().encrypt(secret).decode(),
            "fingerprint": fingerprint(secret),
            "secret_hash": identity(secret),
            "created_by": user if getattr(user, "is_authenticated", False) else None,
        },
    )
    return key
