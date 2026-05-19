"""發票字軌取號 service。"""
from django.db import transaction

from .models import InvoiceTrack, InvoiceType


class InvoiceTrackError(Exception):
    pass


def peek_next_invoice_no(tenant, invoice_type_code: str):
    """非鎖定預覽下一張發票號碼。"""
    if not invoice_type_code or invoice_type_code == "none":
        return None
    try:
        invoice_type = InvoiceType.objects.for_tenant(tenant).get(
            code=invoice_type_code
        )
    except InvoiceType.DoesNotExist:
        return None
    track = (
        InvoiceTrack.objects.for_tenant(tenant)
        .filter(invoice_type=invoice_type, is_active=True)
        .order_by("id")
        .first()
    )
    if not track:
        return None
    while track and track.next_number > track.range_end:
        # 跳過已用完的字軌
        track = (
            InvoiceTrack.objects.for_tenant(tenant)
            .filter(
                invoice_type=invoice_type,
                is_active=True,
                id__gt=track.id,
            )
            .order_by("id")
            .first()
        )
    if not track:
        return None
    return track.format_number(track.next_number)


def assign_invoice_no(tenant, invoice_type_code: str) -> str:
    """以 row-level lock 原子地取出下一張發票號碼,並把 next_number 遞增。

    取不到字軌時拋 InvoiceTrackError(call site 自行決定是否要擋下單)。
    """
    if not invoice_type_code or invoice_type_code == "none":
        raise InvoiceTrackError("發票類型為「免用」或未指定,不取號")

    with transaction.atomic():
        try:
            invoice_type = InvoiceType.objects.for_tenant(tenant).get(
                code=invoice_type_code
            )
        except InvoiceType.DoesNotExist:
            raise InvoiceTrackError(
                f"找不到發票類型 {invoice_type_code}"
            )
        # SELECT ... FOR UPDATE,序列化避免兩張單拿到同一號
        qs = (
            InvoiceTrack.objects.for_tenant(tenant)
            .select_for_update()
            .filter(invoice_type=invoice_type, is_active=True)
            .order_by("id")
        )
        for track in qs:
            if track.next_number <= track.range_end:
                num = track.next_number
                track.next_number = num + 1
                track.save(update_fields=["next_number"])
                return track.format_number(num)
        raise InvoiceTrackError(
            f"發票類型「{invoice_type.name}」沒有可用字軌,請至系統設定新增"
        )
