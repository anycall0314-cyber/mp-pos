"""調撥單兩階段 service。

階段 1:dispatch_transfer_order(來源倉送出)
- 序號商品:serial.status = in_transit、warehouse = None
- 配件:from_warehouse balance.qty -= it.qty;快照當下單台成本到 it.unit_cost_at_dispatch
- 寫 StockMovement TRANSFER_OUT
- status = dispatched

階段 2:confirm_transfer_order(目的倉確認入庫)
- 序號商品:serial.status = in_stock、warehouse = to_warehouse
- 配件:to_warehouse balance.qty += it.qty,依 it.unit_cost_at_dispatch 重算加權平均
- 寫 StockMovement TRANSFER_IN
- status = confirmed

作廢 void_transfer_order(智能回滾)
- 從 dispatched:來源倉恢復(序號回 in_stock、配件 qty 加回)
- 從 confirmed:來源倉恢復、目的倉扣除
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.inventory.models import ProductSerial, StockBalance, StockMovement

from .models import TransferOrder

CENTS = Decimal("0.01")


class TransferOrderError(Exception):
    """調撥業務錯誤;view 轉成 400。"""


def _validate_dispatch(to: TransferOrder, items):
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


def dispatch_transfer_order(to: TransferOrder) -> TransferOrder:
    """來源倉送出。建立時自動呼叫。"""
    items = list(
        to.items.select_related("product")
        .prefetch_related("serials__serial")
        .all()
    )
    _validate_dispatch(to, items)

    with transaction.atomic():
        for it in items:
            product = it.product
            if product.requires_serial:
                for sos in it.serials.select_related("serial").all():
                    s = sos.serial
                    s.status = ProductSerial.Status.IN_TRANSIT
                    s.warehouse = None
                    s.save(update_fields=["status", "warehouse"])
                    StockMovement.objects.create(
                        tenant=to.tenant,
                        serial=s,
                        movement_type=StockMovement.MovementType.TRANSFER_OUT,
                        from_warehouse=to.from_warehouse,
                        to_warehouse=to.to_warehouse,
                        ref_doc_type="transfer_order",
                        ref_doc_id=to.id,
                        note=f"調撥單 {to.no} 派發 第 {it.line_no} 行",
                    )
            else:
                src = StockBalance.objects.get(
                    tenant=to.tenant,
                    product=product,
                    warehouse=to.from_warehouse,
                )
                it.unit_cost_at_dispatch = src.weighted_avg_cost
                it.save(update_fields=["unit_cost_at_dispatch"])
                src.qty -= it.qty
                if src.qty == 0:
                    src.weighted_avg_cost = Decimal("0")
                src.save(update_fields=["qty", "weighted_avg_cost"])
                StockMovement.objects.create(
                    tenant=to.tenant,
                    product=product,
                    qty=it.qty,
                    movement_type=StockMovement.MovementType.TRANSFER_OUT,
                    from_warehouse=to.from_warehouse,
                    to_warehouse=to.to_warehouse,
                    ref_doc_type="transfer_order",
                    ref_doc_id=to.id,
                    note=f"調撥單 {to.no} 派發 第 {it.line_no} 行 {product.sku} ×{it.qty}",
                )

        to.status = TransferOrder.Status.DISPATCHED
        to.save(update_fields=["status"])
    return to


def confirm_transfer_order(to: TransferOrder, user=None) -> TransferOrder:
    """目的倉確認入庫。"""
    if to.is_void:
        raise TransferOrderError("此單已作廢,無法確認")
    if to.status != TransferOrder.Status.DISPATCHED:
        raise TransferOrderError("此單非派發中狀態,無法確認")

    items = list(
        to.items.select_related("product")
        .prefetch_related("serials__serial")
        .all()
    )

    with transaction.atomic():
        now = timezone.now()
        for it in items:
            product = it.product
            if product.requires_serial:
                for sos in it.serials.select_related("serial").all():
                    s = sos.serial
                    if s.status != ProductSerial.Status.IN_TRANSIT:
                        raise TransferOrderError(
                            f"序號 {s.serial_no} 非調撥中狀態,無法確認"
                        )
                    s.status = ProductSerial.Status.IN_STOCK
                    s.warehouse = to.to_warehouse
                    s.save(update_fields=["status", "warehouse"])
                    StockMovement.objects.create(
                        tenant=to.tenant,
                        serial=s,
                        movement_type=StockMovement.MovementType.TRANSFER_IN,
                        from_warehouse=to.from_warehouse,
                        to_warehouse=to.to_warehouse,
                        ref_doc_type="transfer_order",
                        ref_doc_id=to.id,
                        note=f"調撥單 {to.no} 確認 第 {it.line_no} 行",
                    )
            else:
                dst, _ = StockBalance.objects.get_or_create(
                    tenant=to.tenant,
                    product=product,
                    warehouse=to.to_warehouse,
                )
                new_qty = dst.qty + it.qty
                if new_qty > 0:
                    old_value = Decimal(dst.qty) * dst.weighted_avg_cost
                    moved_value = Decimal(it.qty) * it.unit_cost_at_dispatch
                    dst.weighted_avg_cost = (
                        (old_value + moved_value) / Decimal(new_qty)
                    ).quantize(CENTS)
                dst.qty = new_qty
                dst.save(update_fields=["qty", "weighted_avg_cost"])
                StockMovement.objects.create(
                    tenant=to.tenant,
                    product=product,
                    qty=it.qty,
                    movement_type=StockMovement.MovementType.TRANSFER_IN,
                    from_warehouse=to.from_warehouse,
                    to_warehouse=to.to_warehouse,
                    ref_doc_type="transfer_order",
                    ref_doc_id=to.id,
                    note=f"調撥單 {to.no} 確認 第 {it.line_no} 行 {product.sku} ×{it.qty}",
                )

        to.status = TransferOrder.Status.CONFIRMED
        to.confirmed_at = now
        to.confirmed_by = user
        to.save(update_fields=["status", "confirmed_at", "confirmed_by"])
    return to


def void_transfer_order(to: TransferOrder) -> TransferOrder:
    """智能回滾。
    - 派發中:序號 in_transit → in_stock 回來源倉;配件 balance 回補來源倉
    - 已完成:序號從目的倉移回來源倉(必須仍 in_stock);配件目的倉扣、來源倉加
    """
    if to.is_void:
        raise TransferOrderError("此單已作廢")

    items = list(
        to.items.select_related("product")
        .prefetch_related("serials__serial")
        .all()
    )
    is_confirmed = to.status == TransferOrder.Status.CONFIRMED

    # 預檢
    for it in items:
        product = it.product
        if product.requires_serial:
            for sos in it.serials.select_related("serial").all():
                s = sos.serial
                if is_confirmed:
                    if s.status != ProductSerial.Status.IN_STOCK:
                        raise TransferOrderError(
                            f"序號 {s.serial_no} 已不在 in_stock,無法作廢"
                        )
                    if s.warehouse_id != to.to_warehouse_id:
                        raise TransferOrderError(
                            f"序號 {s.serial_no} 已不在目的倉,無法作廢"
                        )
                else:
                    if s.status != ProductSerial.Status.IN_TRANSIT:
                        raise TransferOrderError(
                            f"序號 {s.serial_no} 已不在調撥中,無法作廢"
                        )
        else:
            if is_confirmed:
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
                    s.status = ProductSerial.Status.IN_STOCK
                    s.warehouse = to.from_warehouse
                    s.save(update_fields=["status", "warehouse"])
                    StockMovement.objects.create(
                        tenant=to.tenant,
                        serial=s,
                        movement_type=StockMovement.MovementType.VOID,
                        from_warehouse=to.to_warehouse if is_confirmed else None,
                        to_warehouse=to.from_warehouse,
                        ref_doc_type="transfer_order",
                        ref_doc_id=to.id,
                        note=f"調撥單 {to.no} 作廢({to.get_status_display()})",
                    )
            else:
                if is_confirmed:
                    dst = StockBalance.objects.get(
                        tenant=to.tenant,
                        product=product,
                        warehouse=to.to_warehouse,
                    )
                    dst.qty -= it.qty
                    if dst.qty == 0:
                        dst.weighted_avg_cost = Decimal("0")
                    dst.save(update_fields=["qty", "weighted_avg_cost"])

                # 回補來源倉
                src, _ = StockBalance.objects.get_or_create(
                    tenant=to.tenant,
                    product=product,
                    warehouse=to.from_warehouse,
                )
                # 加權平均:用 unit_cost_at_dispatch 還原
                new_qty = src.qty + it.qty
                if new_qty > 0:
                    old_value = Decimal(src.qty) * src.weighted_avg_cost
                    restore_value = Decimal(it.qty) * it.unit_cost_at_dispatch
                    src.weighted_avg_cost = (
                        (old_value + restore_value) / Decimal(new_qty)
                    ).quantize(CENTS)
                src.qty = new_qty
                src.save(update_fields=["qty", "weighted_avg_cost"])

                StockMovement.objects.create(
                    tenant=to.tenant,
                    product=product,
                    qty=it.qty,
                    movement_type=StockMovement.MovementType.VOID,
                    from_warehouse=to.to_warehouse if is_confirmed else None,
                    to_warehouse=to.from_warehouse,
                    ref_doc_type="transfer_order",
                    ref_doc_id=to.id,
                    note=f"調撥單 {to.no} 作廢({to.get_status_display()}) {product.sku} ×{it.qty}",
                )

        to.is_void = True
        to.save(update_fields=["is_void"])
    return to
