"""同一個帳號同一時間只能在一個位置登入(owner 2026-10-24:「同一時間只允許同一帳號登入一個位置,登入新位置,自動踢掉舊位置」)。

- 位置 = 一個瀏覽器(畫面送來的記號,`frontend/src/api/client.ts` 的 `deviceId()`)。同一個瀏覽器另開分頁、關掉再開
  重新登入拿回原本那一把 token,不會把自己踢掉。
- 換一個位置登入:舊的 token 刪掉、雜湊記進 `SignedOutElsewhere`,舊位置下一次呼叫拿到 401 + `signed_in_elsewhere`
  (`apps/backup/auth.py`),畫面跳回登入頁、寫「帳號已在別處登入」。被拒的那一下沒有做(驗證在任何動作之前)。
- 沒送記號(舊版畫面、瀏覽器不給存)= 每次都當新位置。
- 每個帳號都一樣(老闆、平台管理員也是;紅隊:開了例外大家就擠去用那個帳號)。
- 刻意不做:登入前先問要不要踢、登入紀錄 / 裝置清單、限制哪幾台能登入、告訴被踢的人是哪一台。
"""
import hashlib
import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.authtoken.models import Token

from .models import SignedOutElsewhere, SignInPlace

ELSEWHERE_CODE = "signed_in_elsewhere"
ELSEWHERE_TEXT = "帳號已在別處登入"
KEEP_DAYS = 14
_DEVICE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def clean_device(value) -> str:
    """畫面送來的位置記號;格式不對或沒送回空字串(= 每次都當新位置)。"""
    return value if isinstance(value, str) and _DEVICE.match(value) else ""


def sign_in(user, device: str) -> Token:
    """登入拿 token:同一個位置拿回原本那一把;換位置就把舊的作廢、發新的。"""
    with transaction.atomic():
        # 同一個帳號同時在兩個地方登入:一個一個來(不然兩邊都看到舊的、都去建新的,後到的撞「一個帳號一把」)
        get_user_model().objects.select_for_update().only("pk").get(pk=user.pk)
        token = Token.objects.filter(user=user).first()
        place = SignInPlace.objects.filter(user=user).first()
        if token is not None and device and place is not None and place.device == device:
            return token
        if token is not None:
            SignedOutElsewhere.objects.update_or_create(digest=digest(token.key), defaults={"user": user})
            token.delete()
        SignedOutElsewhere.objects.filter(at__lt=timezone.now() - timedelta(days=KEEP_DAYS)).delete()
        SignInPlace.objects.update_or_create(user=user, defaults={"device": device})
        return Token.objects.create(user=user)


def signed_out_elsewhere(key: str) -> bool:
    """這把 token 是不是被別處登入作廢的。"""
    return SignedOutElsewhere.objects.filter(digest=digest(key)).exists()
