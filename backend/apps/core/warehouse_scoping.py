"""WarehouseScopedMixin:把 viewset 限制到當前登入帳號可存取的倉別範圍。

套用對象:任何主 model 有 warehouse FK 的 viewset(銷貨/進貨/雜支/...)。

行為:
- 帳號 profile.is_warehouse_locked == True:
  * list / detail 只回 warehouse == default_warehouse 的單據
  * create:warehouse 不是 default_warehouse 直接 403
- 帳號 profile.is_warehouse_locked == False (例如 tenant_admin / platform_admin):
  * 不做額外過濾(交給 for_tenant 處理 tenant 隔離即可)
- 沒有 profile / 沒有 default_warehouse 但 is_warehouse_locked=True:
  * 視同看不到任何資料(防呆,避免漏設定)

子類可覆寫 `warehouse_field` 來指定 FK 名稱(預設 'warehouse');或
覆寫 `_allowed_warehouse_ids()` 來客製規則(例如 TransferOrder 要看 source OR
destination 都算自己倉)。
"""
from rest_framework.exceptions import PermissionDenied


def report_warehouse_id(request):
    """報表 / 首頁摘要用的門市範圍。

    鎖倉帳號 → 自己門市;鎖倉卻沒有設定門市(設定不完整)→ 403,不能因此變成看全公司;
    沒鎖倉 → 網址的 ?warehouse=(沒帶就是 None = 全公司)。
    """
    profile = getattr(request.user, "profile", None)
    if profile and profile.is_warehouse_locked:
        if not profile.default_warehouse_id:
            raise PermissionDenied("這個帳號鎖定門市但還沒有設定門市")
        return profile.default_warehouse_id
    raw = request.query_params.get("warehouse")
    return int(raw) if raw and raw.isdigit() else None


class WarehouseScopedMixin:
    warehouse_field = "warehouse"

    def _profile(self):
        user = getattr(self.request, "user", None)
        if user and user.is_authenticated:
            return getattr(user, "profile", None)
        return None

    def _allowed_warehouse_ids(self):
        """回傳允許的 warehouse_id list;None 代表不限制。"""
        profile = self._profile()
        if not profile or not profile.is_warehouse_locked:
            return None
        if not profile.default_warehouse_id:
            return []  # 鎖倉但沒設預設倉 → 看不到任何資料
        return [profile.default_warehouse_id]

    def filter_queryset(self, queryset):
        qs = super().filter_queryset(queryset)
        ids = self._allowed_warehouse_ids()
        if ids is not None:
            qs = qs.filter(**{f"{self.warehouse_field}_id__in": ids})
        return qs

    def check_create_warehouse(self, serializer):
        """鎖倉帳號只能在自己門市建單。子類覆寫 perform_create 時要自己呼叫這個。"""
        ids = self._allowed_warehouse_ids()
        if ids is not None:
            wh = serializer.validated_data.get(self.warehouse_field)
            wh_id = getattr(wh, "id", wh)
            if wh_id not in ids:
                raise PermissionDenied(
                    "不可在非自己門市建立資料"
                )

    def perform_create(self, serializer):
        self.check_create_warehouse(serializer)
        return super().perform_create(serializer)

    def perform_update(self, serializer):
        ids = self._allowed_warehouse_ids()
        if ids is not None:
            wh = serializer.validated_data.get(self.warehouse_field)
            if wh is not None:
                wh_id = getattr(wh, "id", wh)
                if wh_id not in ids:
                    raise PermissionDenied(
                        "不可改成非自己門市"
                    )
        return super().perform_update(serializer)


class TransferWarehouseScopedMixin(WarehouseScopedMixin):
    """TransferOrder 特殊版:from 或 to 任一是自己倉就算自己的單。

    建單(派發階段)時,from_warehouse 必須是自己倉。
    確認(confirm action)時權限由 action 自己檢查 to_warehouse == 自己倉。
    """

    source_field = "from_warehouse"
    destination_field = "to_warehouse"

    def filter_queryset(self, queryset):
        # 跳過父類的單一欄位 filter,改用 OR
        qs = super(WarehouseScopedMixin, self).filter_queryset(queryset)
        ids = self._allowed_warehouse_ids()
        if ids is not None:
            from django.db.models import Q

            qs = qs.filter(
                Q(**{f"{self.source_field}_id__in": ids})
                | Q(**{f"{self.destination_field}_id__in": ids})
            )
        return qs

    def check_create_warehouse(self, serializer):
        """調撥:鎖倉帳號只能從自己門市調出。"""
        ids = self._allowed_warehouse_ids()
        if ids is not None:
            src = serializer.validated_data.get(self.source_field)
            src_id = getattr(src, "id", src)
            if src_id not in ids:
                raise PermissionDenied("不可從非自己門市調出")

    def perform_create(self, serializer):
        self.check_create_warehouse(serializer)
        return super(WarehouseScopedMixin, self).perform_create(serializer)
