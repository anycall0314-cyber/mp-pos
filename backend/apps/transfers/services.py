"""調撥單儲存即生效 service。

單步調撥:從來源倉直接搬到目的倉,沒有 in_transit 中間狀態。
- 序號商品:逐隻指定序號;serial.warehouse from → to,狀態維持 in_stock
- 配件:from_wh.balance.qty -= qty;to_wh.balance.qty += qty;
  目的倉加權平均依「移入單位成本(取自來源倉的 avg)」重算
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.inventory.models import ProductSerial, StockBalance, StockMovement

from .models import TransferOrder

CENTS = Decimal("0.01")


class TransferOrderError(Exception):
    """調撥業務錯誤;view 轉成 400。"""


def _validate(to: TransferOrder, items):
    if not items:
        raise TransferOrderError("無明細,無法過帳")
    if to.from_warehouse_id == to.to_warehouse_id:
        raise TransferOrderError("來源倉與目的倉不可相同")

    seen_serials = set()
    for it in items:
        product = it.product
        if product.is_virtual:
            raise TransferOrderError(
                f"第 {it.line_no} 行虛擬商品 {product.sku} 不可調撥"
            )
        if it.qty <= 0:
            raise TransferOrderError(f"第 {it.line_no} 行數量需 > 0")

        item_serials = list(it.serials.select_related("serial").all())
        if product.requires_serial:
            if len(item_serials) != it.qty:
                raise TransferOrderError(
                    f"第 {it.line_no} 行需 {it.qty} 個序號,目前 {len(item_serials)} 個"
                )
            for sos in item_serials:
                s = sos.serial
                if s.product_id != product.id:
                    raise TransferOrderError(
                        f"第 {it.line_no} 行序號 {s.serial_no} 不屬於商品 {product.sku}"
                    )
                if s.status != ProductSerial.Status.IN_STOCK:
                    raise TransferOrderError(
                        f"第 {it.line_no} 行序號 {s.serial_no} 狀態為「{s.get_status_display()}」,不可調撥"
                    )
                if s.warehouse_id != to.from_warehouse_id:
                    raise TransferOrderError(
                        f"第 {it.line_no} 行序號 {s.serial_no} 不在來源倉"
                    )
                if s.id in seen_serials:
                    raise TransferOrderError(f"序號 {s.serial_no} 重複出現")
                seen_serials.add(s.id)
        else:
            if item_serials:
                raise TransferOrderError(
                    f"第 {it.line_no} 行配件 {product.sku} 不可指定序號"
                )
            bal = StockBalance.objects.filter(
                tenant=to.tenant,
                product=product,
                warehouse=to.from_warehouse,
            ).first()
            current = bal.qty if bal else 0
            if current < it.qty:
                raise TransferOrderError(
                    f"第 {it.line_no} 行 {product.sku} 在 {to.from_warehouse.code} "
                    f"現有 {current},不足調撥 {it.qty}"
                )


def commit_transfer_order(to: TransferOrder) -> TransferOrder:
    items = list(
        to.items.select_related("product")
        .prefetch_related("serials__serial")
        .all()
    )
    _validate(to, items)

    with transaction.atomic():
        for it in items:
            product = it.product
            if product.requires_serial:
                for sos in it.serials.select_related("serial").all():
                    s = sos.serial
                    s.warehouse = to.to_warehouse
                    s.save(update_fields=["warehouse"])
                    StockMovement.objects.create(
                        tenant=to.tenant,
                        serial=s,
                        movement_type=StockMovement.MovementType.TRANSFER_OUT,
                        from_warehouse=to.from_warehouse,
                        to_warehouse=to.to_warehouse,
                        ref_doc_type="transfer_order",
                        ref_doc_id=to.id,
                        note=f"調撥單 {to.no} 第 {it.line_no} 行",
                    )
            else:
                # 配件:from 扣、to 加,目的倉加權平均依移入成本重算
                src = StockBalance.objects.get(
                    tenant=to.tenant,
                    product=product,
                    warehouse=to.from_warehouse,
                )
                move_unit_cost = src.weighted_avg_cost  # 用來源倉的平均成本
                src.qty -= it.qty
                if src.qty == 0:
                    src.weighted_avg_cost = Decimal("0")
                src.save(update_fields=["qty", "weighted_avg_cost"])

                dst, _ = StockBalance.objects.get_or_create(
                    tenant=to.tenant,
                    product=product,
                    warehouse=to.to_warehouse,
                )
                new_qty = dst.qty + it.qty
                if new_qty > 0:
                    old_value = Decimal(dst.qty) * dst.weighted_avg_cost
                    moved_value = Decimal(it.qty) * move_unit_cost
                    dst.weighted_avg_cost = (
                        (old_value + moved_value) / Decimal(new_qty)
                    ).quantize(CENTS)
                dst.qty = new_qty
                dst.save(update_fields=["qty", "weighted_avg_cost"])

                StockMovement.objects.create(
                    tenant=to.tenant,
                    product=product,
                    qty=it.qty,
                    movement_type=StockMovement.MovementType.TRANSFER_OUT,
                    from_warehouse=to.from_warehouse,
                    to_warehouse=to.to_warehouse,
                    ref_doc_type="transfer_order",
                    ref_doc_id=to.id,
                    note=f"調撥單 {to.no} 第 {it.line_no} 行 {product.sku} ×{it.qty}",
                )
    return to


def void_transfer_order(to: TransferOrder) -> TransferOrder:
    if to.is_void:
        raise TransferOrderError("此單已作廢")

    items = list(
        to.items.select_related("product")
        .prefetch_related("serials__serial")
        .all()
    )
    # 預檢:序號是否仍在目的倉且 in_stock;配件目的倉是否還有量可退
    for it in items:
        product = it.product
        if product.requires_serial:
            for sos in it.serials.select_related("serial").all():
                s = sos.serial
                if s.status != ProductSerial.Status.IN_STOCK:
                    raise TransferOrderError(
                        f"序號 {s.serial_no} 已不在 in_stock,無法作廢"
                    )
                if s.warehouse_id != to.to_warehouse_id:
                    raise TransferOrderError(
                        f"序號 {s.serial_no} 已不在目的倉,無法作廢"
                    )
        else:
            bal = StockBalance.objects.filter(
                tenant=to.tenant,
                product=product,
                warehouse=to.to_warehouse,
            ).first()
            current = bal.qty if bal else 0
            if current < it.qty:
                raise TransferOrderError(
                    f"商品 {product.sku} 在目的倉 {to.to_warehouse.code} "
                    f"現有 {current},無法退回本單的 {it.qty} 件"
                )

    with transaction.atomic():
        for it in items:
            product = it.product
            if product.requires_serial:
                for sos in it.serials.select_related("serial").all():
                    s = sos.serial
                    s.warehouse = to.from_warehouse
                    s.save(update_fields=["warehouse"])
                    StockMovement.objects.create(
                        tenant=to.tenant,
                        serial=s,
                        movement_type=StockMovement.MovementType.VOID,
                        from_warehouse=to.to_warehouse,
                        to_warehouse=to.from_warehouse,
                        ref_doc_type="transfer_order",
                        ref_doc_id=to.id,
                        note=f"調撥單 {to.no} 作廢",
                    )
            else:
                dst = StockBalance.objects.get(
                    tenant=to.tenant,
                    product=product,
                    warehouse=to.to_warehouse,
                )
                dst.qty -= it.qty
                if dst.qty == 0:
                    dst.weighted_avg_cost = Decimal("0")
                dst.save(update_fields=["qty", "weighted_avg_cost"])

                src, _ = StockBalance.objects.get_or_create(
                    tenant=to.tenant,
                    product=product,
                    warehouse=to.from_warehouse,
                )
                src.qty += it.qty
                src.save(update_fields=["qty"])

                StockMovement.objects.create(
                    tenant=to.tenant,
                    product=product,
                    qty=it.qty,
                    movement_type=StockMovement.MovementType.VOID,
                    from_warehouse=to.to_warehouse,
                    to_warehouse=to.from_warehouse,
                    ref_doc_type="transfer_order",
                    ref_doc_id=to.id,
                    note=f"調撥單 {to.no} 作廢 {product.sku} ×{it.qty}",
                )

        to.is_void = True
        to.save(update_fields=["is_void"])
    return to
