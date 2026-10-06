"""建單端點:同一份請求只成立一次。

工作台版型的畫面按「確認」之後,如果連線在半路斷掉,畫面不知道那張單到底有沒有成立。
以前只能回頭「找找看有沒有一張長得一樣的」(調撥頁就是這樣),銷貨收了錢更不能靠猜。
現在畫面每開一張新的單就自己產生一把鑰匙,送出時放在 `Idempotency-Key`;不確定時拿同一把再送:

- 第一次:照常建單,把「這把鑰匙 → 這個單號」記下來(跟建單在同一個交易裡,要嘛都有、要嘛都沒有)。
- 同一把再來:不建單,直接回已經成立的那一張(HTTP 200,多一個 `Idempotent-Replay: true`)。
- 第一次其實失敗了(資料不對被擋):鑰匙沒有留下來,改一改用同一把再送就是一次新的建單。
- 兩個請求同時帶同一把:後到的會等先到的做完,然後拿到同一張。

沒有帶鑰匙的請求跟以前完全一樣。
"""
import re
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import IdempotencyKey

HEADER = "Idempotency-Key"
KEEP_DAYS = 7
_KEY_RE = re.compile(r"[A-Za-z0-9_\-]{8,64}")


class IdempotentCreateMixin:
    """放在 viewset 繼承清單的最前面;`idempotency_scope` 填這個端點建的是哪一種單。"""

    idempotency_scope = ""

    def create(self, request, *args, **kwargs):
        key = (request.headers.get(HEADER) or "").strip()
        if not key:
            return super().create(request, *args, **kwargs)
        if not _KEY_RE.fullmatch(key):
            raise ValidationError({"detail": "Idempotency-Key 格式不對"})
        tenant = request.tenant
        with transaction.atomic():
            record = self._claim(tenant, key, request.user)
            if record.doc_no:
                existing = self.get_queryset().filter(no=record.doc_no).first()
                if existing is not None:
                    return Response(
                        self.get_serializer(existing).data,
                        status=status.HTTP_200_OK,
                        headers={"Idempotent-Replay": "true"},
                    )
                # 單號記著但單不在了(例如還原到更早的備份):當成新的一次
            response = super().create(request, *args, **kwargs)
            if response.status_code >= 400:
                # 沒有用例外、直接回錯誤的情形:單沒成立,鑰匙也不能留下
                transaction.set_rollback(True)
                return response
            record.doc_no = str(response.data.get("no") or "")
            record.save(update_fields=["doc_no", "updated_at"])
            return response

    def _claim(self, tenant, key, user):
        """拿到這把鑰匙的那一列(新的或既有的),並且鎖住它直到交易結束。"""
        scope = self.idempotency_scope
        who = user if getattr(user, "is_authenticated", False) else None
        try:
            # 包一層 savepoint:撞到唯一限制時外層交易還能繼續用
            with transaction.atomic():
                record = IdempotencyKey.objects.create(
                    tenant=tenant, scope=scope, key=key, created_by=who
                )
        except IntegrityError:
            # 同一把鑰匙已經有人用過(或同時送進來、先到的剛做完):拿它那一列
            return IdempotencyKey.objects.select_for_update().get(
                tenant=tenant, scope=scope, key=key
            )
        # 順手清掉過期的(不會再有人拿那麼舊的鑰匙重送)
        IdempotencyKey.objects.filter(
            created_at__lt=timezone.now() - timedelta(days=KEEP_DAYS)
        ).delete()
        return record
