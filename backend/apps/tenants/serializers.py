from django.utils import timezone
from rest_framework import serializers

from apps.core.tenant_fields import TenantScopedRelatedFieldsMixin

from . import invoice_periods
from .models import InvoiceTrack, InvoiceTrackJump, InvoiceType, PaymentMethod
from .services import track_in_use


class InvoiceTypeSerializer(TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = InvoiceType
        fields = ["id", "code", "name", "sort_order", "is_active", "is_default", "tax_method"]
        read_only_fields = ["id", "code"]


class InvoiceTrackSerializer(TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
    """發票字軌。規則(owner 2026-10-13:字軌設定完、用了一陣子之後出狀況,要能指定從幾號開始印):

    - 新增一定要選門市(每間門市的發票機各有一捲紙)與期別(兩個月一期;開單只取當期的);
      「下一張」只有新增時可以填(那一捲已經用掉幾張)。期別的字(`period_label`)有登記期別的由系統填(`InvoiceTrack.save`)。
    - 之後「下一張」只能用跳號改(`services.jump_invoice_track`,留紀錄、擋重複),這裡直接改會被退回。
    - 已經開過發票或跳過號的:字軌兩碼、起號、類型不能改;迄號不能縮到已經用到的號碼前面。
    - 同一家公司不能有兩條字軌的號碼重疊(同一捲紙登記兩次 = 兩邊開出同一個號碼)。
    """

    invoice_type_code = serializers.CharField(
        source="invoice_type.code", read_only=True
    )
    invoice_type_name = serializers.CharField(
        source="invoice_type.name", read_only=True
    )
    warehouse_name = serializers.SerializerMethodField()
    period_state = serializers.SerializerMethodField()
    is_depleted = serializers.BooleanField(read_only=True)
    next_invoice_no = serializers.SerializerMethodField()
    next_number = serializers.IntegerField(required=False, min_value=0)

    def get_warehouse_name(self, obj) -> str:
        return obj.warehouse.name if obj.warehouse_id else ""

    def get_period_state(self, obj) -> str:
        """這條字軌的期別跟今天比:`past` 過期了、`now` 這一期、`future` 還沒到;沒登記期別的舊字軌是空字串。"""
        if obj.period_start is None:
            return ""
        today = invoice_periods.start_of(timezone.localdate())
        return "now" if obj.period_start == today else "past" if obj.period_start < today else "future"

    def get_next_invoice_no(self, obj):
        if obj.is_depleted:
            return None
        return obj.format_number(obj.next_number)

    class Meta:
        model = InvoiceTrack
        fields = [
            "id",
            "invoice_type",
            "invoice_type_code",
            "invoice_type_name",
            "warehouse",
            "warehouse_name",
            "period_label",
            "period_start",
            "period_state",
            "prefix",
            "range_start",
            "range_end",
            "next_number",
            "is_active",
            "is_depleted",
            "next_invoice_no",
            "note",
        ]
        read_only_fields = [
            "id",
            "invoice_type_code",
            "invoice_type_name",
            "warehouse_name",
            "period_state",
            "is_depleted",
            "next_invoice_no",
        ]

    def validate_prefix(self, value):
        return value.strip().upper()

    def validate_period_start(self, value):
        if value is not None and not invoice_periods.is_start(value):
            raise serializers.ValidationError("期別是兩個月一期,從奇數月 1 日開始")
        return value

    def validate(self, data):
        track = self.instance

        def now(name):
            return data[name] if name in data else getattr(track, name, None)

        start, end, prefix = now("range_start"), now("range_end"), now("prefix")
        if end < start:
            raise serializers.ValidationError({"range_end": "迄號不可小於起號"})
        if end > 99999999:
            raise serializers.ValidationError({"range_end": "發票號碼是 8 位數"})

        if track is None:
            if data.get("warehouse") is None:
                raise serializers.ValidationError({"warehouse": "請選門市"})
            if data.get("period_start") is None:
                raise serializers.ValidationError({"period_start": "請選期別"})
            nxt = data.get("next_number")
            if nxt is None:
                data["next_number"] = start
            elif not start <= nxt <= end + 1:
                raise serializers.ValidationError(
                    {"next_number": f"下一張號碼必須介於 {start} ~ {end + 1}"}
                )
        else:
            if "warehouse" in data and data["warehouse"] is None and track.warehouse_id is not None:
                raise serializers.ValidationError({"warehouse": "請選門市"})
            if "period_start" in data and data["period_start"] is None and track.period_start is not None:
                raise serializers.ValidationError({"period_start": "請選期別"})
            if "next_number" in data and data["next_number"] != track.next_number:
                raise serializers.ValidationError({"next_number": "下一張不能直接改,請用「跳號」"})
            data.pop("next_number", None)
            identity = [n for n in ("prefix", "range_start", "invoice_type") if n in data and data[n] != getattr(track, n)]
            if identity and track_in_use(track):
                raise serializers.ValidationError(
                    {identity[0]: "這條字軌已經開過發票或跳過號,字軌、起號、類型不能改"}
                )
            if start != track.range_start and track.next_number == track.range_start:
                data["next_number"] = start          # 還沒用過的字軌改起號:下一張跟著起號走
            elif not start <= track.next_number <= end + 1:
                raise serializers.ValidationError(
                    {"range_end": f"下一張是 {track.format_number(track.next_number)},起號到迄號要包含它的前一張"}
                )

        request = self.context.get("request")
        tenant = getattr(request, "tenant", None) or getattr(track, "tenant", None)
        if tenant is not None:
            clash = InvoiceTrack.objects.for_tenant(tenant).filter(
                prefix__iexact=prefix, range_start__lte=end, range_end__gte=start
            )
            if track is not None:
                clash = clash.exclude(pk=track.pk)
            other = clash.first()
            if other is not None:
                raise serializers.ValidationError(
                    {"range_start": f"號碼跟另一條字軌重疊:{other.format_number(other.range_start)} ~ {other.format_number(other.range_end)}"}
                )
        return data


class InvoiceTrackJumpSerializer(serializers.ModelSerializer):
    """跳號紀錄(只讀)。"""

    from_no = serializers.SerializerMethodField()
    to_no = serializers.SerializerMethodField()
    by = serializers.SerializerMethodField()

    class Meta:
        model = InvoiceTrackJump
        fields = ["id", "created_at", "from_number", "to_number", "from_no", "to_no", "reason", "by"]

    def get_from_no(self, jump) -> str:
        return jump.track.format_number(jump.from_number)

    def get_to_no(self, jump) -> str:
        return jump.track.format_number(jump.to_number)

    def get_by(self, jump) -> str:
        """跟銷貨單「誰作廢的」同一個原則:不是這家公司的人(平台管理員代為操作)只寫「平台管理員」。"""
        user = jump.created_by
        if user is None:
            return ""
        profile = getattr(user, "profile", None)
        if profile is None or profile.tenant_id != jump.tenant_id:
            return "平台管理員"
        return user.username


class PaymentMethodSerializer(TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    # 未指定 code → 自動產生(pm_xxxxxx);使用者只認 name
    code = serializers.CharField(max_length=20, required=False, allow_blank=True)

    class Meta:
        model = PaymentMethod
        fields = [
            "id",
            "code",
            "name",
            "kind",
            "kind_label",
            "sort_order",
            "is_active",
            "is_default",
            "note",
        ]
        read_only_fields = ["id", "kind_label"]

    def create(self, validated_data):
        if not validated_data.get("code"):
            import secrets

            tenant = validated_data["tenant"]
            for _ in range(8):
                candidate = f"pm_{secrets.token_hex(3)}"
                if not PaymentMethod.objects.for_tenant(tenant).filter(
                    code=candidate
                ).exists():
                    validated_data["code"] = candidate
                    break
            else:
                raise serializers.ValidationError(
                    {"code": "自動產生代碼衝突,請重試"}
                )
        return super().create(validated_data)
